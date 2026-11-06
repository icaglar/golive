---
name: monitoring
description: Sets up metrics, dashboards and alerts with Prometheus, Grafana and Alertmanager - on a small separate monitoring server for Docker Compose setups, kube-prometheus-stack in k8s, or Grafana Cloud's free tier - with exporters, blackbox checks, alert rules (site down, disk, memory, DB, backup too old, reboot required, pull failed), a dead-man's switch to an external heartbeat service and an escalation receiver. Use for the monitoring go-live step, or when the user says "Grafana kur", "Prometheus", "izleme", "metrik", "dashboard", "alarm kur", "log toplama".
---

# Monitoring: Prometheus, Grafana, Alertmanager

Talk to the user in the language they use. Read `runtime`, `environments`, `servers`, `database` and `profile.budget` from `.claude/golive.yaml`. Templates: `${CLAUDE_PLUGIN_ROOT}/templates/monitoring/`. A new server or volume costs money: show the price, ask first (the guard asks too), then append a `costs:` entry (`mon-1`, or Grafana Cloud with 0 and a note on the free tier limits; check the provider docs).

## 1. Ask

One `AskUserQuestion` form, best guess first:

1. **Where**: compose: **separate small `mon-1`** (recommended, keeps alerting when an app server dies; `budget: minimal` may prefer Grafana Cloud) / Grafana Cloud free tier with Grafana Alloy / on the prod app server (cheapest, dies with what it watches). k8s: **kube-prometheus-stack** / Grafana Cloud.
2. **Alerts to**: Telegram (bot token and chat id from the user) / e-mail via the mail provider's SMTP (587) / both. **Escalation**: a second chat id or address (second admin) for critical alerts.
3. **Dead-man's switch**: an external heartbeat service (any cron/heartbeat monitoring provider; check its docs): the user creates a check and keeps its ping URL.
4. **Logs too?** No for now / Loki with Grafana Alloy (7-14 days).
5. **App metrics?** Add `/metrics` (FastAPI: `prometheus-fastapi-instrumentator`; Node: `prom-client`) / not now.

Record under `monitoring:` (`monitoring.deadman` = where the URL lives, never the URL).

## 2. Compose: monitoring server

1. **Server `mon-1`** (`role: monitoring, env: shared` in `servers:`) with the `server` skill and `skills/server/providers.md` for the provider's CLI: small shared type, same cloud-init/bootstrap, on the private network (`server_defaults.private_network`; create it via the `server`/`database` skill if missing). Firewall: SSH from `ssh_from`; 80/443 as the Grafana exposure below needs.
2. **Exporters on every server in `servers:`** (app, db): render `compose.exporters.yaml` with that server's `private_ip` (`__PRIVATE_IP__`) to `/srv/monitoring/compose.yaml`, `docker compose up -d`. node-exporter binds the private IP only; cAdvisor on app servers; `postgres_exporter`/`mysqld_exporter` on DB servers with a read-only role (`pg_monitor`) whose password is generated on the server. `/var/lib/node_exporter/textfile` must exist (the `server` skill creates it in its verify step; create it if missing).
3. **Textfile scripts**: install `templates/monitoring/textfile/reboot-required.sh` as `/usr/local/sbin/golive-reboot-required.sh` (0755) and `golive-textfile.{service,timer}` to `/etc/systemd/system/`, enable the timer. Together with the pull unit, backup script and `templates/firewall/golive-cf-ranges.*` (Cloudflare setups) they feed `RebootRequired`, `PullFailed`, `BackupTooOld` and `CloudflareRangesChanged`.
4. **Caddy metrics** on app servers: the metrics site on `<private ip>:9180` is in the Caddyfile templates; publish it via `compose.caddy.yaml` (`__PRIVATE_IP__`). Never expose Caddy's admin port.
5. **Stack on mon-1** in `/srv/monitoring`: `compose.monitoring.yaml` (pin images to current release tags), `prometheus.yml` (private IPs per server and env; drop jobs that do not apply), `alerts.yml`, `alertmanager.yml` (chat ids or e-mail).
6. **Secrets on mon-1 only**: `GF_SECURITY_ADMIN_PASSWORD=$(openssl rand -hex 16)` into `/srv/monitoring/.env` (600). The user writes the Telegram bot token to `/srv/monitoring/secrets/telegram_bot_token` and the heartbeat ping URL to `/etc/alertmanager/secrets/deadman_url` (mounted from `secrets/`), both 600, themselves. Tell the user where the Grafana password is instead of printing it. The Watchdog alert is pushed through the `deadman` receiver every minute; if the heartbeat service stops hearing it, it notifies the user out-of-band.
7. **Grafana provisioning**: Prometheus datasource at `http://prometheus:9090`; dashboards from grafana.com: Node Exporter Full (1860), PostgreSQL (9628) or MySQL, cAdvisor, Caddy.
8. **Grafana exposure** (by `domain.dns_provider`):
   - **Cloudflare**: `grafana.<domain>` proxied to mon-1 with the origin certificate; the Cloudflare Access app is created in the `dns` step (add `grafana` there if missing).
   - **No Cloudflare**: Caddy on mon-1 with Let's Encrypt and basic auth (`caddy hash-password`), or keep Grafana private (bind to the private IP) and reach it with `ssh -L 3000:localhost:3000`, which is the safest.
9. **Test**: all Prometheus targets `UP` (`curl -s localhost:9090/api/v1/targets`); send a test alert (`amtool alert add`) and confirm it reaches Telegram/e-mail and the escalation channel; confirm the heartbeat service shows the Watchdog ping.

## 3. k8s: kube-prometheus-stack

`helm upgrade --install` of `kube-prometheus-stack` in `monitoring` (a guard prompt is expected) with persistent volumes on the cluster's storage class and 15-30 days retention. CNPG PodMonitor, a `ServiceMonitor` for the app, `alerts.yml` as a `PrometheusRule`, Alertmanager with the same receivers (secrets created without printing). Grafana through the ingress: Cloudflare = Origin cert + Access app; otherwise cert-manager `letsencrypt-prod` plus basic auth, or `kubectl port-forward`. Manifests in `deploy/k8s/monitoring/` so Flux owns them.

## 4. Grafana Cloud

The user creates the stack (user step); install Grafana Alloy per server (or the k8s-monitoring chart) with credentials in a root-only file; import the same dashboards and alerts. No monitoring server, no Grafana exposure to solve. Still set up the dead-man's switch and escalation in whatever Alertmanager or Grafana alerting is used.

## 5. Logs (optional)

Loki on mon-1 (or the Helm chart) with Grafana Alloy per server; 7-14 days. Caddy access logs stay off or short-lived. Personal data in logs falls under data protection law: short retention, no request bodies.

Set `steps.monitoring: done` with where it runs, alert channels, the dead-man's switch and the date of the last test alert. The `launch` skill checks that a test alert arrived.
