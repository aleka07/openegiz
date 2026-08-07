#!/usr/bin/env python3
"""Pull OpenEgiz telemetry out of InfluxDB2 into a tidy pandas DataFrame.

Run with the course venv:
    ~/course/venv/bin/python influx_to_dataframe.py [--thing test:winterschool-1] [--hours 24]

Reads INFLUX_* config from ~/.config/openegiz-mcp.env (same file the MCP
servers use), so no token ever has to be pasted on the command line.

Importable too:
    from influx_to_dataframe import fetch
    df = fetch(thing_id="test:winterschool-1", hours=24)
    # columns: time (UTC), thingId, field, value
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
from influxdb_client import InfluxDBClient

ENV_FILE = Path(os.environ.get("OPENEGIZ_ENV_FILE", "~/.config/openegiz-mcp.env")).expanduser()


def _load_env() -> None:
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def fetch(thing_id: str | None = None, hours: int = 24, measurement: str = "mqtt_consumer") -> pd.DataFrame:
    """Return telemetry as a DataFrame with columns time, thingId, field, value."""
    _load_env()
    url = os.environ.get("INFLUX_URL", "http://localhost:30716")
    token = os.environ["INFLUX_TOKEN"]
    org = os.environ.get("INFLUX_ORG", "opentwins")
    bucket = os.environ.get("INFLUX_BUCKET", "default")

    thing_filter = f'\n  |> filter(fn: (r) => r.thingId == "{thing_id}")' if thing_id else ""
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: -{int(hours)}h)
  |> filter(fn: (r) => r._measurement == "{measurement}"){thing_filter}
  |> keep(columns: ["_time", "thingId", "_field", "_value"])
  |> sort(columns: ["_time"])
'''
    rows = []
    with InfluxDBClient(url=url, token=token, org=org, timeout=60_000) as client:
        for table in client.query_api().query(flux):
            for rec in table.records:
                rows.append(
                    {
                        "time": rec.get_time(),
                        "thingId": rec.values.get("thingId"),
                        "field": rec.get_field(),
                        "value": rec.get_value(),
                    }
                )
    return pd.DataFrame(rows, columns=["time", "thingId", "field", "value"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--thing", default=None, help="Ditto thing ID, e.g. test:winterschool-1")
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args()

    df = fetch(args.thing, args.hours)
    print(f"rows={len(df)}")
    if not df.empty:
        print(df.head(20).to_string(index=False))
        print("\nfields:", sorted(df["field"].unique()))
        print("things:", sorted(x for x in df["thingId"].unique() if x))
