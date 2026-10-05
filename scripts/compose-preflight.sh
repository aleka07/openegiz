#!/usr/bin/env bash
#
# Catch the usual first-run problems before `docker compose up` turns them
# into cryptic container errors: Docker not running, an old Compose, too
# little memory for Docker, host ports already taken.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
set -a; . "$ROOT/deploy/compose/.env"; set +a

die() { printf '\033[31mERROR:\033[0m %s\n' "$1" >&2; exit 1; }
warn() { printf '\033[33mWARNING:\033[0m %s\n' "$1" >&2; }

docker info >/dev/null 2>&1 || die "Docker is not running (start Docker Desktop, or the docker service on Linux)."

compose_version="$(docker compose version --short 2>/dev/null || true)"
[ -n "$compose_version" ] || die "Docker Compose v2 is required ('docker compose', not 'docker-compose')."
major="${compose_version%%.*}"; rest="${compose_version#*.}"; minor="${rest%%.*}"
if [ "$major" -lt 2 ] || { [ "$major" -eq 2 ] && [ "$minor" -lt 20 ]; }; then
  die "Docker Compose $compose_version is too old; 2.20 or newer is required."
fi

mem_bytes="$(docker info --format '{{.MemTotal}}')"
mem_gib=$((mem_bytes / 1024 / 1024 / 1024))
if [ "$mem_gib" -lt 6 ]; then
  warn "Docker has ${mem_gib} GiB of memory; OpenEgiz needs about 6 GiB. Raise it in Docker Desktop -> Settings -> Resources."
fi

# A port is a problem only if something other than this stack holds it.
ours="$(docker compose -f "$ROOT/deploy/compose/docker-compose.yml" ps -q 2>/dev/null || true)"
if [ -z "$ours" ]; then
  busy=()
  for var in GRAFANA_PORT DITTO_PORT EXTENDED_API_PORT UNITY_PORT INFLUXDB_PORT MQTT_PORT; do
    port="${!var}"
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      busy+=("$var=$port")
    fi
  done
  if [ "${#busy[@]}" -gt 0 ]; then
    die "Ports already in use on this machine: ${busy[*]}. Stop whatever uses them, or change these values in deploy/compose/.env."
  fi
fi
