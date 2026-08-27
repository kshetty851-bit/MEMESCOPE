#!/usr/bin/env bash
# Reclaim Docker's disk when the host gets tight. Run from cron on the HOST.
#
# WHY THIS LIVES OUTSIDE THE APPLICATION
#
# HQ already watches the disk and can run the retention prune itself
# (`disk.run_retention`, `disk.emergency_check`). Those reach the DATABASE, and
# on 2026-08-26 the database had nothing left to give — retention was current,
# score history was already at its 3-day emergency window, and the disk still
# climbed to 95% and failed a deploy's build.
#
# What was actually consuming it: 5.8GB of Docker build cache and 4.5GB of old
# dumps. No container can prune Docker, because no container mounts
# docker.sock — that socket is root on the host, and handing it to a Celery
# worker to save disk would be a bad trade. So this runs on the host instead,
# which is the only place with the authority to do it.
#
# WHAT IT WILL NOT DO
#
#   * volumes  — postgres-data lives there. `prune --volumes` is never used.
#   * backups  — retention belongs to backup.sh (3 daily / 1 weekly / 1 monthly).
#   * images in use — only dangling and unreferenced ones go.
#   * restart the docker daemon — a restart releases buildkit's cache, and on
#     2026-08-26 that was worth 5.8GB when a plain prune returned nothing. It
#     is still not automated: it stops every container, and a machine that
#     decides on its own to bounce a live trading stack to save disk is worse
#     than a full disk. When a prune cannot get under the threshold, this says
#     so and leaves it to a human.
set -euo pipefail

THRESHOLD="${DISK_GUARD_THRESHOLD:-85}"
LOG="${DISK_GUARD_LOG:-/var/log/memescope-disk-guard.log}"

used() { df --output=pcent / | tail -1 | tr -dc '0-9'; }
say() { echo "[disk-guard] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >>"$LOG"; }

before="$(used)"
if [ "$before" -lt "$THRESHOLD" ]; then
	exit 0
fi

say "disk ${before}% >= ${THRESHOLD}%, reclaiming"

# Build cache first: it is the biggest and the least missed. Buildkit refuses
# to drop records an active build still references, so this is safe to run at
# any time, including mid-deploy — it declines rather than corrupts.
docker builder prune -af >>"$LOG" 2>&1 || say "builder prune failed"
docker image prune -f >>"$LOG" 2>&1 || say "image prune failed"

after="$(used)"
say "reclaimed to ${after}% (was ${before}%)"

if [ "$after" -ge "$THRESHOLD" ]; then
	# Deliberately loud and deliberately inert. The remaining space is either
	# buildkit cache pinned by the running daemon or the database itself, and
	# neither is something a cron job should decide to take.
	say "STILL ${after}% — pruning could not clear it. Needs a human: either a"
	say "  docker daemon restart (releases pinned buildkit cache, stops every"
	say "  container) or a look at database growth. Not doing either from cron."
fi
