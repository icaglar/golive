#!/usr/bin/env bash
# golive bootstrap for an existing Ubuntu 22.04/24.04 server (any provider), run once as root:
#   ssh -p <port> root@<ip> "DEPLOY_USER=deploy SSH_PUBLIC_KEY='$(cat ~/.ssh/id_ed25519.pub)' PRIVATE_RANGE=10.0.0.0/16 bash -s" < bootstrap.sh
# Same result as templates/cloud-init.yaml: deploy user with key-only SSH, root login off,
# Docker with log rotation, ufw, fail2ban, unattended security upgrades with a reboot window, swap
# on small servers. Safe to re-run.
#
# Environment:
#   DEPLOY_USER      deploy user (default deploy)
#   SSH_PUBLIC_KEY   required: key that may log in as DEPLOY_USER
#   SSH_PORT         port to allow in ufw (default 22). The ports sshd currently listens on
#                    (sshd -T) are ALWAYS kept allowed too, so a custom port never locks you out.
#                    bootstrap.sh does not change the sshd port.
#   PRIVATE_RANGE    private network CIDR (default 10.0.0.0/16); the private services' ports
#                    (5432 3306 9100 9187 9104 8080 9180 9200) are allowed from it only
#   REBOOT_TIME      automatic reboot window for updates, HH:MM (default 04:00)
#   GOLIVE_CONFIRM   set to 1 to continue when the pre-flight finds anything unexpected listening,
#                    running in Docker, or a control panel (cPanel/Plesk/...). Without it, the
#                    script prints the findings and stops BEFORE changing anything.
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
SSH_PORT="${SSH_PORT:-22}"
PRIVATE_RANGE="${PRIVATE_RANGE:-10.0.0.0/16}"
REBOOT_TIME="${REBOOT_TIME:-04:00}"
: "${SSH_PUBLIC_KEY:?set SSH_PUBLIC_KEY to the public key that may log in as $DEPLOY_USER}"
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] || { echo "SSH_PORT must be a number" >&2; exit 1; }
[[ "$REBOOT_TIME" =~ ^[0-2][0-9]:[0-5][0-9]$ ]] || { echo "REBOOT_TIME must be HH:MM" >&2; exit 1; }
[[ "$PRIVATE_RANGE" =~ ^[0-9a-fA-F:.]+/[0-9]+$ ]] || { echo "PRIVATE_RANGE must be a CIDR like 10.0.0.0/16" >&2; exit 1; }
PRIVATE_PORTS="5432 3306 9100 9187 9104 8080 9180 9200"

# ---------- pre-flight: what already runs here? (read-only) ----------
SSHD_PORTS="$( (sshd -T 2>/dev/null || true) | awk '$1=="port"{print $2}' | sort -un | tr '\n' ' ')"
[ -n "$SSHD_PORTS" ] || SSHD_PORTS="$SSH_PORT"
echo "== golive pre-flight =="
echo "sshd listens on: $SSHD_PORTS(these stay allowed in ufw; golive port: $SSH_PORT)"
echo "-- listening TCP ports --"
LISTEN="$( (ss -H -ltnp 2>/dev/null || true) | awk '{print $4 "\t" $NF}')"
echo "${LISTEN:-none visible}"
if command -v docker >/dev/null 2>&1; then
  echo "-- docker containers --"
  docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' 2>/dev/null || true
fi
PANEL=""
[ -d /usr/local/cpanel ] && PANEL="cPanel"
[ -d /usr/local/psa ] && PANEL="Plesk"
[ -d /usr/local/directadmin ] && PANEL="DirectAdmin"
[ -d /usr/local/hestia ] && PANEL="HestiaCP"
[ -d /usr/local/CyberCP ] && PANEL="CyberPanel"
command -v aaPanel >/dev/null 2>&1 && PANEL="aaPanel"
[ -d /www/server/panel ] && PANEL="aaPanel/BT"
[ -n "$PANEL" ] && echo "-- control panel detected: $PANEL (its own firewall and web server will conflict with this script)"
echo "-- existing firewall --"
(ufw status 2>/dev/null | head -n 5) || true
(iptables -S 2>/dev/null | wc -l | sed 's/^/iptables rules: /') || true

# "Unexpected" = a listening port other than the sshd ports, 80/443, and local-only addresses (53 is systemd-resolved).
UNEXPECTED="$(echo "$LISTEN" | awk -F'\t' 'NF{print $1}' | grep -Ev '^(127\.|\[::1\]|localhost)' | sed -E 's/.*:([0-9]+)$/\1/' | sort -un | while read -r p; do
  case " $SSHD_PORTS 80 443 53 " in *" $p "*) ;; *) echo -n "$p ";; esac
done)"
RUNNING="$( (docker ps -q 2>/dev/null || true) | wc -l)"
if { [ -n "$UNEXPECTED" ] || [ -n "$PANEL" ] || [ "$RUNNING" -gt 0 ]; } && [ "${GOLIVE_CONFIRM:-0}" != "1" ]; then
  echo
  echo "STOP: this server is not empty (unexpected ports: ${UNEXPECTED:-none}; panel: ${PANEL:-none}; containers: $RUNNING)." >&2
  echo "bootstrap.sh restarts Docker, replaces ufw rules and hardens SSH. Review the list above, then re-run with GOLIVE_CONFIRM=1" >&2
  echo "if that is what you want. Nothing has been changed." >&2
  exit 3
fi
echo "== pre-flight done =="

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y ca-certificates curl git ufw fail2ban unattended-upgrades

# Docker (official convenience script) and log rotation. An existing daemon.json is backed up first.
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
install -d -m 0755 /etc/docker
DJ=/etc/docker/daemon.json
LOGOPTS='{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"5"}}'
if [ -s "$DJ" ]; then
  if ! grep -q '"max-size"' "$DJ"; then
    cp -a "$DJ" "$DJ.golive-backup-$(date +%Y%m%d%H%M%S)"
    if command -v jq >/dev/null 2>&1 && jq -e . "$DJ" >/dev/null 2>&1; then
      jq --argjson l "$LOGOPTS" '. * $l' "$DJ" > "$DJ.new" && mv "$DJ.new" "$DJ"
    else
      echo "$LOGOPTS" > "$DJ"
      echo "note: daemon.json replaced (no jq or not valid JSON); the old file is saved as $DJ.golive-backup-*"
    fi
  fi
else
  echo "$LOGOPTS" > "$DJ"
fi
systemctl enable --now docker
systemctl restart docker

# Deploy user with the key, sudo without password, docker group
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$DEPLOY_USER"
fi
usermod -aG sudo,docker "$DEPLOY_USER"
passwd -l "$DEPLOY_USER" >/dev/null
install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
AUTH="/home/$DEPLOY_USER/.ssh/authorized_keys"
touch "$AUTH"
grep -qxF "$SSH_PUBLIC_KEY" "$AUTH" || echo "$SSH_PUBLIC_KEY" >> "$AUTH"
chown "$DEPLOY_USER:$DEPLOY_USER" "$AUTH"
chmod 0600 "$AUTH"
echo "$DEPLOY_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-golive-$DEPLOY_USER"
chmod 0440 "/etc/sudoers.d/90-golive-$DEPLOY_USER"

# SSH hardening (00- so it wins over later drop-ins); only after the key is in place. The port is not changed.
cat > /etc/ssh/sshd_config.d/00-golive.conf <<'EOS'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
EOS
sshd -t
systemctl restart ssh || systemctl restart sshd

# fail2ban and automatic security updates (with a reboot window so kernel updates apply)
cat > /etc/fail2ban/jail.d/sshd.local <<'EOS'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
EOS
systemctl enable --now fail2ban
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOS'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOS
cat > /etc/apt/apt.conf.d/52golive-unattended <<EOS
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-WithUsers "true";
Unattended-Upgrade::Automatic-Reboot-Time "$REBOOT_TIME";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOS

# Swap for small servers: 2 GB when RAM <= 8 GB and no swap exists
if [ -z "$(swapon --show --noheadings)" ] && [ ! -e /swapfile ]; then
  MEM_KB="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
  if [ "$MEM_KB" -le 8388608 ]; then
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo 'vm.swappiness=10' > /etc/sysctl.d/99-golive-swap.conf
    sysctl -p /etc/sysctl.d/99-golive-swap.conf >/dev/null
  fi
fi

# Host firewall (Docker-published ports bypass ufw: see firewall_rules.py --format docker-user).
# SSH ports are allowed BEFORE ufw is enabled: the configured one and every port sshd listens on now.
ufw default deny incoming
ufw default allow outgoing
for p in $SSHD_PORTS $SSH_PORT; do ufw allow "$p/tcp"; done
ufw allow 80/tcp
ufw allow 443/tcp
for p in $PRIVATE_PORTS; do ufw allow from "$PRIVATE_RANGE" to any port "$p" proto tcp; done
ufw --force enable

install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" /srv/app /srv/backups
echo "golive bootstrap done: log in as $DEPLOY_USER (ssh port $SSH_PORT); root login is now disabled."
