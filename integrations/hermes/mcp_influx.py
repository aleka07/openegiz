#!/usr/bin/env python3
"""MCP server exposing the InfluxDB2 telemetry history of the OpenEgiz stack.

Transport: stdio (spawned by Hermes as a subprocess).

Telemetry that devices publish over MQTT is applied to the Ditto twin and then
forwarded by Telegraf into InfluxDB2, measurement ``mqtt_consumer``:

    measurement  mqtt_consumer
    tag          thingId          e.g. test:winterschool-1
    field        value_<feature>_properties_value   e.g. value_temperature_properties_value

Configuration (env vars; the token normally comes from
~/.config/openegiz-mcp.env which install.sh writes from the k8s secret):
    INFLUX_URL     default http://localhost:30716
    INFLUX_TOKEN   required
    INFLUX_ORG     default opentwins
    INFLUX_BUCKET  default default
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastmcp import FastMCP  # noqa: E402

from _env import load_env_file  # noqa: E402

load_env_file()

INFLUX_URL = os.environ.get("INFLUX_URL", "http://localhost:30716").rstrip("/")
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN", "")
INFLUX_ORG = os.environ.get("INFLUX_ORG", "opentwins")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "default")
MEASUREMENT = os.environ.get("INFLUX_MEASUREMENT", "mqtt_consumer")

MAX_CHARS = 6000
MAX_ROWS = 200

mcp = FastMCP("openegiz-influx")


def _query(flux: str):
    """Run a Flux query, return list of influxdb_client tables."""
    from influxdb_client import InfluxDBClient

    if not INFLUX_TOKEN:
        raise RuntimeError(
            "INFLUX_TOKEN is not set. Expected it in ~/.config/openegiz-mcp.env "
            "(written by integrations/hermes/install.sh from the k8s secret)."
        )
    with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=30_000) as client:
        return client.query_api().query(flux)


def _truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS] + f"\n... [truncated, {len(text)} chars total]"


@mcp.tool
def get_recent_telemetry(thing_id: str, minutes: int = 60) -> str:
    """Get the recent telemetry HISTORY of a digital twin from InfluxDB.

    Use this for questions about the past — "show telemetry for the last 24
    hours", "how did the temperature change", "what was the maximum". For the
    single current value of a twin, use the Ditto get_feature tool instead.

    Args:
        thing_id: Ditto thing ID, e.g. "test:winterschool-1".
        minutes: How far back to look, in minutes. 60 = last hour,
            1440 = last 24 hours, 10080 = last week.

    Returns a compact text table (time, field, value) plus a summary line with
    the point count and the min/max/last of each numeric field. Long results
    are downsampled so they stay readable.
    """
    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{int(minutes)}m)
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")
  |> filter(fn: (r) => r.thingId == "{thing_id}")
  |> keep(columns: ["_time", "_field", "_value"])
  |> sort(columns: ["_time"])
'''
    try:
        tables = _query(flux)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR querying InfluxDB: {exc}"

    rows = []
    for table in tables:
        for rec in table.records:
            rows.append((rec.get_time(), rec.get_field(), rec.get_value()))
    if not rows:
        return (
            f"No telemetry found for thing '{thing_id}' in the last {minutes} minutes "
            f"(bucket={INFLUX_BUCKET}, measurement={MEASUREMENT}). "
            "Either nothing was published in that window, or the thing ID is wrong — "
            "call list_thing_ids to see which IDs actually have data."
        )
    rows.sort(key=lambda r: r[0])

    # Per-field summary over the full window, before any downsampling.
    summary = {}
    for _, field, value in rows:
        if isinstance(value, (int, float)):
            slot = summary.setdefault(field, {"n": 0, "min": value, "max": value, "last": value})
            slot["n"] += 1
            slot["min"] = min(slot["min"], value)
            slot["max"] = max(slot["max"], value)
            slot["last"] = value

    shown = rows
    note = ""
    if len(rows) > MAX_ROWS:
        step = len(rows) // MAX_ROWS + 1
        shown = rows[::step]
        note = f" (downsampled: showing every {step}th record)"

    n_fields = len({f for _, f, _ in rows})
    lines = [
        f"Telemetry for {thing_id}, last {minutes} min.",
        f"{len(rows)} records across {n_fields} field(s){note}. NOTE: one reading "
        "produces several records — a *_value record holding the number and a "
        "*_timestamp record holding the device clock. The number of readings is "
        "the per-field count 'n' in the summary below, not the record count.",
        "",
        "time                      field                                 value",
    ]
    for ts, field, value in shown:
        lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')}  {field:<38}  {value}")
    if summary:
        lines.append("")
        lines.append("summary:")
        for field, s in summary.items():
            lines.append(
                f"  {field}: n={s['n']} min={s['min']} max={s['max']} last={s['last']}"
            )
    return _truncate("\n".join(lines))


@mcp.tool
def list_thing_ids(hours: int = 24) -> str:
    """List which digital twins have actually sent telemetry recently.

    Answers "which devices are reporting" / "what data do we have". This is
    the InfluxDB view: a thing can exist in Ditto but appear here only if it
    published telemetry inside the window.

    Args:
        hours: Look-back window in hours (default 24).
    """
    flux = f'''
import "influxdata/influxdb/schema"
schema.tagValues(
  bucket: "{INFLUX_BUCKET}",
  tag: "thingId",
  predicate: (r) => r._measurement == "{MEASUREMENT}",
  start: -{int(hours)}h,
)
'''
    try:
        tables = _query(flux)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR querying InfluxDB: {exc}"

    ids = [rec.get_value() for table in tables for rec in table.records]
    if not ids:
        return f"No thing has sent telemetry in the last {hours} hours."
    return f"{len(ids)} thing(s) with telemetry in the last {hours}h:\n" + "\n".join(
        f"  {i}" for i in ids
    )


@mcp.tool
def flux_query(query: str) -> str:
    """Run an arbitrary Flux query against InfluxDB (escape hatch).

    Only use this when get_recent_telemetry and list_thing_ids cannot express
    what is needed — for example aggregation windows, joins, or a different
    measurement. Prefer the specific tools; they format results better.

    The bucket is "default", the org is "opentwins", the measurement holding
    telemetry is "mqtt_consumer", the twin identity tag is "thingId", and
    numeric fields are named value_<feature>_properties_value.

    Args:
        query: A complete Flux query, starting with from(bucket: "default").

    Results are truncated to a safe size, so add |> limit(n: 50) yourself for
    anything broad.
    """
    try:
        tables = _query(query)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR running Flux query: {exc}"

    lines = []
    count = 0
    for table in tables:
        for rec in table.records:
            values = {k: v for k, v in rec.values.items() if not k.startswith("result")}
            values.pop("table", None)
            lines.append("  ".join(f"{k}={v}" for k, v in values.items()))
            count += 1
            if count >= MAX_ROWS:
                lines.append(f"... [stopped at {MAX_ROWS} records]")
                break
        if count >= MAX_ROWS:
            break
    if not lines:
        return "Query returned no records."
    return _truncate(f"{count} record(s):\n" + "\n".join(lines))


if __name__ == "__main__":
    mcp.run(show_banner=False)
