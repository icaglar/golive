#!/usr/bin/env bash
# golive: compare live Cloudflare ranges with the saved baseline; write a node_exporter textfile metric.
#   golive_cloudflare_ranges_changed 1   ranges differ from the baseline (alert CloudflareRangesChanged fires)
#   golive_cloudflare_ranges_changed 0   same as baseline
# The baseline /var/lib/golive/cf-ranges.txt is created on the first run (assumed to match what is applied now).
# To ACCEPT a change after applying it (see "Apply" below): run `golive-cf-ranges.sh --accept`.
#
# Apply (manual, after reviewing the diff in /var/lib/golive/cf-ranges.diff):
#   Hetzner Cloud Firewall: python3 /opt/golive/firewall_rules.py --ssh-from <your-ip>/32 > rules.json &&
#                           hcloud firewall replace-rules golive-web --rules-file rules.json
#   No cloud firewall:      python3 /opt/golive/firewall_rules.py --format docker-user > /usr/local/sbin/golive-docker-user.sh &&
#                           bash /usr/local/sbin/golive-docker-user.sh
#   Caddy trusted_proxies:  python3 /opt/golive/firewall_rules.py --format json-ranges  (update the Caddyfile list, then reload Caddy)
set -euo pipefail
STATE=/var/lib/golive
PROM=/var/lib/node_exporter/textfile/cloudflare.prom
SCRIPT=/opt/golive/firewall_rules.py
mkdir -p "$STATE" "$(dirname "$PROM")"

write_metric() {
  printf '# HELP golive_cloudflare_ranges_changed 1 when Cloudflare published IP ranges differ from the applied baseline\n# TYPE golive_cloudflare_ranges_changed gauge\ngolive_cloudflare_ranges_changed %s\n' "$1" > "$PROM.tmp"
  mv "$PROM.tmp" "$PROM"
}

fetch() {
  { curl -fsS --max-time 15 https://www.cloudflare.com/ips-v4; echo; curl -fsS --max-time 15 https://www.cloudflare.com/ips-v6; } | awk 'NF' | sort
}

if [ "${1:-}" = "--accept" ]; then
  fetch > "$STATE/cf-ranges.txt"; write_metric 0; echo "baseline updated"; exit 0
fi

NEW="$(fetch)"
[ -n "$NEW" ] || { echo "could not fetch Cloudflare ranges; leaving the metric unchanged" >&2; exit 1; }
if [ ! -s "$STATE/cf-ranges.txt" ]; then
  echo "$NEW" > "$STATE/cf-ranges.txt"; write_metric 0; exit 0
fi
if diff -u "$STATE/cf-ranges.txt" <(echo "$NEW") > "$STATE/cf-ranges.diff"; then
  write_metric 0
else
  write_metric 1
  echo "Cloudflare ranges changed; see $STATE/cf-ranges.diff" >&2
fi
