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
#   4. writes ~/.config/openegiz-mcp.env (chmod 600) with the Ditto password
#      taken from the helm secrets override and a READ-ONLY InfluxDB token
#      minted inside the influxdb pod — no secret ever leaves the host
#   5. backs up ~/.hermes/config.yaml (timestamped), registers the two MCP
#      servers and re-applies the openegiz-ditto tool filter, touching
#      nothing else in the config
#
# Env overrides: VENV, MCP_DIR, SKILLS_DIR, ENV_FILE, HERMES_BIN,
#                SECRETS_FILE, DITTO_PASSWORD.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV:-$HOME/course/venv}"
MCP_DIR="${MCP_DIR:-$HOME/course/mcp}"
SKILLS_DIR="${SKILLS_DIR:-$HOME/.hermes/skills/openegiz}"
ENV_FILE="${ENV_FILE:-$HOME/.config/openegiz-mcp.env}"
HERMES_BIN="${HERMES_BIN:-$HOME/.local/bin/hermes}"
HERMES_CONFIG="$HOME/.hermes/config.yaml"
KUBECONFIG_PATH="${KUBECONFIG_PATH:-/etc/rancher/k3s/k3s.yaml}"
# Credentials were rotated 2026-08-07 and deliberately live outside the repo.
SECRETS_FILE="${SECRETS_FILE:-$HOME/openegiz-deploy/secrets.values.yaml}"
INFLUX_RO_DESC="hermes MCP read-only (created 2026-08-07)"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# Print a read-only InfluxDB token for the `default` bucket, creating it on
# first run. Everything happens inside the influxdb pod; only the token value
# crosses back, and it is never echoed to the terminal by the caller.
#
# NOTE: `kubectl exec` without -i on purpose. With -i it forwards this
# script's stdin, which silently swallows the rest of the script when the
# installer is piped in (`ssh host 'bash -s' < install.sh`).
get_or_create_readonly_influx_token() {
  local k="sudo KUBECONFIG=$KUBECONFIG_PATH kubectl -n opentwins"
  local pod=opentwins-influxdb2-0
  local op tok
  op="$($k get secret opentwins-influxdb2-auth -o jsonpath='{.data.admin-token}' | base64 -d)"
  [ -n "$op" ] || die "could not read admin-token from secret/opentwins-influxdb2-auth"

  _lookup() {
    $k exec "$pod" -- influx auth list -t "$op" --json \
      | DESC="$INFLUX_RO_DESC" "$VENV/bin/python" -c '
import json, os, sys
print(next((a["token"] for a in json.load(sys.stdin)
            if a["description"] == os.environ["DESC"]), ""))'
  }

  tok="$(_lookup)"
  if [ -z "$tok" ]; then
    local bucket_id
    bucket_id="$($k exec "$pod" -- influx bucket list -t "$op" --org opentwins --json \
      | "$VENV/bin/python" -c '
import json, sys
print(next(b["id"] for b in json.load(sys.stdin) if b["name"] == "default"))')"
    $k exec "$pod" -- influx auth create --read-bucket "$bucket_id" --org opentwins \
      -t "$op" -d "$INFLUX_RO_DESC" >/dev/null
    tok="$(_lookup)"
  fi
  printf '%s' "$tok"
}

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

# Ditto password: taken from the helm secrets override, which is the single
# source of truth for what is actually deployed. It is NOT in the repo.
if [ -z "${DITTO_PASSWORD:-}" ]; then
  [ -f "$SECRETS_FILE" ] || die "secrets override not found: $SECRETS_FILE (or pass DITTO_PASSWORD=...)"
  DITTO_PASSWORD="$("$VENV/bin/python" - "$SECRETS_FILE" <<'PY'
import sys, yaml
print(yaml.safe_load(open(sys.argv[1]))["ditto"]["global"]["basicAuthUsers"]["ditto"]["password"])
PY
)"
fi
[ -n "$DITTO_PASSWORD" ] || die "could not determine the Ditto password"

# InfluxDB token: a READ-ONLY token scoped to the `default` bucket, minted
# inside the influxdb pod. Hermes must never hold the operator token — the
# agent is allowed to query history, not to rewrite it. Reused if it exists.
INFLUX_TOKEN="$(get_or_create_readonly_influx_token)"
[ -n "$INFLUX_TOKEN" ] || die "could not obtain a read-only InfluxDB token"

mkdir -p "$(dirname "$ENV_FILE")"
umask 077
cat > "$ENV_FILE" <<EOF
# OpenEgiz MCP server configuration — written by integrations/hermes/install.sh
# SECRET FILE. Never copy this into the repo or paste its contents anywhere.
DITTO_URL=http://localhost:30525/api/2
DITTO_USER=ditto
DITTO_PASSWORD=$DITTO_PASSWORD
MQTT_HOST=localhost
MQTT_PORT=30511
INFLUX_URL=http://localhost:30716
INFLUX_ORG=opentwins
INFLUX_BUCKET=default
INFLUX_TOKEN=$INFLUX_TOKEN
EOF
chmod 600 "$ENV_FILE"
unset INFLUX_TOKEN DITTO_PASSWORD
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

# `mcp add` writes a fresh server block, so the tool filter has to be put back
# every time. Schema (hermes-agent tools/mcp_tool.py, _register_server_tools):
#   mcp_servers.<name>.tools.include -> whitelist, takes precedence
#   mcp_servers.<name>.tools.exclude -> blacklist; exact names or fnmatch globs
# set_feature_property writes straight into the twin and bypasses the
# MQTT -> Ditto -> Telegraf -> InfluxDB path the course is built around.
# publish_telemetry deliberately stays: it uses the real pipeline.
say "restricting openegiz-ditto tools"
"$VENV/bin/python" - "$HERMES_CONFIG" <<'PY'
import sys
p = sys.argv[1]
lines = open(p).read().splitlines()
anchor = "  openegiz-ditto:"
if anchor not in lines:
    sys.exit("ERROR: %r not found in %s" % (anchor, p))
i = lines.index(anchor)
j = i + 1
while j < len(lines) and (lines[j].startswith("    ") or not lines[j].strip()):
    j += 1
if "set_feature_property" in "\n".join(lines[i:j]):
    print("  already excluded")
else:
    lines[i+1:i+1] = [
        "    tools:",
        "      # direct twin writes bypass the MQTT -> Ditto -> Telegraf -> InfluxDB",
        "      # path; publish_telemetry stays because it uses the real pipeline.",
        "      exclude:",
        "        - set_feature_property",
    ]
    open(p, "w").write("\n".join(lines) + "\n")
    print("  set_feature_property excluded")
PY

say "result"
"$HERMES_BIN" mcp list || true
cat <<EOF

Done. Verify with:
  hermes mcp test openegiz-ditto
  hermes mcp test openegiz-influx
  hermes -z "What is the current temperature of thing test:winterschool-1?"

Config backup kept at: $BACKUP
EOF
