#!/bin/sh
# Take one PostgreSQL backup and prune old ones to the retention policy.
#
# Retention: 7 daily, 4 weekly, 6 monthly.
#
# Tiering is decided at write time by *where the dump is filed*, not later by
# reading dates off filenames. A daily job that has to work out "is this the
# backup I should promote to weekly?" gets it wrong the first time the machine
# is asleep at midnight; filing a copy into each tier it qualifies for is
# idempotent and survives missed runs.
#
# `pg_dump -Fc` (custom format) rather than plain SQL: it compresses, and
# `pg_restore` can then restore selectively and in parallel. A 600k-row
# snapshots table is not something to replay as a text script.

set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
PGDATABASE="${PGDATABASE:-memescope}"

DAILY="$BACKUP_DIR/daily"
WEEKLY="$BACKUP_DIR/weekly"
MONTHLY="$BACKUP_DIR/monthly"
mkdir -p "$DAILY" "$WEEKLY" "$MONTHLY"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
name="memescope-${stamp}.dump"
tmp="$BACKUP_DIR/.in-progress-${name}"

echo "[backup] dumping ${PGDATABASE} -> ${name}"

# Written to a temporary name and moved into place only on success, so a dump
# interrupted halfway can never be mistaken for a restorable backup. This is the
# difference between "we have backups" and "we have backups that restore".
pg_dump --format=custom --compress=6 --file="$tmp" "$PGDATABASE"
mv "$tmp" "$DAILY/$name"

# Sunday is the weekly anchor; the first of the month the monthly one. Hard
# links rather than copies: same inode, so the extra tiers cost no disk until
# the daily copy is pruned.
[ "$(date -u +%u)" = "7" ] && ln -f "$DAILY/$name" "$WEEKLY/$name"
[ "$(date -u +%d)" = "01" ] && ln -f "$DAILY/$name" "$MONTHLY/$name"

prune() {
	dir="$1"
	keep="$2"
	# Newest first, skip the ones we keep, delete the rest.
	ls -1t "$dir" 2>/dev/null | tail -n "+$((keep + 1))" | while read -r old; do
		echo "[backup] pruning $dir/$old"
		rm -f "$dir/$old"
	done
}

prune "$DAILY" 7
prune "$WEEKLY" 4
prune "$MONTHLY" 6

echo "[backup] complete: $(ls -1 "$DAILY" | wc -l) daily, $(ls -1 "$WEEKLY" | wc -l) weekly, $(ls -1 "$MONTHLY" | wc -l) monthly"
