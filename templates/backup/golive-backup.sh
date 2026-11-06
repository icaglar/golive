#!/usr/bin/env bash
# golive: run the backup and, only on success, write the heartbeat node_exporter exports as
#   golive_backup_last_success_timestamp_seconds   (alert BackupTooOld fires when it is older than 26 h)
# Install to /usr/local/sbin/golive-backup.sh (0755), run as root by golive-backup.timer.
#
# What runs (BACKUP_CMD overrides it; the default is the pgBackRest incremental/full schedule):
#   PostgreSQL: sudo -u postgres pgbackrest --stanza=$STANZA --type=incr backup   (full on Sunday)
#   MySQL:      set BACKUP_CMD to your XtraBackup/mariadb-backup/mysqldump pipeline.
set -euo pipefail
STANZA="${STANZA:-__PROJECT__}"
PROM="${PROM:-/var/lib/node_exporter/textfile/backup.prom}"
mkdir -p "$(dirname "$PROM")"

if [ -n "${BACKUP_CMD:-}" ]; then
  bash -c "$BACKUP_CMD"
else
  type=incr
  [ "$(date +%u)" = "7" ] && type=full
  sudo -u postgres pgbackrest --stanza="$STANZA" --type="$type" backup
  # Verify the repositories answer and WAL archiving works before calling it a success.
  sudo -u postgres pgbackrest --stanza="$STANZA" check
fi

# Optional second job: files and server .env (restic), same heartbeat only if it also succeeds.
if [ -n "${RESTIC_ENV_FILE:-}" ] && [ -r "$RESTIC_ENV_FILE" ]; then
  set -a; . "$RESTIC_ENV_FILE"; set +a
  restic backup --tag golive ${RESTIC_PATHS:-/srv/app/.env /srv/app/uploads}
  restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
fi

printf '# HELP golive_backup_last_success_timestamp_seconds unix time of the last successful backup\n# TYPE golive_backup_last_success_timestamp_seconds gauge\ngolive_backup_last_success_timestamp_seconds %s\n' "$(date +%s)" > "$PROM.tmp"
mv "$PROM.tmp" "$PROM"
