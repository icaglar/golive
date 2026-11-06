#!/usr/bin/env bash
# golive: write node_reboot_required (1/0) for node_exporter's textfile collector.
# Install: /usr/local/sbin/golive-reboot-required.sh (0755) + golive-textfile.service/.timer in /etc/systemd/system/.
set -euo pipefail
DIR=/var/lib/node_exporter/textfile
mkdir -p "$DIR"
val=0
[ -f /var/run/reboot-required ] && val=1
printf '# HELP node_reboot_required 1 when the OS says a reboot is pending\n# TYPE node_reboot_required gauge\nnode_reboot_required %s\n' "$val" > "$DIR/reboot.prom.tmp"
mv "$DIR/reboot.prom.tmp" "$DIR/reboot.prom"
