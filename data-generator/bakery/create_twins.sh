#!/usr/bin/env bash
# Create (or re-create) the five bakery twins in Eclipse Ditto.
#
# Run this ON THE HOST (gx10-11). Credentials are never stored in this repo:
# the script reads the Ditto password from the helm secrets override, or from
# $DITTO_PASSWORD if you export it yourself.
#
#   bash ~/course/bakery/create_twins.sh
#   DITTO_URL=http://192.168.0.135:30525 bash create_twins.sh   # from a laptop
#
# PUT is idempotent for the thing document, but it OVERWRITES current feature
# values back to 0. That is intentional — it is the "reset the line" button.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DITTO_URL="${DITTO_URL:-http://localhost:30525}"
DITTO_USER="${DITTO_USER:-ditto}"
SECRETS_FILE="${SECRETS_FILE:-$HOME/openegiz-deploy/secrets.values.yaml}"
TWINS_JSON="${TWINS_JSON:-$HERE/twins.json}"

if [[ -z "${DITTO_PASSWORD:-}" ]]; then
  if [[ -r "$SECRETS_FILE" ]]; then
    DITTO_PASSWORD="$(python3 -c '
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
print(d["ditto"]["global"]["basicAuthUsers"]["ditto"]["password"])
' "$SECRETS_FILE")"
  else
    echo "ERROR: no DITTO_PASSWORD and $SECRETS_FILE is unreadable." >&2
    echo "       Export DITTO_PASSWORD (see ~/course/CREDENTIALS.md on the host)." >&2
    exit 1
  fi
fi

echo "Ditto: $DITTO_URL  (user $DITTO_USER)"
rc=0
while IFS=$'\t' read -r thing_id body; do
  code="$(curl -s -o /tmp/bakery-twin.out -w '%{http_code}' \
            -u "$DITTO_USER:$DITTO_PASSWORD" -X PUT \
            -H 'Content-Type: application/json' \
            "$DITTO_URL/api/2/things/$thing_id" -d "$body")"
  case "$code" in
    201) echo "  created  $thing_id" ;;
    204) echo "  updated  $thing_id" ;;
    *)   echo "  FAILED   $thing_id  (HTTP $code)"; cat /tmp/bakery-twin.out; echo; rc=1 ;;
  esac
done < <(python3 -c '
import json, sys
for tid, doc in json.load(open(sys.argv[1])).items():
    print(tid + "\t" + json.dumps(doc, separators=(",", ":")))
' "$TWINS_JSON")

rm -f /tmp/bakery-twin.out
echo
echo "Twins now visible at: $DITTO_URL/api/2/search/things?filter=like(thingId,\"bakery:*\")"
echo "and in the OpenEgiz Grafana plugin (extended API :30528/api/twins/)."
exit $rc
