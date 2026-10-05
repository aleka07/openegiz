#!/usr/bin/env bash
# Print where the compose stack can be reached and how to log in.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
set -a; . "$ROOT/deploy/compose/.env"; set +a
H="${OPENEGIZ_PUBLIC_HOST:-localhost}"
cat <<TXT

OpenEgiz is up.

  Grafana        http://$H:$GRAFANA_PORT        admin / $GRAFANA_ADMIN_PASSWORD
  Ditto API      http://$H:$DITTO_PORT/api/2    ditto / $DITTO_PASSWORD   (devops / $DITTO_DEVOPS_PASSWORD)
  Extended API   http://$H:$EXTENDED_API_PORT
  InfluxDB       http://$H:$INFLUXDB_PORT        admin / $INFLUXDB_ADMIN_PASSWORD
  MQTT           tcp://$H:$MQTT_PORT
  Unity WebGL    http://$H:$UNITY_PORT/build/<file>   (files from ./build/)

Credentials live in deploy/compose/.env. Check everything with: make smoke
TXT
