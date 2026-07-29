#!/bin/sh
# Backup scheduler.
#
# A plain sleep loop rather than cron: the container has one job, cron in a
# container needs its own supervision and swallows stdout, and this way the
# dump output lands in `docker compose logs backup` like every other service.
#
# Runs once on start so a fresh deployment has a restorable backup within
# seconds rather than up to a day later — the window right after a deploy is
# exactly when one is most likely to be needed.

set -eu

INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"

echo "[backup-loop] starting; interval ${INTERVAL_SECONDS}s"

while true; do
	# A failed dump must not kill the loop — tomorrow's attempt might succeed,
	# and a backup container that exited quietly weeks ago is how a database
	# ends up with no backups at all.
	if ! /bin/sh /scripts/backup.sh; then
		echo "[backup-loop] backup FAILED; will retry next cycle" >&2
	fi
	sleep "$INTERVAL_SECONDS"
done
