#!/usr/bin/env bash
# Called by cron every 15 minutes. myhome decides which searches are due;
# this just drains them. A lock prevents overlapping ticks.
set -u
cd "$(dirname "$0")" || exit 1
export PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin

mkdir -p logs
exec 9>logs/run.lock
flock -n 9 || exit 0

python3 -m propertysearch.main "$@" >> "logs/$(date +%F).log" 2>&1
rc=$?
find logs -name '*.log' -mtime +60 -delete 2>/dev/null
exit $rc
