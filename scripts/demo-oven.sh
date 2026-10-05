#!/usr/bin/env bash
# Oven demo (examples/oven): create the two oven twins in Ditto, then stream
# telemetry over MQTT until Ctrl+C. Run via `make generate-data`.
#
# Compose (default): ports and the Ditto password come from deploy/compose/.env.
# Helm: pass them explicitly, e.g.
#   make generate-data MQTT_PORT=30511 DITTO_URL=http://localhost:30525 DITTO_PASSWORD=...
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/deploy/compose/.env"
VENV="$ROOT/examples/.venv"

# Caller-provided values win over deploy/compose/.env.
caller_mqtt_port="${MQTT_PORT:-}"
caller_ditto_url="${DITTO_URL:-}"
caller_ditto_password="${DITTO_PASSWORD:-}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
MQTT_PORT="${caller_mqtt_port:-${MQTT_PORT:-1883}}"
DITTO_URL="${caller_ditto_url:-http://localhost:${DITTO_PORT:-8080}}"
DITTO_PASSWORD="${caller_ditto_password:-${DITTO_PASSWORD:-}}"
if [ -z "$DITTO_PASSWORD" ]; then
  echo "ERROR: no Ditto password. Start the platform with 'make up' first," >&2
  echo "       or pass DITTO_PASSWORD=... (Helm deployments)." >&2
  exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "==> creating $VENV (first run only)"
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --disable-pip-version-check -r "$ROOT/examples/requirements.txt"

echo "==> oven twins in Ditto ($DITTO_URL)"
DITTO_URL="$DITTO_URL" DITTO_PASSWORD="$DITTO_PASSWORD" \
  TWINS_FILE="$ROOT/examples/oven/twins.json" \
  "$VENV/bin/python" "$ROOT/examples/mine/setup_twins.py"

echo "==> streaming oven telemetry to MQTT localhost:$MQTT_PORT (Ctrl+C to stop)"
exec "$VENV/bin/python" "$ROOT/examples/oven/data_generator.py" --mqtt-port "$MQTT_PORT"
