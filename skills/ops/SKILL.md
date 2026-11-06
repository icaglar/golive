---
name: ops
description: Puts the production basics in place after deploy - backups (deferring to the database step, or a simple dump with heartbeat), secrets escrow, an infra/rebuild.md generated from the state file with a rebuild drill, host lifecycle checks (reboot window, swap, memory limits, image prune), uptime monitoring and error tracking. Use for the ops go-live step, or when the user says "yedekleme kur", "backup", "uptime izleme", "Sentry ekle", "yeniden kurulum", "rebuild", "secrets yedeği", "prod hazırlığı".
---

# Production basics

Talk to the user in the language they use. Ask which items they want; items 1-3 are required to mark the step done. Deploys are not part of this skill: releases go through `workflows` and `release`.

## 1. Backups (required)

- **Database step done** (`steps.database`): backups are pgBackRest (encrypted, `templates/backup/`) or the operator's own, with the offsite copy and restore drill recorded there. Verify only: `database.backups` is set, the heartbeat `golive_backup_last_success_timestamp_seconds` in `/var/lib/node_exporter/textfile/backup.prom` is fresh, and the drill date is in the note. Do not add a second dump job.
- **No database step** (SQLite, managed DB, or skipped): a nightly dump on the server, written by a small script that appends the heartbeat on success: dump to `/srv/backups/db-$(date +%F).dump` (`pg_dump -Fc`, `mysqldump --single-transaction`, or a file copy), keep 14 days, then write `golive_backup_last_success_timestamp_seconds <unix time>` to `/var/lib/node_exporter/textfile/backup.prom`. Copy offsite with `restic` (below). A restore into a throwaway container with a row count is required: a backup never restored is not a backup.
- **Uploads, volumes and `.env` files**: `restic` offsite using `templates/backup/restic.env.example` (S3-compatible bucket or SFTP at a provider other than the server's). The restic password lives in the user's password manager and a root-only file on the server, never in the repo. Buckets cost money: confirm first, append a `costs:` entry. Expect a guard prompt on `restic forget --prune`.
- Provider snapshots are optional extras, not instead of backups.

## 2. Secrets escrow (required)

Generated secrets exist only on servers. Per server, copy `/srv/app/.env` (and `/srv/monitoring/.env`, `/etc/alertmanager/secrets/*`) into the user's password manager (the user does it: secure notes, one per server), or into the encrypted restic repository above. Never into the repo, the state file or this chat. Record only the locations in `secrets:`. Rotate any key that was ever pasted into a chat or committed.

## 3. Rebuild document and drill (required)

Generate `infra/rebuild.md` in the app repo from `.claude/golive.yaml` (names and locations only, no secrets):

- Provider, region, image; each server in `servers:` with type, location, firewall, private network and range.
- Cloud-init / bootstrap parameters (`__DEPLOY_USER__`, `__SSH_PORT__`, `__PRIVATE_RANGE__`, `__REBOOT_TIME__`).
- DNS records (provider, names, proxied or not), Cloudflare Access apps if any, mail records.
- Where each secret lives (password manager entry, restic repo), registrar and DNS accounts.
- **Restore order**: network and firewall, servers, DB restore from backup, `.env` files from escrow, Caddy and compose, pull unit, then run `release` for the current prod sha, DNS last.

**Rebuild drill**: on a throwaway server (small, deleted afterwards; show the price, the guard asks) follow the document: restore the DB, bring the app up, check it answers. Record date and minutes in the step note: that is the real RTO. Fix the document where it was wrong.

## 4. Host lifecycle (verify)

- Reboot window and swap come from cloud-init/bootstrap: `ssh ... 'grep -r Automatic-Reboot /etc/apt/apt.conf.d/; swapon --show'`. The `RebootRequired` alert (monitoring) covers pending reboots.
- Container memory limits live in `compose.<env>.yaml` (`deploy.resources.limits.memory` or `mem_limit`); a Postgres container must not be the OOM victim on a small server.
- Old images are pruned by the pull unit (`docker image prune -f`); check `docker system df` once.
- Compose services: `restart: unless-stopped`, a `healthcheck`, data on named volumes.

## 5. Uptime and error tracking

- **Uptime**: if `monitoring` is in scope its blackbox checks cover this; otherwise monitor from outside the servers (a hosted free tier, or Uptime Kuma on a different provider). Check `https://<domain>` and a health endpoint every minute, alert by e-mail or chat.
- **Error tracking**: Sentry (hosted; pick the region matching `profile.data_residency`) or GlitchTip (self-hosted, Sentry SDK compatible). Add the SDK, `SENTRY_DSN` in the server `.env`.

Set `steps.ops: done` when items 1-3 exist; list the optional items in the note.
