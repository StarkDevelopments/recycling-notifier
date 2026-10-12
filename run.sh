#!/usr/bin/env bash
# Run the recycling notifier in a throwaway container.
#
# Nothing stays running: the container starts, queries the council API, sends
# a Pushover notification if there is something to say, then exits. This is the
# same command cron fires at 2pm UK time; use it to run manually right now:
#
#   ./run.sh
#
# Exit codes pass through: 0 = ran (with or without a notification), 1 = failed.
set -euo pipefail
cd "$(dirname "$0")"

IMAGE="${RECYCLING_NOTIFIER_IMAGE:-recycling-notifier:latest}"

if [ ! -f .env ]; then
  echo "missing .env - copy .env.example to .env and fill in your Pushover credentials" >&2
  exit 1
fi

exec docker run --rm \
  --env-file .env \
  "$IMAGE" "$@"
