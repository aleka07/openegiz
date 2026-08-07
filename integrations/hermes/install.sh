#!/usr/bin/env bash
# Deploy the OpenEgiz <-> Hermes integration ON THE HOST (gx10-11).
#
# Idempotent: safe to re-run after every rsync of this directory.
#
# From the repo checkout on the workstation:
#   rsync -a --delete "integrations/hermes/" gx10-11:~/openegiz-hermes/
#   ssh gx10-11 'bash ~/openegiz-hermes/install.sh'
#
# What it does:
#   1. installs the MCP server dependencies into ~/course/venv
#   2. copies the MCP servers to ~/course/mcp/
#   3. copies the skills to ~/.hermes/skills/openegiz/
#   4. writes ~/.config/openegiz-mcp.env (chmod 600) with the InfluxDB admin
#      token read from the k8s secret — the token never leaves the host
#   5. backs up ~/.hermes/config.yaml (timestamped) and registers the two MCP
#      servers, touching nothing else in the config
#
# Env overrides: VENV, MCP_DIR, SKILLS_DIR, ENV_FILE, HERMES_BIN.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV:-$HOME/course/venv}"
MCP_DIR="${MCP_DIR:-$HOME/course/mcp}"
SKILLS_DIR="${SKILLS_DIR:-$HOME/.hermes/skills/openegiz}"
ENV_FILE="${ENV_FILE:-$HOME/.config/openegiz-mcp.env}"
HERMES_BIN="${HERMES_BIN:-$HOME/.local/bin/hermes}"
HERMES_CONFIG="$HOME/.hermes/config.yaml"
KUBECONFIG_PATH="${KUBECONFIG_PATH:-/etc/rancher/k3s/k3s.yaml}"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- preflight
say "preflight"
[ -x "$VENV/bin/python" ] || die "python venv not found at $VENV (expected the course venv)"
[ -x "$HERMES_BIN" ]      || die "hermes not found at $HERMES_BIN"
[ -f "$HERMES_CONFIG" ]   || die "hermes config not found at $HERMES_CONFIG"
echo "venv:    $($VENV/bin/python -V)"
echo "hermes:  $HERMES_BIN"

# ------------------------------------------------------------ dependencies
# Decision: reuse ~/course/venv rather than creating a second venv. It already
# carries influxdb-client, paho-mqtt, requests and pandas for the pm4py work,
# so the MCP servers only add fastmcp. One interpreter, one place to look.
say "python dependencies (into $VENV)"
"$VENV/bin/pip" install --quiet --upgrade fastmcp influxdb-client paho-mqtt requests
"$VENV/bin/python" - <<'PY'
import fastmcp, influxdb_client, paho.mqtt, requests
print("fastmcp", fastmcp.__version__)
print("influxdb-client", influxdb_client.__version__)
print("requests", requests.__version__)
PY

# ------------------------------------------------------------- mcp servers
say "MCP servers -> $MCP_DIR"
mkdir -p "$MCP_DIR"
install -m 0644 "$SRC_DIR/_env.py"      "$MCP_DIR/_env.py"
install -m 0755 "$SRC_DIR/mcp_ditto.py" "$MCP_DIR/mcp_ditto.py"
install -m 0755 "$SRC_DIR/mcp_influx.py" "$MCP_DIR/mcp_influx.py"
ls -l "$MCP_DIR"

# ------------------------------------------------------------------ skills
# Skills need no config entry: Hermes discovers ~/.hermes/skills/<category>/<name>/SKILL.md
# on startup. "openegiz" is the category folder.
say "skills -> $SKILLS_DIR"
mkdir -p "$SKILLS_DIR"
cp -a "$SRC_DIR/skills/." "$SKILLS_DIR/"
find "$SKILLS_DIR" -name '*.sh' -exec chmod 0755 {} +
find "$SKILLS_DIR" -name 'SKILL.md' -printf '  %p\n'

# --------------------------------------------------------------- env file
say "credentials -> $ENV_FILE"
INFLUX_TOKEN="$(sudo KUBECONFIG="$KUBECONFIG_PATH" kubectl -n opentwins get secret \
    opentwins-influxdb2-auth -o jsonpath='{.data.admin-token}' | base64 -d)"
[ -n "$INFLUX_TOKEN" ] || die "could not read admin-token from secret/opentwins-influxdb2-auth"

mkdir -p "$(dirname "$ENV_FILE")"
umask 077
cat > "$ENV_FILE" <<EOF
# OpenEgiz MCP server configuration — written by integrations/hermes/install.sh
# SECRET FILE. Never copy this into the repo or paste its contents anywhere.
DITTO_URL=http://localhost:30525/api/2
DITTO_USER=ditto
DITTO_PASSWORD=ditto
MQTT_HOST=localhost
MQTT_PORT=30511
INFLUX_URL=http://localhost:30716
INFLUX_ORG=opentwins
INFLUX_BUCKET=default
INFLUX_TOKEN=$INFLUX_TOKEN
EOF
chmod 600 "$ENV_FILE"
unset INFLUX_TOKEN
ls -l "$ENV_FILE"
echo "(token length: $(grep -c . "$ENV_FILE") lines written, value not printed)"

# -------------------------------------------------------- hermes config.yaml
say "registering MCP servers in $HERMES_CONFIG"
BACKUP="$HERMES_CONFIG.bak.$(date +%Y%m%d_%H%M%S)"
cp -p "$HERMES_CONFIG" "$BACKUP"
echo "backup: $BACKUP"

register() {
  local name="$1" script="$2"
  # remove-then-add keeps the script idempotent; `remove` on a missing entry
  # is a no-op we deliberately ignore.
  "$HERMES_BIN" mcp remove "$name" >/dev/null 2>&1 || true
  # `mcp add` probes the server and then asks "Enable all N tools? [Y/n/select]".
  # Without a TTY that prompt reads EOF and cancels the whole add, so answer it.
  printf 'y\n' | "$HERMES_BIN" mcp add "$name" \
      --command "$VENV/bin/python" \
      --connect-timeout 60 \
      --env "OPENEGIZ_ENV_FILE=$ENV_FILE" \
      --args "$MCP_DIR/$script"
}
register openegiz-ditto  mcp_ditto.py
register openegiz-influx mcp_influx.py

say "result"
"$HERMES_BIN" mcp list || true
cat <<EOF

Done. Verify with:
  hermes mcp test openegiz-ditto
  hermes mcp test openegiz-influx
  hermes -z "What is the current temperature of thing test:winterschool-1?"

Config backup kept at: $BACKUP
EOF
