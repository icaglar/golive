---
name: launch
description: Pre-launch readiness review before real users arrive - checks every go-live step, then the items people forget (rebuild drill, restore drill, migrations in the release flow, rollback tested, zero-downtime deploys, health checks, alerts that reach someone, WAF and rate limits, load test, dependency updates, status page, runbooks, costs, legal pages) - and writes a launch checklist with owners. Use for the launch go-live step, or when the user says "canlıya hazır mıyız", "launch checklist", "yayın öncesi kontrol", "canlı için eksik ne".
---

# Launch readiness

Talk to the user in the language they use. Read `.claude/golive.yaml`; check what you can yourself, ask about the rest. Output: `docs/launch-checklist.md` in the repo, each item ✅ / ❌ / n/a with a one-line note and an owner (`claude` or `user`), and the step note in the state file.

## Must have before launch

| Area | Check |
|---|---|
| Steps | Every golive step `done` or `skipped` with a reason; nothing `blocked` except the lawyer's review if the user accepts that. |
| Data | Prod backups run, are **encrypted**, and a second **offsite copy** exists at another provider (`database.offsite`); a **restore drill** was done and timed (`database` skill). |
| Rebuild | A **rebuild drill**: one server (staging, or a throwaway) was rebuilt from the `servers:` entries in the state file and `infra/rebuild.md` (written by the `ops` skill), including restoring its `.env` from the escrow. Time it and fix the doc where it was wrong. |
| Migrations | Run in the release flow before the new version takes traffic; the last one was tested on staging. |
| Rollback | A rollback to the previous release was tried once on staging (`release` skill). |
| Health | `/health` (or similar) endpoint checks the DB; compose `healthcheck` / k8s readiness and liveness probes use it. |
| Zero downtime | k8s: rolling update with ≥2 replicas. Compose: say plainly that `up -d` restarts the container (a few seconds); if that matters, run two app containers behind Caddy and restart them one by one, or move to k3s. |
| Alerts | Prometheus/Alertmanager (monitoring skill) or the uptime monitor, plus error tracking, alert a channel the user actually reads (Telegram, e-mail); a test alert arrived; Grafana dashboards show every server. |
| Dead-man's switch | The monitor's own heartbeat (the `Watchdog` alert to the external heartbeat service, `monitoring.deadman`) was **tested**: stop Alertmanager or the heartbeat for a few minutes and confirm the external service alarms through a different channel. |
| CI | **Branch protection on `main`** with the `ci` check required (`templates/github/branch-protection.md`; check with `gh api repos/{owner}/{repo}/branches/main/protection`; plan limits per `profile.github.plan`). Prod changes only through `/golive:release`. |
| Host lifecycle | **Reboot window** set (unattended upgrades with the reboot time from cloud-init) and the RebootRequired alert works. |
| Secrets | None in git history (`git log -p` scan for keys or a tool like gitleaks if installed); server `.env` files are 600; any key that ever passed through a chat is rotated. |
| Edge | With Cloudflare: WAF managed rules on, a rate-limiting rule for login/auth and API endpoints, Bot Fight Mode considered, caching for static assets (through the Cloudflare MCP after the user agrees). Without it: the host's firewall plus rate limiting in the proxy, and the DNS provider's protection if it has any. |
| Mail | SPF, DKIM, DMARC pass on a real message; bounce and complaint handling in the app (the mail provider's webhooks) if it sends a lot. |
| Legal | Privacy notice, cookie policy and consent banner live for the users' jurisdictions; legal checklist reviewed by a lawyer. |
| Audit | `audit.py` has no FAIL on the prod domain; staging hosts are checked with `--host-only`; use `--no-send-subdomain` when the mail provider has no sending subdomain (see the `audit` skill). |
| Migration | If `profile.replaces_live_app`: the `migrate` step is done, the 301 map was tested, and the old system is kept running for rollback. |

## Should have

- **Load test** on staging with realistic traffic (k6 or similar): find the first bottleneck, decide the server size or replica count from it.
- **Dependency updates**: Dependabot or Renovate config for the app and the base images.
- **Status page** (hosted, or Uptime Kuma's) and where users report problems.
- **Runbooks** in `docs/`: deploy and rollback, DB failover (`docs/runbook-db.md`), restoring from backup, rotating a leaked key, what to do when the site is down.
- **Costs**: a monthly total of servers, volumes, load balancers, object storage, domain and paid services, compared with the `costs:` total on the status board, so there are no surprises.
- **Access**: who has access to the cloud provider, DNS provider, GitHub, the registrar and the mail provider (`profile.accounts`); two-factor auth on all of them; a second person or a sealed recovery path for the critical accounts.

## Report

Show the table with ✅/❌, the three most important gaps first, and offer to fix the ones Claude can do. Set `steps.launch: done` only when every must-have item is ✅ or consciously accepted by the user (note which).
