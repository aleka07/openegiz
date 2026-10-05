#!/usr/bin/env bash
#
# Ditto's services report healthy before the cluster has finished placing its
# shards, and for a while after that REST calls still fail. `make up` should
# only return once the platform actually serves requests, so wait for a run
# of consecutive successful reads.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
set -a; . "$ROOT/deploy/compose/.env"; set +a

DITTO="http://127.0.0.1:$DITTO_PORT"
needed=5
streak=0
deadline=$((SECONDS + 300))

printf 'Waiting for Ditto to serve requests '
while [ "$streak" -lt "$needed" ]; do
  if curl -sf -o /dev/null -u "ditto:$DITTO_PASSWORD" "$DITTO/api/2/policies/default:basic_policy" \
     && curl -sf -o /dev/null -u "ditto:$DITTO_PASSWORD" "$DITTO/api/2/search/things?option=size(1)"; then
    streak=$((streak + 1))
  else
    streak=0
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo
    echo "ERROR: Ditto did not start serving requests within 5 minutes." >&2
    echo "       Inspect with: make logs S=gateway" >&2
    exit 1
  fi
  printf '.'
  sleep 2
done
echo " ready"
