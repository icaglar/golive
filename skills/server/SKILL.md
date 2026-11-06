---
name: server
description: Creates and hardens the servers of a project at the provider the user chooses - Hetzner Cloud with hcloud by default, or DigitalOcean, Vultr, Linode, AWS Lightsail, Scaleway, or any existing VPS (including Turkish VPS providers) over SSH with a bootstrap script. Uploads the SSH key, creates a Cloudflare-only firewall, picks type and location with the user (monthly price shown, data residency respected), boots Ubuntu 24.04 with a cloud-init that adds a deploy user, disables root and password login, installs Docker, ufw, fail2ban, automatic updates with a reboot window, then sets reverse DNS. Runs per environment (staging first, then prod). Use for the server go-live step, or when the user says "sunucu aç", "sunucu kur", "SSH key ekle", "firewall ayarla", "rDNS ayarla", "Hetzner'de sunucu".
---

# Server

Talk to the user in the language they use. State lives in `.claude/golive.yaml`: `server_defaults` (provider, image, deploy_user, ssh_key, ssh_port, ssh_from, firewall, private_network, private_range) and `servers.<name>` (role, env, type, location, ipv4, ipv6, private_ip, rdns). An old file with a single `server:` block is read as `servers.app-prod` plus `server_defaults`; rewrite it in the new shape when you next write.

## 0. Plan the machines

From `environments.layout` and `profile.budget`: `separate-servers` = `app-staging` and `app-prod`; `same-server` = one `app-prod` that runs both stacks (see the deploy skill); `prod-only` = `app-prod`. Dedicated DB, replica and monitoring servers are created by the `database` and `monitoring` skills with this same procedure. Run the steps below **per server, staging first, then prod**, and record `steps.server.envs.<env>`; the step is done when every env is done or skipped.

**Provider.** Use `server_defaults.provider`; if unset ask: Hetzner Cloud (default) / DigitalOcean / another cloud / an existing server or VPS. Everything provider-specific (CLI, firewall, private network, volumes, rDNS, mail ports) is in `${CLAUDE_PLUGIN_ROOT}/skills/server/providers.md`; run the create command's `--help` before using flags. The Hetzner (`hcloud`) commands follow; other providers reach the same end state.

**Data residency.** `profile.data_residency` decides the location (EU: Hetzner fsn1/nbg1/hel1; US: ash/hil; `tr`: a Turkish provider or existing server; `any`: closest to the users). Mention it when it limits the choice.

## 1. Access and SSH key

`hcloud context active` must print a context; otherwise the user creates a Read & Write API token and runs `hcloud context create <project>` in their own terminal. Never ask for the token in chat or write it to a file. There is no official Hetzner MCP; do not use community ones (no rDNS or cloud-init).

Public key: `~/.ssh/id_ed25519.pub`, else `id_rsa.pub`; if none, the user runs `ssh-keygen -t ed25519` (they choose the passphrase). Reuse a matching key (`hcloud ssh-key list -o json`, compare `ssh-keygen -lf <pub> -E md5`), else `hcloud ssh-key create --name <user>-<machine> --public-key-from-file <pub>`. Record `server_defaults.ssh_key`.

## 2. Firewall

Docker-published ports bypass ufw, so the cloud firewall is the real barrier. Ask the SSH port (default 22; `server_defaults.ssh_port`).

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/firewall_rules.py" --ssh-from <ip>/32 --ssh-port <port> > /tmp/golive-rules.json
hcloud firewall create --name golive-web --rules-file /tmp/golive-rules.json
```

80/443 are open only to Cloudflare's ranges. Find the user's IP with `curl --noproxy '*' -4 -s https://api.ipify.org` and **confirm it** (VPN or changing IP; the script warns when SSH is open to everyone). Record `server_defaults.ssh_from`. Without Cloudflare (`domain.dns_provider` not cloudflare) use `--public`. Firewalls are free. DB and monitoring servers get a firewall with SSH only.

**Weekly range refresh.** On Cloudflare setups install the check on every web-facing server after it boots: copy `${CLAUDE_PLUGIN_ROOT}/scripts/firewall_rules.py` to `/opt/golive/firewall_rules.py` and `templates/firewall/golive-cf-ranges.{service,timer}` + `golive-cf-ranges.sh` as described in the header of that service file, then `systemctl enable --now golive-cf-ranges.timer`. It only alerts (`CloudflareRangesChanged`); applying a change is a manual, reviewed step.

## 3. Type, location, price

`hcloud server-type list` and `hcloud location list`. Suggest a small type for one app with Postgres (2-4 vCPU, 4-8 GB); staging can be smaller. Show the monthly price for that location (`hcloud server-type describe <type>`), plus the separately billed primary IPv4, and ask before creating. After creating, append to `costs:` one entry per billable item, e.g. `{item: "app-staging cx23 fsn1", monthly: <price>, currency: EUR, step: server}` and one for the IPv4.

## 4. Cloud-init

Render `${CLAUDE_PLUGIN_ROOT}/templates/cloud-init.yaml` to a temp file, replacing `__DEPLOY_USER__`, `__SSH_PUBLIC_KEY__` (full key), `__SSH_PORT__`, `__PRIVATE_RANGE__` (`server_defaults.private_range`) and `__REBOOT_TIME__` (default 04:00; ask if the app has a quiet window). It opens the private-service ports (5432 3306 9100 9187 9104 8080 9180 9200) from the private range only.

## 5. Create

```bash
hcloud server create --name <name> --type <type> --image ubuntu-24.04 --location <loc> \
  --ssh-key <key name> --firewall golive-web --user-data-from-file /tmp/golive-cloud-init.yaml \
  --enable-protection delete,rebuild -o json
```

Record `servers.<name>`: role, env, type, location, ipv4, ipv6 as `<prefix>::1` (Hetzner reports a /64; the server answers on `::1`; AAAA and rDNS use it). A confirmation prompt is expected.

**Private network** (needed for DB and monitoring servers; free): Hetzner: `hcloud network create --name golive-net --ip-range <private_range>`, `hcloud network add-subnet golive-net --network-zone eu-central --type cloud --ip-range 10.0.0.0/24`, `hcloud server attach-to-network <name> --network golive-net --ip 10.0.0.<n>`; record `private_ip`. Other providers: providers.md (VPC row; check the provider docs).

**Volumes** (databases, uploads): `hcloud volume create --size <GB> --server <name> --automount --format ext4`; billable, append to `costs:`. Other providers: providers.md.

## 6. Existing server instead (bootstrap.sh)

Ask first: what already runs there (sites, Docker, a panel such as cPanel/Plesk), the SSH port, and any existing firewall. Then run the **pre-flight** (it changes nothing without confirmation):

```bash
ssh -p <port> root@<ip> "DEPLOY_USER=<user> SSH_PUBLIC_KEY='$(cat <pub>)' SSH_PORT=<port> PRIVATE_RANGE=<range> REBOOT_TIME=<hh:mm> bash -s" < "${CLAUDE_PLUGIN_ROOT}/templates/bootstrap.sh"
```

It lists listening ports, containers, firewall and control panel, and exits 3 when something unexpected runs. **Show that output to the user and ask** before re-running with `GOLIVE_CONFIRM=1` (it overwrites `daemon.json`, restarts Docker and enables ufw). Without a provider firewall also install `firewall_rules.py --format docker-user` as a oneshot systemd unit.

## 7. Verify

Use `ssh -i <key> -o IdentitiesOnly=yes -p <port> …` everywhere (without `IdentitiesOnly` an agent offering several keys gets the IP banned by fail2ban).

1. `cloud-init status --wait` (retry every 20 s; SSH takes about a minute).
2. `docker version --format {{.Server.Version}} && sudo ufw status && sudo fail2ban-client status sshd`.
3. `sudo sshd -T | grep -Ei '^(passwordauthentication|permitrootlogin|port)'`; root login must be refused.
4. `sudo mkdir -p /var/lib/node_exporter/textfile` (node_exporter textfile collector; the pull and backup units write heartbeats there).

## 8. Reverse DNS

`hcloud server set-rdns <name> --ip <ipv4> --hostname <host>` and again for the `::1` address (other providers: providers.md). Use the app host; for a self-hosted mail server it must match the mail hostname. Record `servers.<name>.rdns`.

Set `steps.server.envs.<env>: done` (name, type, location, IPs in the note).

## Things to know

- Outgoing ports 25/465 are blocked on new Hetzner accounts (other providers: providers.md); send mail by API or 587.
- Server backups (`hcloud server enable-backup`) cost 20% of the server price; `ops` decides.
- Bind databases and internal services to the compose network or private IP only.
