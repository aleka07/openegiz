# Hermes ↔ OpenEgiz integration

This directory is the **source of truth** for everything that connects the
self-hosted [Hermes Agent](https://github.com/NousResearch/hermes-agent) on
`gx10-11` to the OpenEgiz digital-twin stack. Nothing here is edited on the
host directly — you edit it in this repo, rsync it over, and re-run
`install.sh`.

A student talks to Hermes in plain language; Hermes decides which of the tools
below to call.

## What gets registered

| Layer | Name | Mechanism | Backs onto |
|---|---|---|---|
| MCP server | `openegiz-ditto` | stdio, FastMCP | Eclipse Ditto REST API + MQTT |
| MCP server | `openegiz-influx` | stdio, FastMCP | InfluxDB2 |
| Skill | `openegiz/jaamsim` | `SKILL.md` + wrapper script | JaamSim CLI (headless) |
| Skill | `openegiz/pm4py-mining` | `SKILL.md` + helper script | pm4py venv + InfluxDB |

The split follows Nous's own rule: an **MCP tool** when the integration needs
credentials and its own request/response handling (Ditto, InfluxDB); a
**skill** when it is instructions plus shell commands over tools Hermes
already has (JaamSim, pm4py).

## Tool → stack map

`mcp_ditto.py` → **Eclipse Ditto** on `http://localhost:30525/api/2`
(basic auth as user `ditto`; the password was rotated 2026-08-07 and lives only on
the host, see `~/course/CREDENTIALS.md`) and **MQTT** on `localhost:30511`.

| Tool | Does | Path through the stack |
|---|---|---|
| `list_things` | Enumerate twins | `GET /search/things` |
| `get_thing` | Full twin document | `GET /things/{id}` |
| `get_feature` | **Current** value of one feature | `GET /things/{id}/features/{f}` |
| `set_feature_property` | Administrative twin write | `PUT …/properties/{path}` — twin only, **no history** |
| `publish_telemetry` | Simulate a device reading | MQTT `telemetry/{id}` → Ditto source connection → twin → Telegraf → InfluxDB |

The two write paths are deliberately different tools with different
docstrings, because the difference is the whole point of the course: a REST
write edits the twin, a device publish creates history.

`mcp_influx.py` → **InfluxDB2** on `http://localhost:30716`, org `opentwins`,
bucket `default`, measurement `mqtt_consumer`, tag `thingId`, fields
`value_<feature>_properties_value`.

| Tool | Does |
|---|---|
| `get_recent_telemetry` | Compact table + per-field min/max/last, auto-downsampled |
| `list_thing_ids` | Which twins actually reported in a window |
| `flux_query` | Raw Flux escape hatch, truncated to a safe size |

`skills/jaamsim` → `java -jar ~/course/jaamsim/JaamSim2026-05.jar <cfg> -headless`.
The wrapper exists because **JaamSim always exits 0**, even on failure; it
compares `.dat`/`.rep` mtimes before and after and only then prints the `.dat`.

`skills/pm4py-mining` → `~/course/venv/bin/python`, plus
`scripts/influx_to_dataframe.py` for pulling telemetry into pandas.

## Where things land on the host

| Source here | Host path |
|---|---|
| `mcp_ditto.py`, `mcp_influx.py`, `_env.py` | `~/course/mcp/` |
| `skills/*` | `~/.hermes/skills/openegiz/` |
| (generated) | `~/.config/openegiz-mcp.env`, chmod 600 |
| (edited) | `~/.hermes/config.yaml` — only the `mcp_servers` key |

**Python environment: `~/course/venv` is reused, not duplicated.** It already
carries `influxdb-client`, `paho-mqtt`, `requests` and `pandas` for the pm4py
work, so the MCP servers only add `fastmcp`. One interpreter means one place
to look when an import breaks, and the pm4py skill and the MCP servers cannot
drift apart.

## Secrets

`install.sh` assembles `~/.config/openegiz-mcp.env` (mode 600) **on the host**
and nothing lands in this repo:

- the Ditto password comes from the helm secrets override
  `~/openegiz-deploy/secrets.values.yaml`, which is the source of truth for
  what is actually deployed;
- the InfluxDB token is a **read-only** token scoped to the `default` bucket,
  minted inside the influxdb pod on first run and reused afterwards. Hermes
  never holds the operator token — the agent may query history, not rewrite it.

Neither value is in `config.yaml`: each MCP server loads the env file itself at
startup (`_env.py`), and `config.yaml` only carries the path to it. Real
environment variables win over the file, so anything can still be overridden
per-server.

## Tool filter

`set_feature_property` is excluded from the `openegiz-ditto` server in
`~/.hermes/config.yaml`:

```yaml
mcp_servers:
  openegiz-ditto:
    tools:
      exclude:
        - set_feature_property
```

A direct twin write bypasses the MQTT → Ditto → Telegraf → InfluxDB path the
course is built around, so students get `publish_telemetry` instead. `mcp add`
rewrites the server block, so `install.sh` re-applies the filter after
registering. Note `hermes mcp test` still lists all five tools — that is what
the server advertises; the filter applies when tools are registered with the
agent, so check `hermes mcp list` (`-1 excluded`) instead.

## Deploy / re-deploy

```bash
# from the repo root, on the workstation
rsync -a --delete "integrations/hermes/" gx10-11:~/openegiz-hermes/
ssh gx10-11 'bash ~/openegiz-hermes/install.sh'
```

`install.sh` is idempotent — re-running it re-copies files, re-reads the
token, takes a fresh timestamped backup of `config.yaml`, and re-registers the
MCP servers (`hermes mcp remove` then `hermes mcp add`). It only ever writes
the `mcp_servers` key; model, terminal, agent and toolset settings are
untouched.

Verify:

```bash
hermes mcp list
hermes mcp test openegiz-ditto
hermes mcp test openegiz-influx
hermes skills list | grep openegiz
hermes -z "What is the current temperature of thing test:winterschool-1?"
```

Note that `hermes` is **not** on the non-interactive PATH — use
`~/.local/bin/hermes` or export `PATH=$HOME/.local/bin:$PATH` first.

## Editing the MCP tools

The docstrings *are* the interface: they are what the model reads to decide
which tool to call and what to pass. Treat a wrong tool choice as a docstring
bug first and a model limitation second. After editing, re-copy the file and
start a new session — Hermes reconnects stdio servers per session:

```bash
rsync -a integrations/hermes/ gx10-11:~/openegiz-hermes/
ssh gx10-11 'install -m0755 ~/openegiz-hermes/mcp_influx.py ~/course/mcp/mcp_influx.py'
```

## Reading a test transcript

`-z` prints only the final answer. To see which tools were actually called:

```bash
SID=$(hermes sessions list | awk 'NR==3{print $NF}')
hermes sessions export --format trace --session-id "$SID" --yes -
```

Tools appear under the name `mcp__<server_with_underscores>__<tool>`, e.g.
`mcp__openegiz_ditto__get_feature`.
