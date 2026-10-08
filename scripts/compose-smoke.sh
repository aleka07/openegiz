#!/usr/bin/env bash
#
# End-to-end check of a running compose stack. Exercises the full loop the
# platform exists for:
#   MQTT (Ditto protocol) -> Ditto twin -> MQTT event -> Telegraf -> InfluxDB
# plus Grafana provisioning, the extended API and the Unity file server.
# Leaves nothing behind: the test twin is deleted at the end.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/deploy/compose/docker-compose.yml")
# shellcheck disable=SC1091
set -a; . "$ROOT/deploy/compose/.env"; set +a

HOST=127.0.0.1
DITTO="http://$HOST:$DITTO_PORT"
GRAFANA="http://$HOST:$GRAFANA_PORT"
THING="org.openegiz:smoke-test-$$"
FAILED=0

pass() { printf '  \033[32mok\033[0m    %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }
check() { local name="$1"; shift; if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi; }
# For reads from Ditto: right after start, while its JVMs warm up and the
# Example Mine simulator starts, Ditto answers 503 "Please retry" for a few
# seconds at a time. Retry for up to a minute before calling it a failure.
check_ditto() {
  local name="$1"; shift
  for _ in $(seq 1 20); do
    if "$@" >/dev/null 2>&1; then pass "$name"; return; fi
    sleep 3
  done
  fail "$name"
}

cleanup() {
  curl -s -o /dev/null -u "ditto:$DITTO_PASSWORD" -X DELETE "$DITTO/api/2/things/$THING" || true
}
trap cleanup EXIT

echo "Containers"
init_exit=$("${COMPOSE[@]}" ps -a --format '{{.Service}} {{.ExitCode}}' | awk '$1=="init"{print $2}')
if [ "$init_exit" = "0" ]; then pass "init job finished (policy + connections)"; else fail "init job exit code: ${init_exit:-not run}"; fi
unhealthy=$("${COMPOSE[@]}" ps --format '{{.Service}} {{.Health}}' | awk '$2!="" && $2!="healthy"{print $1}')
if [ -z "$unhealthy" ]; then pass "all health-checked services healthy"; else fail "not healthy: $(echo $unhealthy)"; fi

echo "Ditto"
check_ditto "status/health is UP" sh -c "curl -sf -u devops:$DITTO_DEVOPS_PASSWORD $DITTO/status/health | grep -q '\"UP\"'"
check_ditto "default policy exists" curl -sf -u "ditto:$DITTO_PASSWORD" "$DITTO/api/2/policies/default:basic_policy"
for c in mosquitto-source-connection mosquitto-target-connection; do
  check_ditto "connection $c open" sh -c "curl -sf -u devops:$DITTO_DEVOPS_PASSWORD $DITTO/api/2/connections/$c/status | grep -q '\"open\"'"
done
check_ditto "create test twin" curl -sf -u "ditto:$DITTO_PASSWORD" -X PUT -H 'Content-Type: application/json' \
  -d '{"policyId":"default:basic_policy","features":{"smoke":{"properties":{"value":0}}}}' "$DITTO/api/2/things/$THING"

# Each Ditto JVM needs about 300 MiB besides its heap (metaspace, JIT code, GC
# structures, threads), more as it runs; the compose file gives it 512. With
# less room the kernel kills the JVM once the heap has grown under load,
# 5-60 minutes into a run (docker reports exit 137 and OOMKilled=false). The heap size comes from the JVM itself, so
# this also catches a JVM that cannot see its container limit and sizes the
# heap from the host's memory (JDK 17.0.8 on kernels without the cgroup v1
# memory controller, such as the 6.12 kernel of recent Docker Desktop).
echo "Ditto memory"
for svc in policies things things-search connectivity gateway; do
  heap="" limit=""
  for _ in 1 2 3; do
    heap=$("${COMPOSE[@]}" exec -T "$svc" curl -s -m 5 localhost:9095/ 2>/dev/null \
      | awk '/^jvm_memory_max_bytes\{region="heap"/ {printf "%d", $2 / 1048576}') || true
    [ -n "$heap" ] && break
    sleep 3
  done
  limit=$("${COMPOSE[@]}" exec -T "$svc" sh -c 'cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes' 2>/dev/null \
    | awk '/^[0-9]+$/ {printf "%d", $1 / 1048576}') || true
  if [ -z "$heap" ] || [ -z "$limit" ]; then
    fail "$svc: could not read max heap (${heap:-?} MiB) or container limit (${limit:-?} MiB)"
  elif [ $((limit - heap)) -ge 512 ]; then
    pass "$svc: max heap ${heap} MiB leaves $((limit - heap)) MiB of its ${limit} MiB limit"
  else
    fail "$svc: max heap ${heap} MiB leaves $((limit - heap)) MiB of its ${limit} MiB limit (need 512)"
  fi
done

echo "Telemetry loop"
value=$((RANDOM % 1000 + 1))
msg=$(printf '{"topic":"%s/%s/things/twin/commands/modify","path":"/features/smoke/properties/value","value":%s}' \
  "${THING%%:*}" "${THING#*:}" "$value")
# Capture the twin event Ditto publishes back, to check what it exposes.
event_file="$(mktemp)"
"${COMPOSE[@]}" exec -T mosquitto mosquitto_sub -h localhost -C 1 -W 30 \
  -t "opentwins/twin/events/${THING%%:*}/${THING#*:}" >"$event_file" 2>/dev/null &
sub_pid=$!
sleep 1
"${COMPOSE[@]}" exec -T mosquitto mosquitto_pub -h localhost -t telemetry/smoke -m "$msg"

ok=0
for _ in $(seq 1 15); do
  got=$(curl -sf -u "ditto:$DITTO_PASSWORD" "$DITTO/api/2/things/$THING/features/smoke/properties/value" || true)
  if [ "$got" = "$value" ]; then ok=1; break; fi
  sleep 1
done
if [ $ok = 1 ]; then pass "MQTT -> Ditto updated the twin"; else fail "MQTT -> Ditto: twin value is '${got:-?}', expected $value"; fi

wait "$sub_pid" || true
if [ ! -s "$event_file" ]; then
  fail "Ditto published no twin event on opentwins/#"
elif grep -qi '"authorization"' "$event_file"; then
  fail "twin events on MQTT leak the HTTP Authorization header"
else
  pass "twin event published without credentials"
fi
rm -f "$event_file"

ok=0
flux="from(bucket:\"default\") |> range(start:-5m) |> filter(fn:(r) => r.thingId == \"$THING\") |> last()"
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T influxdb influx query --org opentwins --token "$INFLUXDB_TOKEN" --raw "$flux" 2>/dev/null \
      | grep -q ",$value,"; then ok=1; break; fi
  sleep 2
done
if [ $ok = 1 ]; then pass "Ditto -> Telegraf -> InfluxDB stored the value"; else fail "value $value did not reach InfluxDB within 60 s"; fi

echo "Grafana"
check "API healthy" curl -sf "$GRAFANA/api/health"
check "OpenEgiz app plugin enabled" sh -c "curl -sf -u admin:$GRAFANA_ADMIN_PASSWORD $GRAFANA/api/plugins/ertis-opentwins-app/settings | grep -q '\"enabled\":true'"
check "Unity panel plugin loaded" curl -sf -u "admin:$GRAFANA_ADMIN_PASSWORD" "$GRAFANA/api/plugins/ertis-unity-panel/settings"
check "InfluxDB datasource healthy" sh -c "curl -sf -u admin:$GRAFANA_ADMIN_PASSWORD $GRAFANA/api/datasources/uid/opentwins-influxdb/health | grep -q '\"OK\"'"
# The OpenEgiz app reaches Ditto and the extended API only through Grafana's
# plugin proxy, from inside the Grafana container.
PROXY="$GRAFANA/api/plugin-proxy/ertis-opentwins-app"
check_ditto "OpenEgiz app reaches Ditto (plugin proxy)" curl -sf -u "admin:$GRAFANA_ADMIN_PASSWORD" "$PROXY/ditto/api/2/search/things?option=size(1)"
check "OpenEgiz app reaches the extended API (plugin proxy)" sh -c "curl -s -o /dev/null -w '%{http_code}' -u admin:$GRAFANA_ADMIN_PASSWORD $PROXY/extended/ | grep -qE '^[2-4][0-9][0-9]$'"

echo "Extended API and Unity"
check "extended API answers" sh -c "curl -s -o /dev/null -w '%{http_code}' http://$HOST:$EXTENDED_API_PORT/ | grep -qE '^[2-4][0-9][0-9]$'"
check "Unity file server serves build/" curl -sf -o /dev/null "http://$HOST:$UNITY_PORT/build/README.md"

if "${COMPOSE[@]}" ps -a --format '{{.Service}}' 2>/dev/null | grep -qx mine-setup || \
   docker ps -a --format '{{.Names}}' | grep -q '^openegiz-mine-simulator-'; then
  echo "Example Mine"
  for twin in mine-01 excavator-01 truck-01 truck-02 crusher-01; do
    check_ditto "twin org.openegiz.mine:$twin exists" curl -sf -u "ditto:$DITTO_PASSWORD" "$DITTO/api/2/things/org.openegiz.mine:$twin"
  done
  ok=0
  mine_flux='from(bucket:"default") |> range(start:-2m) |> filter(fn:(r) => r.thingId == "org.openegiz.mine:truck-01" and r._field == "value_route_position_properties_value") |> count()'
  for _ in $(seq 1 30); do
    if "${COMPOSE[@]}" exec -T influxdb influx query --org opentwins --token "$INFLUXDB_TOKEN" --raw "$mine_flux" 2>/dev/null \
        | grep -qE ',[1-9][0-9]*,value_route_position_properties_value,'; then ok=1; break; fi
    sleep 2
  done
  if [ $ok = 1 ]; then pass "simulator telemetry reaches InfluxDB"; else fail "no Example Mine telemetry in InfluxDB for the last 2 minutes"; fi
  # Same query the app's Twins page sends.
  check_ditto "Twins UI lists the Example Mine twins" sh -c "curl -sf -u admin:$GRAFANA_ADMIN_PASSWORD '$PROXY/ditto/api/2/search/things?filter=ne(attributes/_isType,true)&fields=thingId&option=size(200)' | grep -q 'org.openegiz.mine:truck-01'"
  check "dashboard provisioned" curl -sf -u "admin:$GRAFANA_ADMIN_PASSWORD" "$GRAFANA/api/dashboards/uid/openegiz-example-mine"
fi

echo
if [ $FAILED = 0 ]; then echo "Smoke test passed."; else echo "Smoke test FAILED."; exit 1; fi
