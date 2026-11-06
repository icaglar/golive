---
name: database
description: Sets up the app's database per environment - PostgreSQL (recommended) or MySQL - as a container for staging, on a dedicated server with a volume, private network and streaming replica for prod, encrypted backups with an offsite copy, or with an operator (CloudNativePG, MySQL/Percona operator) on k3s - plus point-in-time backups to object storage, a tested restore, migrations and manual failover. Use for the database go-live step, or when the user says "veritabanı kur", "PostgreSQL kur", "MySQL kur", "replica", "DB cluster", "yedekli veritabanı", "failover".
---

# Database

Talk to the user in the language they use. Read `runtime` and `environments` from `.claude/golive.yaml`. Anything that creates servers, volumes or buckets is billed: show what and ask first (the guard also asks). Passwords are generated where they are used (`openssl rand -hex 24` inside the command) and never printed.

## 1. Ask

One `AskUserQuestion` form, best guess first:

1. **Engine**: what the app already uses (driver in the code, `DATABASE_URL` scheme); otherwise PostgreSQL (recommended) / MySQL 8.4.
2. **Prod layout**:
   - Compose: **dedicated DB server + streaming replica** (recommended once prod matters) / dedicated DB server only / DB container on the app server (only for a small, non-critical prod).
   - k3s: **operator cluster in the cluster** (recommended: CloudNativePG for Postgres; Percona or Oracle MySQL operator for MySQL) / dedicated DB server outside the cluster.
3. **Staging**: its own small DB container next to the app (recommended) / same layout as prod, smaller.
4. **Backups**: point-in-time to S3-compatible object storage (recommended for prod; provider and region follow `profile.data_residency`), encrypted, plus an offsite copy at a second provider / nightly dumps only.

Record the answers under `database:` in the state file (engine, version, per-environment layout, hosts as private IPs or service names, backup target, where the passwords live).

## 2. Compose: staging (container)

Staging's database is the `db` service in `compose.staging.yaml` (copied by the deploy skill; `postgres:16-alpine`, named volume, healthcheck, no `ports:`). The deploy skill already generated `POSTGRES_PASSWORD` and `DATABASE_URL` in the server's `.env`; do not write `.env` here. For MySQL swap the image (`mysql:8.4`), healthcheck (`mysqladmin ping`) and data path in that override. Add the `migrate` service's `depends_on: db` if the app has one.

## 3. Compose: prod on a dedicated server

Costs: every DB server, volume and bucket is appended to `costs:` (`step: database`) with the monthly price shown to the user.

1. **Private network** (free). Create a private network/VPC in the DB server's location and attach the app server and each DB server; record each `private_ip`. Hetzner example: `hcloud network create --name golive-net --ip-range <server_defaults.private_range>`, `hcloud network add-subnet golive-net --network-zone eu-central --type cloud --ip-range 10.0.0.0/24`, `hcloud server attach-to-network <server> --network golive-net`. Other providers: `${CLAUDE_PLUGIN_ROOT}/skills/server/providers.md` (private network row), else WireGuard. The database listens only on its private IP; the cloud firewall of DB servers opens only SSH from `server_defaults.ssh_from`.
2. **DB servers** with the `server` skill (`db-1` primary, `db-2` replica; role `db-primary` / `db-replica`, env prod; memory-heavy or dedicated-vCPU types; no 80/443). The cloud-init (and bootstrap.sh on existing servers) already opens 5432/3306 from the private range with ufw. If a server is configured otherwise: `sudo ufw allow from <private_range> to any port 5432 proto tcp`. Data on a **volume** (create per providers.md; Hetzner: `hcloud volume create --size <GB> --server db-1 --automount --format ext4`) so it can grow and outlives a rebuild; point the data directory at it.
3. **PostgreSQL** from the PGDG apt repository. `listen_addresses = '<private ip>'`, `shared_buffers` about 25% of RAM, `effective_cache_size` about 70%, `wal_level = replica`, `max_wal_senders = 10`, plus the archiving settings of step 5. `pg_hba.conf`: the app user from the app server's private IP, `replication` from the replica's IP, `scram-sha-256` only.
4. **Replica**: `replicator` role with `REPLICATION LOGIN` (password generated on the primary, handed to the replica over SSH without printing); on `db-2`: `pg_basebackup -h <primary ip> -U replicator -D <data dir> -R -X stream -C -S db2`. Check `SELECT client_addr, state, replay_lag FROM pg_stat_replication;` on the primary.
5. **MySQL 8.4 variant**: `gtid_mode=ON`, `enforce_gtid_consistency=ON`, `bind_address=<private ip>`, unique `server_id`; seed the replica (clone plugin or dump), then `CHANGE REPLICATION SOURCE TO SOURCE_HOST='<primary ip>', SOURCE_USER='repl', SOURCE_PASSWORD=…, SOURCE_AUTO_POSITION=1; START REPLICA;` and check `SHOW REPLICA STATUS`. Backups: step 5 MySQL line.
6. **App connection**: on the prod app server, write `POSTGRES_PASSWORD`/`DATABASE_URL` into `/srv/app/.env` pointing at the primary's private IP (password generated on the DB server and passed over SSH without printing; build the URL in the same command). Then restart the stack. A read-only connection to the replica only if the app is written for it.

## 4. k3s: operator

- **PostgreSQL / CloudNativePG**: `helm repo add cnpg https://cloudnative-pg.github.io/charts && helm upgrade --install cnpg cnpg/cloudnative-pg -n cnpg-system --create-namespace`. A `Cluster` per namespace: `instances: 1` in staging, `instances: 3` in prod (one primary, two streaming replicas, automatic failover), storage on the provider's CSI storage class, sized from the user's answer. The operator creates the app secret (`<cluster>-app`) and services `<cluster>-rw` (primary) and `<cluster>-ro` (replicas); the app reads `DATABASE_URL` from that secret. Backups: CNPG's object-store backups (Barman Cloud) to an encrypted bucket plus a `ScheduledBackup`, and the second-provider copy where possible; follow the CNPG docs for the installed version, the backup configuration changed across releases.
- **MySQL**: Percona Operator for MySQL or Oracle's MySQL Operator (InnoDB Cluster, 3 instances in prod), installed with its Helm chart; follow its docs for the installed version.
- Add the manifests to `deploy/k8s/overlays/<env>` so Flux owns them.

## 5. Backups and restore (prod)

Templates are in `${CLAUDE_PLUGIN_ROOT}/templates/backup/`; read their header comments. Choose the bucket's provider and region from `profile.data_residency`; buckets are billable (append to `costs:`). A bucket creation prompts for confirmation.

- **PostgreSQL, point-in-time and encrypted**: install pgBackRest on the DB server and render `pgbackrest.conf` to `/etc/pgbackrest/pgbackrest.conf` (0640 root:postgres). Generate the cipher passphrase **on the server** (`openssl rand -base64 32`, substituted into the file in the same command, never printed); the owner escrows it in their password manager (without it backups cannot be restored: ask them to confirm). Set `archive_mode=on` and the `archive_command` from the template, `stanza-create`, `check`. Enable bucket Object Lock where the provider supports it (check the provider docs).
- **Offsite copy at a second provider** (recommended; `database.offsite`): uncomment the `repo2-*` block with another provider/account and its own cipher pass, so one suspended or compromised account does not take every copy.
- **Heartbeat**: install `golive-backup.sh` to `/usr/local/sbin/`, `golive-backup.service` and `.timer` to `/etc/systemd/system/`, enable the timer (02:30). It writes `golive_backup_last_success_timestamp_seconds` for the `BackupTooOld` alert, so `/var/lib/node_exporter/textfile` must exist.
- **MySQL**: pgBackRest is Postgres-only. Set `BACKUP_CMD` in the service to Percona XtraBackup / `mariadb-backup`, or `mysqldump --single-transaction --routines --events | restic backup --stdin`; the same script writes the heartbeat.
- **Uploads, volumes and the servers' `.env`** (they hold every generated secret): restic with `restic.env.example` copied to `/etc/golive/restic.env` on each server that has such data (app servers too), a repository at another provider/account, repository password generated on the server and escrowed by the owner; add `Environment=RESTIC_ENV_FILE=/etc/golive/restic.env` to the backup unit. Never back up the `.env` anywhere unencrypted.
- **Restore drill before launch**: restore the latest backup to a throwaway server or namespace, run the app's migrations against it, count rows on a main table. Record the date and duration in `database.restore_drill` and the step note: that is your real recovery time.

## 6. Migrations

They run once per release, **before** the new app version takes traffic: the pull unit runs `docker compose run --rm migrate` when the compose file has a `migrate` service; on k8s a `migrate` Job (templates/k8s/migrate) that Flux applies before the app. Destructive changes go in two releases (expand, then contract) so a rollback keeps working. Take a backup or snapshot right before a migration that drops or rewrites data.

## 7. Failover (manual, documented)

Write `docs/runbook-db.md` with the exact steps: stop writes, promote the replica (`SELECT pg_promote();` on Postgres; `STOP REPLICA; RESET REPLICA ALL;` and turn off read-only on MySQL), point `DATABASE_URL` at it, restart the app, rebuild the old primary as the new replica. On k3s CloudNativePG fails over automatically; the runbook covers checking it. Promotion is guarded: the hook asks before it.

## 8. Staging data

Never copy prod data into staging as is. Use seed scripts, or a dump passed through an anonymization step agreed with the user (data protection law: GDPR, KVKK, ...).

Set `steps.database: done` with engine, layout per environment, replica state, backup target and the restore drill result.
