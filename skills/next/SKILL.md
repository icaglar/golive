---
name: next
description: Runs the next pending go-live step from .claude/golive.yaml (domain, nameservers, environments, server or cluster, database, deploy, TLS, migration, DNS cutover, CI/CD, mail, app config, ops, monitoring, legal, launch, audit), one step at a time, using the matching golive skill and updating the state file. Use when the user says "devam", "sıradaki adım", "golive devam", "next step", or asks to continue the go-live.
---

# Run the next go-live step

Talk to the user in the language they use.

1. Read `.claude/golive.yaml`. If it does not exist, run the `init` skill instead.
2. Pick a step in this order, skipping `done` and `skipped`. The order is the one `scripts/status.py` shows; keep them identical.

   **Default (DNS on Cloudflare, compose):**
   domain → nameservers → environments → server → database → deploy → tls → [migrate] → dns_records → ci_cd → mail_send → mail_inbound → app_config → ops → monitoring → legal → launch → audit.

   **No Cloudflare** (`domain.dns_provider` is not `cloudflare`): `dns_records` runs before `tls` (Let's Encrypt needs the records to point at the server): … deploy → [migrate] → dns_records → tls → ci_cd …

   **k8s runtimes** (`hetzner-k3s`, `kube-hetzner`, `managed-k8s`, `k3sup`): … environments → cluster → database → ci_cd → tls → [migrate] → dns_records …; `server` and `deploy` are `skipped`; `dns_records` runs only after `kubectl rollout status` is green. Images must exist first, which is why `ci_cd` comes before the cutover.

   **migrate** runs only when `profile.replaces_live_app` is true, always right before `dns_records`; otherwise it is `skipped`. `cluster` is `skipped` on compose.

   | Step | Skill | Needs done (or skipped) first |
   |---|---|---|
   | domain | domain | – |
   | nameservers | dns | domain |
   | environments | environments | – |
   | server | server (per environment) | environments |
   | cluster | cluster (k8s only) | environments |
   | database | database | server, or cluster |
   | deploy | deploy (per environment) | server, database |
   | ci_cd | workflows | deploy; on k8s: database |
   | tls | tls | Cloudflare: deploy (compose) or ci_cd (k8s), nameservers; no Cloudflare: dns_records (compose) |
   | migrate | migrate | the app runs on the new infra (deploy or ci_cd), database, tls (Cloudflare) |
   | dns_records | dns (prod and staging hosts) | Cloudflare: tls, migrate; no Cloudflare: deploy, migrate; k8s: ci_cd and a green rollout |
   | mail_send | mail | nameservers |
   | mail_inbound | mail | nameservers |
   | app_config | mail (section C) | deploy or cluster, mail_send |
   | ops | ops | deploy or cluster |
   | monitoring | monitoring | deploy or cluster |
   | legal | legal | – |
   | launch | launch | everything above done, skipped, or blocked with `owner: user` |
   | audit | audit | every other step done, skipped, or blocked with `owner: user` |

   - A step that is `blocked` with `owner: user` is waiting for the user (a `.com.tr` registration, a registrar top-up, a verification click, a lawyer's review). Do not re-pick it; mention it in one line ("still waiting for you: …") and move on to the next runnable step. Pick it only when the user says that part is done.
   - If nothing is runnable because of prerequisites, say which step blocks what. `server`, `deploy` and `legal` can run while the domain work waits.
   - The web cutover is deliberately late: `dns_records` points the domain at the new infrastructure only after the app runs there, so an existing live site has no downtime.
   - **Per-environment steps** (`server`, `deploy`, `tls`, `dns_records`): run staging first, then prod (staging is absent when `environments.layout` is `prod-only`). Record each under `steps.<step>.envs` (`staging: done`, `prod: pending`); the step is `done` only when every environment is `done` or `skipped`. One invocation does one environment.
3. **Before doing anything**, tell the user in 2-4 lines what the step will do, what it costs (if anything), and which parts are theirs. Ask for a go-ahead when the step costs money or changes live DNS; otherwise proceed.
4. Load and follow the matching skill. Set the step to `in_progress` while working.
5. Update the step: `done` with a one-line note of what now exists (IDs, IPs, record names, never secrets), or `blocked` with `owner: user` and exactly what the user must do. After any billable step (server, volume, load balancer, object storage, paid plan) append an entry to `costs:` (`{item, monthly, currency, step}`, a number from the provider's price list; never invent one, ask or say "check the provider docs"). Update `updated:`.
6. Close with the **status board** (the `status` skill: run `status.py`, show it unchanged in a code block, point to `.claude/golive-status.html`; it includes the running cost line), then one line: what was done and what `/golive:next` will do next. Every step ends with the board. Run only one step per invocation unless the user asked to continue through several.
