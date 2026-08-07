#!/usr/bin/env python3
"""Sanity-check that what landed in InfluxDB is a usable process event log.

Reads measurement `batch_events` straight out of InfluxDB, turns it into a
pm4py event log, discovers the directly-follows graph and prints where the
time actually goes. If the oven is the bottleneck, the ProofingDone ->
BakingStarted edge (batches waiting in front of the oven) dominates.

Run on the host:
    ~/course/venv/bin/python ~/course/bakery/check_log.py
    ~/course/venv/bin/python ~/course/bakery/check_log.py --mode dirty --range -1h

The InfluxDB token comes from $INFLUX_TOKEN, or is read from the k8s secret
`opentwins-influxdb2-auth` — nothing secret is stored in this repo.
"""

import argparse
import os
import subprocess
import sys
import warnings

import pandas as pd
from influxdb_client import InfluxDBClient
from influxdb_client.client.warnings import MissingPivotFunction

# The event-log query deliberately does not pivot (see FLUX_LOG below).
warnings.simplefilter("ignore", MissingPivotFunction)

# Ordering the four stations should be visited in.
ROUTE_ORDER = ["mixer-1", "proofer-1", "oven-1", "packer-1"]


def influx_token():
    tok = os.environ.get("INFLUX_TOKEN")
    if tok:
        return tok
    out = subprocess.run(
        ["kubectl", "get", "secret", "-n", "opentwins",
         "opentwins-influxdb2-auth", "-o",
         "jsonpath={.data.admin-token}"],
        capture_output=True, text=True,
        env={**os.environ, "KUBECONFIG": os.environ.get(
            "KUBECONFIG", "/etc/rancher/k3s/k3s.yaml")})
    if out.returncode != 0:
        sys.exit("cannot read InfluxDB token: set $INFLUX_TOKEN\n" + out.stderr)
    import base64
    return base64.b64decode(out.stdout).decode()


# The string field `ts` and the numeric fields cannot be pivoted together
# (Flux refuses to put string and float in one _value column), so pull them
# with two queries and join on the ingestion timestamp, which is unique per
# event.
FLUX_BASE = '''
from(bucket: "{bucket}")
  |> range(start: {range})
  |> filter(fn: (r) => r._measurement == "batch_events")
  |> filter(fn: (r) => r.mode == "{mode}")
  |> drop(columns: ["_start", "_stop", "_measurement", "host"])
'''

FLUX_LOG = FLUX_BASE + '''
  |> filter(fn: (r) => r._field == "ts")
  |> group()
  |> rename(columns: {{_value: "ts"}})
  |> keep(columns: ["_time", "case_id", "activity", "station", "mode", "ts"])
'''

FLUX_NUM = FLUX_BASE + '''
  |> filter(fn: (r) => r._field == "seq" or r._field == "queue_len"
                    or r._field == "wip")
  |> group(columns: ["case_id", "activity", "station", "mode"])
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> keep(columns: ["_time", "seq", "queue_len", "wip"])
'''


def fetch(args):
    fmt = dict(bucket=args.bucket, range=args.range, mode=args.mode)
    with InfluxDBClient(url=args.url, token=influx_token(),
                        org=args.org, timeout=60_000) as client:
        api = client.query_api()

        def q(flux):
            df = api.query_data_frame(flux.format(**fmt))
            if isinstance(df, list):
                df = pd.concat(df, ignore_index=True)
            return df

        log, nums = q(FLUX_LOG), q(FLUX_NUM)

    if log is None or log.empty:
        sys.exit(f"no batch_events rows for mode={args.mode} in range {args.range}")
    df = log.merge(nums[["_time", "seq", "queue_len", "wip"]], on="_time", how="left")
    if args.case_prefix:
        df = df[df["case_id"].str.startswith(args.case_prefix)]
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:30716")
    p.add_argument("--org", default="opentwins")
    p.add_argument("--bucket", default="default")
    p.add_argument("--range", default="-6h")
    p.add_argument("--mode", default="normal")
    p.add_argument("--case-prefix", default="batch-",
                   help="keep only these cases (drops smoke/test runs)")
    args = p.parse_args()

    df = fetch(args)

    # `ts` is process time (simulated); `_time` is ingestion time. Process
    # mining must use process time. `seq` breaks ties when two events share a
    # second (e.g. MixingDone and ProofingStarted are simultaneous by design).
    df["time:timestamp"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values(["case_id", "time:timestamp", "seq"]).reset_index(drop=True)
    df = df.rename(columns={"case_id": "case:concept:name",
                            "activity": "concept:name",
                            "station": "org:resource"})

    n_cases = df["case:concept:name"].nunique()
    per_case = df.groupby("case:concept:name").size()
    print(f"mode={args.mode}  events={len(df)}  cases={n_cases}")
    print(f"cases: {per_case.index.min()} .. {per_case.index.max()}")
    print(f"events per case: min={per_case.min()} max={per_case.max()} "
          f"mean={per_case.mean():.2f}")
    print(f"complete cases (8 activities): {(per_case == 8).sum()}/{n_cases}")
    print()

    import pm4py
    log = pm4py.format_dataframe(df, case_id="case:concept:name",
                                 activity_key="concept:name",
                                 timestamp_key="time:timestamp")

    dfg, start, end = pm4py.discover_dfg(log)
    print(f"DFG: {len(dfg)} edges, {len(start)} start activities, "
          f"{len(end)} end activities")
    print(f"  start: {dict(start)}")
    print(f"  end:   {dict(end)}")
    print()
    print("Edges by frequency:")
    for (a, b), c in sorted(dfg.items(), key=lambda kv: -kv[1]):
        print(f"  {c:>4}x  {a} -> {b}")
    print()

    perf, _, _ = pm4py.discover_performance_dfg(log)
    print("Edges by mean duration (this is where the time goes):")
    rows = sorted(perf.items(), key=lambda kv: -kv[1]["mean"])
    for (a, b), stats in rows:
        print(f"  {stats['mean'] / 60:8.1f} min  {a} -> {b}")
    print()

    worst = rows[0]
    print(f"Bottleneck by waiting time: {worst[0][0]} -> {worst[0][1]} "
          f"({worst[1]['mean'] / 60:.1f} min mean)")

    # Queue depth is logged on every event, so the bottleneck is also visible
    # without any process mining at all — useful for the business audience.
    print()
    print("Max observed queue length per station:")
    for st in ROUTE_ORDER:
        sub = df[df["org:resource"] == st]
        if not sub.empty:
            print(f"  {st:<10} max queue={int(sub['queue_len'].max()):>3}  "
                  f"mean={sub['queue_len'].mean():.2f}")


if __name__ == "__main__":
    main()
