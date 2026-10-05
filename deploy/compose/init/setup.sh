#!/bin/sh
# One-shot equivalent of the Helm post-install jobs: default policy plus the
# Ditto <-> Mosquitto connections. Idempotent: PUT creates or replaces, so a
# re-run after `make up` on an existing stack is harmless.
set -eu

DITTO_URL="http://ditto-nginx:80"
DEVOPS_AUTH="devops:${DITTO_DEVOPS_PASSWORD}"
DITTO_AUTH="ditto:${DITTO_PASSWORD}"

put() {
    # $1 auth, $2 url, $3 body file
    status=$(curl --silent --show-error --output /tmp/response --write-out '%{http_code}' \
        -X PUT -u "$1" -H 'Content-Type: application/json' --data-binary "@$3" "$2")
    case "$status" in
        2??) echo "ok   $status PUT $2" ;;
        *)   echo "FAIL $status PUT $2"; cat /tmp/response; echo; exit 1 ;;
    esac
}

echo "Waiting for Ditto to report UP..."
i=0
until curl --silent --fail -u "$DEVOPS_AUTH" "$DITTO_URL/status/health" | grep -q '"status" *: *"UP"'; do
    i=$((i + 1))
    if [ "$i" -ge 90 ]; then
        echo "Ditto did not become healthy within 7.5 minutes" >&2
        exit 1
    fi
    sleep 5
done
echo "Ditto is UP"

put "$DITTO_AUTH"  "$DITTO_URL/api/2/policies/default:basic_policy"                  /init/basic-policy.json
put "$DEVOPS_AUTH" "$DITTO_URL/api/2/connections/mosquitto-source-connection"        /init/mosquitto-source-connection.json
put "$DEVOPS_AUTH" "$DITTO_URL/api/2/connections/mosquitto-target-connection"        /init/mosquitto-target-connection.json
echo "OpenEgiz initialised"
