---
name: migrate
description: Moves an existing live app onto the new infrastructure without losing data or search ranking - inventories the old system (data stores, uploads, URLs, mail senders, cron jobs), lowers DNS TTLs ahead, plans a freeze window, imports the data, syncs uploads, builds a 301 redirect map, rehearses on staging and keeps a rollback path, then hands over to the dns_records cutover. Use for the migrate go-live step (shown as "Migration" on the board) when profile.replaces_live_app is true, or when the user says "eski siteyi taşıyalım", "mevcut uygulamanın yerine geçecek", "migrate the old app", "veri taşıma", "301 yönlendirme".
---

# Migrate a live app

Talk to the user in the language they use. Read `.claude/golive.yaml`. If `profile.replaces_live_app` is not true, set `steps.migrate: skipped` with note "not replacing a live app" and stop.

The old system keeps serving until the cutover is confirmed, and stays up afterwards until the user says the new one is fine. Nothing here touches live DNS; the `dns` skill does the cutover as `dns_records`.

## 1. Inventory the old system

Ask for access (SSH, a panel, a dump) and write `docs/migration-inventory.md`:

- **Data stores**: databases (engine, version, size), caches that matter, search indexes, object storage buckets.
- **Uploads and files**: where they live, total size, how they are referenced (paths or URLs in the database).
- **URLs**: every public URL pattern that has traffic (sitemap, analytics top pages, backlinks the user knows), including old domains.
- **Mail**: every service that sends mail as this domain today (the old app, a newsletter tool, a CRM, a helpdesk). They are merged into the SPF record by the `mail` skill; collect their include values now. Existing mailboxes and MX stay untouched.
- **Cron jobs and workers** on the old host and what each does; move them to the new system or retire them on purpose.
- **Integrations with fixed IPs or callbacks** (payment webhooks, partners that allowlist the old IP, OAuth redirect URIs).

## 2. Plan the timeline

- When DNS is **not** on Cloudflare: lower the TTL of the records that will change (A/AAAA/CNAME for the apex, `www`) to 300 s at least 24-48 hours before the cutover, so the old TTL has expired by then. Note the original TTLs to restore them afterwards. On Cloudflare proxied records this is not needed.
- A **freeze window**: when the old app becomes read-only or offline for writes, how long the final import takes (measured in the rehearsal), who announces it. Pick a low-traffic hour.
- Write the plan, with times, into `docs/migration-plan.md`.

## 3. Import and sync

- **Database**: dump from the old store, import into the new database (`database` skill's engine; a logical dump for a small database, replication or a staged copy for a large one). Convert encodings, collations and schema differences deliberately; run the app's migrations after the import. Verify with row counts and a few spot checks, not "no error".
- **Uploads**: `rsync -a` (or the object-storage sync tool) from the old host to the new volume or bucket; repeat after the freeze for the delta. Check the path references in the database.
- Large copies cost bandwidth and time: say so before starting. Never print credentials; use environment variables or the user's SSH agent.

## 4. 301 redirect map

Build `docs/redirects.csv` (old path → new path) from the inventory and the old sitemap. Every old URL that changes gets a permanent redirect; unchanged URLs need nothing. Implement it in the Caddyfile (`redir` / a `@old path` matcher with `redir ... permanent`) on compose, or ingress annotations / a redirect middleware on k8s. Validate (`caddy validate`) before reload, and test with `curl -I` for the top 20 URLs. Old domains redirect to the new canonical host (`profile.app_shape.canonical_host`).

## 5. Rehearsal on staging

Run the whole sequence once on staging with a copy of the old data: dump, import, uploads sync, redirect tests, login and a core user flow, mail test. Time every phase and fix the plan. Get the user's sign-off on the result before the real run.

## 6. Rollback plan

- The old system stays running and unchanged (no data deletion, no decommission) until the user confirms the new one after a stable period (suggest at least a week).
- Rollback = point DNS back (the old records and TTLs are written down in the plan); data written on the new system after the cutover is exported first if the user wants to keep it.
- Decommissioning the old system is a separate, later, confirmed action.

## 7. Hand over

When the rehearsal passed and the final import is ready (or done at the freeze), set `steps.migrate: done` with a note (what moved, sizes, redirect count, rollback owner). Tell the user the `dns_records` step is next and is the real cutover; restore the original TTLs a few days after it. End with the status board.
