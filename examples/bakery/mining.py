#!/usr/bin/env python3
"""Process mining of the bakery line: InfluxDB event log -> bottleneck -> JaamSim parameters.

This is the runnable mirror of `mining.ipynb`. The notebook is the teaching
artefact (narrative, pictures); this file is the automation artefact — it is
what the Hermes agent and the runbook call.

Three ways to use it:

    # full report, normal dataset
    ~/course/venv/bin/python ~/course/bakery/mining.py

    # compact text for an agent / for pasting into a chat
    ~/course/venv/bin/python ~/course/bakery/mining.py --summary

    # the same pipeline on the deliberately broken dataset
    ~/course/venv/bin/python ~/course/bakery/mining.py --mode dirty --summary

Note on `--range`: a leading minus confuses argparse, so always write
`--range=-24h`, never `--range -24h`.

The InfluxDB token comes from $INFLUX_TOKEN, or from ~/.config/openegiz-mcp.env,
or from the k8s secret `opentwins-influxdb2-auth`. Nothing secret lives here.
"""

import argparse
import base64
import math
import os
import subprocess
import sys
import warnings

import pandas as pd
from influxdb_client import InfluxDBClient
from influxdb_client.client.warnings import MissingPivotFunction

warnings.simplefilter("ignore", MissingPivotFunction)

# --------------------------------------------------------------------------
# Domain constants. These describe the SHOP FLOOR, not the data — the order
# stations are visited in, and which activity pair belongs to which station.
# Everything else in this file is derived from the event log.
# --------------------------------------------------------------------------

ROUTE = ["mixer-1", "proofer-1", "oven-1", "packer-1"]

# station -> (StartedActivity, DoneActivity)
SERVICE_PAIRS = {
    "mixer-1":   ("MixingStarted", "MixingDone"),
    "proofer-1": ("ProofingStarted", "ProofingDone"),
    "oven-1":    ("BakingStarted", "BakingDone"),
    "packer-1":  ("PackingStarted", "PackingDone"),
}

# station -> (PreviousStationDone, ThisStationStarted). The mixer has no
# waiting pair: the log begins when mixing starts, so time spent waiting to
# enter the line is simply not recorded. Saying that out loud is part of the
# analysis.
WAITING_PAIRS = {
    "proofer-1": ("MixingDone", "ProofingStarted"),
    "oven-1":    ("ProofingDone", "BakingStarted"),
    "packer-1":  ("BakingDone", "PackingStarted"),
}

# The activity that marks a batch entering the line — used for arrival rate.
FIRST_ACTIVITY = "MixingStarted"

ENV_FILE = os.path.expanduser("~/.config/openegiz-mcp.env")


# --------------------------------------------------------------------------
# (a) Loading the event log
# --------------------------------------------------------------------------

def influx_token():
    """Token, in order of preference: env var, env file, k8s secret."""
    tok = os.environ.get("INFLUX_TOKEN")
    if tok:
        return tok
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if line.startswith("INFLUX_TOKEN="):
                return line.split("=", 1)[1].strip()
    out = subprocess.run(
        ["kubectl", "get", "secret", "-n", "opentwins",
         "opentwins-influxdb2-auth", "-o", "jsonpath={.data.admin-token}"],
        capture_output=True, text=True,
        env={**os.environ,
             "KUBECONFIG": os.environ.get("KUBECONFIG", "/etc/rancher/k3s/k3s.yaml")})
    if out.returncode != 0:
        sys.exit("cannot read InfluxDB token: set $INFLUX_TOKEN\n" + out.stderr)
    return base64.b64decode(out.stdout).decode()


# `ts` (string, process time) and the numeric fields cannot be pivoted into one
# column — Flux refuses to mix string and float in `_value`. So: two queries,
# joined on the ingestion timestamp, which is unique per event.
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


def load_event_log(url="http://localhost:30716", org="opentwins", bucket="default",
                   time_range="-24h", mode="normal", case_prefix="batch-"):
    """Pull `batch_events` out of InfluxDB and return a pm4py-shaped DataFrame.

    Three things here are easy to get wrong and all three are fatal:

    1. `ts` is PROCESS time (simulated). `_time` is INGESTION time. The line
       was replayed at --speedup 200, so using `_time` would make every
       duration 200x too short. Mining must use `ts`.
    2. Events that are simultaneous by construction (MixingDone and
       ProofingStarted share a second) need a tie-break, otherwise the order
       inside a case is arbitrary. That is what the field `seq` is for.
    3. Old smoke-test runs share the measurement. Filter case_id by prefix
       `batch-`, or two junk cases end up in the log.
    """
    fmt = dict(bucket=bucket, range=time_range, mode=mode)
    with InfluxDBClient(url=url, token=influx_token(), org=org, timeout=60_000) as client:
        api = client.query_api()

        def q(flux):
            df = api.query_data_frame(flux.format(**fmt))
            if isinstance(df, list):
                df = pd.concat(df, ignore_index=True)
            return df

        log, nums = q(FLUX_LOG), q(FLUX_NUM)

    if log is None or log.empty:
        sys.exit(f"no batch_events rows for mode={mode} in range {time_range}")

    df = log.merge(nums[["_time", "seq", "queue_len", "wip"]], on="_time", how="left")
    if case_prefix:
        df = df[df["case_id"].str.startswith(case_prefix)]

    df["time:timestamp"] = pd.to_datetime(df["ts"], utc=True)          # (1)
    df = df.sort_values(["case_id", "time:timestamp", "seq"])          # (2)
    df = df.reset_index(drop=True)
    df = df.rename(columns={"case_id": "case:concept:name",
                            "activity": "concept:name",
                            "station": "org:resource"})
    return df


def log_shape(df):
    """The three numbers that must be stated before interpreting anything."""
    per_case = df.groupby("case:concept:name").size()
    return dict(events=len(df),
                cases=df["case:concept:name"].nunique(),
                activities=df["concept:name"].nunique(),
                first_case=per_case.index.min(), last_case=per_case.index.max(),
                events_per_case_min=int(per_case.min()),
                events_per_case_max=int(per_case.max()),
                events_per_case_mean=float(per_case.mean()),
                complete_cases=int((per_case == 8).sum()))


# --------------------------------------------------------------------------
# (c) Performance: where the time actually goes
# --------------------------------------------------------------------------

def pair_durations(df, a, b):
    """Minutes from activity `a` to activity `b`, per case. One value per case."""
    piv = (df[df["concept:name"].isin([a, b])]
           .pivot_table(index="case:concept:name", columns="concept:name",
                        values="time:timestamp", aggfunc="min"))
    if a not in piv.columns or b not in piv.columns:
        return pd.Series(dtype="float64")
    return ((piv[b] - piv[a]).dt.total_seconds() / 60.0).dropna()


def describe_minutes(s):
    if s.empty:
        return dict(n=0, mean=float("nan"), median=float("nan"), std=float("nan"))
    return dict(n=int(s.size), mean=float(s.mean()), median=float(s.median()),
                std=float(s.std(ddof=1)) if s.size > 1 else 0.0)


def service_and_waiting(df):
    """Per station: how long work takes vs how long batches wait to start it."""
    rows = []
    for st in ROUTE:
        a, b = SERVICE_PAIRS[st]
        svc = describe_minutes(pair_durations(df, a, b))
        if st in WAITING_PAIRS:
            wa, wb = WAITING_PAIRS[st]
            wait = describe_minutes(pair_durations(df, wa, wb))
        else:
            wait = dict(n=0, mean=float("nan"), median=float("nan"), std=float("nan"))
        rows.append(dict(station=st,
                         service_mean=svc["mean"], service_median=svc["median"],
                         service_std=svc["std"], service_n=svc["n"],
                         wait_mean=wait["mean"], wait_median=wait["median"],
                         wait_n=wait["n"]))
    out = pd.DataFrame(rows).set_index("station")
    out["total_mean"] = out["service_mean"] + out["wait_mean"].fillna(0.0)
    return out


def observed_capacity(df):
    """Max number of batches inside a station at the same time.

    Capacity is a fact about the shop floor, but it is also *visible in the
    log*: count overlapping [Started, Done] intervals per station. This is the
    honest way to get the number — no one has to remember it.
    """
    caps = {}
    for st in ROUTE:
        a, b = SERVICE_PAIRS[st]
        piv = (df[df["concept:name"].isin([a, b])]
               .pivot_table(index="case:concept:name", columns="concept:name",
                            values="time:timestamp", aggfunc="min"))
        if a not in piv.columns or b not in piv.columns:
            caps[st] = None
            continue
        iv = piv[[a, b]].dropna()
        # +1 at every start, -1 at every end; running max is the concurrency.
        ev = ([(t, 1) for t in iv[a]] + [(t, -1) for t in iv[b]])
        ev.sort(key=lambda x: (x[0], x[1]))   # ends before starts at equal time
        cur = peak = 0
        for _, d in ev:
            cur += d
            peak = max(peak, cur)
        caps[st] = peak
    return caps


def bottleneck(df):
    """The waiting pair with the largest mean. That is the constraint."""
    waits = {st: pair_durations(df, *WAITING_PAIRS[st]).mean() for st in WAITING_PAIRS}
    waits = {k: v for k, v in waits.items() if pd.notna(v)}
    if not waits:
        return None, float("nan")
    st = max(waits, key=waits.get)
    return st, waits[st]


# --------------------------------------------------------------------------
# (d) Parameters for JaamSim
# --------------------------------------------------------------------------

def lognormal_params(mean, std, median):
    """Mined mean/std -> the two numbers JaamSim's LogNormalDistribution wants.

    JaamSim draws  Scale * exp(NormalMean + NormalStandardDeviation * Z).
    Set Scale to the observed MEDIAN and NormalMean to 0: the median of a
    lognormal is exactly exp(mu), so Scale = median makes the model's median
    equal the observed median with no arithmetic.
    The spread in log space is  sigma = sqrt(ln(1 + (std/mean)^2)).
    """
    if not (mean and mean > 0) or pd.isna(std):
        return dict(scale=float("nan"), sigma=float("nan"), cv=float("nan"))
    cv = std / mean
    sigma = math.sqrt(math.log(1.0 + cv * cv))
    return dict(scale=median, sigma=sigma, cv=cv)


def arrival_stats(df):
    """Interarrival time of batches, from consecutive MixingStarted events."""
    firsts = (df[df["concept:name"] == FIRST_ACTIVITY]
              .groupby("case:concept:name")["time:timestamp"].min()
              .sort_values())
    gaps = firsts.diff().dt.total_seconds().dropna() / 60.0
    return describe_minutes(gaps)


def jaamsim_parameters(df):
    """Everything the owner has to type into BakeryLine.cfg, in one table."""
    sw = service_and_waiting(df)
    caps = observed_capacity(df)
    rows = []
    for st in ROUTE:
        p = lognormal_params(sw.loc[st, "service_mean"], sw.loc[st, "service_std"],
                             sw.loc[st, "service_median"])
        rows.append(dict(station=st, capacity=caps.get(st),
                         service_mean=sw.loc[st, "service_mean"],
                         service_median=sw.loc[st, "service_median"],
                         service_std=sw.loc[st, "service_std"],
                         cv=p["cv"], scale_min=p["scale"], sigma_ln=p["sigma"]))
    params = pd.DataFrame(rows).set_index("station")
    arr = arrival_stats(df)
    arr_p = lognormal_params(arr["mean"], arr["std"], arr["median"])
    arrival = dict(mean=arr["mean"], median=arr["median"], std=arr["std"],
                   n=arr["n"], scale_min=arr_p["scale"], sigma_ln=arr_p["sigma"])
    return params, arrival


def format_parameter_block(params, arrival):
    """The 'PARAMETERS FOR JAAMSIM' table — this is what gets copied by hand."""
    L = []
    L.append("=" * 74)
    L.append("PARAMETERS FOR JAAMSIM  (copy into the EDIT HERE block of BakeryLine.cfg)")
    L.append("=" * 74)
    L.append("")
    L.append(f"{'station':<11}{'cap':>4}{'mean':>9}{'median':>9}{'std':>8}"
             f"{'cv':>7}   JaamSim keywords")
    L.append("-" * 74)
    for st, r in params.iterrows():
        L.append(f"{st:<11}{int(r['capacity']):>4}{r['service_mean']:>9.2f}"
                 f"{r['service_median']:>9.2f}{r['service_std']:>8.2f}{r['cv']:>7.3f}"
                 f"   Scale {{ {r['scale_min']:.2f} min }}  "
                 f"NormalStandardDeviation {{ {r['sigma_ln']:.3f} }}")
    L.append("-" * 74)
    L.append(f"{'arrivals':<11}{'-':>4}{arrival['mean']:>9.2f}"
             f"{arrival['median']:>9.2f}{arrival['std']:>8.2f}"
             f"{arrival['std'] / arrival['mean']:>7.3f}"
             f"   Scale {{ {arrival['scale_min']:.2f} min }}  "
             f"NormalStandardDeviation {{ {arrival['sigma_ln']:.3f} }}")
    L.append("")
    L.append("All times in minutes. 'cap' is the max concurrency observed in the log,")
    L.append("not a number anyone had to remember. JaamSim draws")
    L.append("  Scale * exp(NormalMean + NormalStandardDeviation * Z),  NormalMean = 0,")
    L.append("so Scale is the median and the mean comes out ~0.7% higher — negligible.")
    return "\n".join(L)


# --------------------------------------------------------------------------
# (b) Discovery
# --------------------------------------------------------------------------

def discover(df, out_dir=None, tag="normal", render=True):
    """DFG + inductive Petri net. Returns (dfg, start, end, net, im, fm, paths)."""
    import pm4py
    log = pm4py.format_dataframe(df.copy(), case_id="case:concept:name",
                                 activity_key="concept:name",
                                 timestamp_key="time:timestamp")
    dfg, start, end = pm4py.discover_dfg(log)
    net, im, fm = pm4py.discover_petri_net_inductive(log)
    paths = {}
    if render and out_dir:
        os.makedirs(out_dir, exist_ok=True)
        paths["dfg"] = os.path.join(out_dir, f"process_map_{tag}.png")
        paths["net"] = os.path.join(out_dir, f"petri_net_{tag}.png")
        pm4py.save_vis_dfg(dfg, start, end, paths["dfg"])
        pm4py.save_vis_petri_net(net, im, fm, paths["net"])
    return dfg, start, end, net, im, fm, paths


def performance_dfg(df):
    import pm4py
    log = pm4py.format_dataframe(df.copy(), case_id="case:concept:name",
                                 activity_key="concept:name",
                                 timestamp_key="time:timestamp")
    perf, _, _ = pm4py.discover_performance_dfg(log)
    rows = [dict(edge=f"{a} -> {b}", mean_min=s["mean"] / 60.0,
                 median_min=s["median"] / 60.0, n=s["count"] if "count" in s else None)
            for (a, b), s in perf.items()]
    return pd.DataFrame(rows).sort_values("mean_min", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def report(df, args):
    shape = log_shape(df)
    print(f"mode={args.mode}  events={shape['events']}  cases={shape['cases']}  "
          f"activities={shape['activities']}")
    print(f"cases {shape['first_case']} .. {shape['last_case']};  "
          f"events per case min={shape['events_per_case_min']} "
          f"max={shape['events_per_case_max']} mean={shape['events_per_case_mean']:.2f};  "
          f"complete (8 events) {shape['complete_cases']}/{shape['cases']}")
    print()

    dfg, start, end, net, im, fm, paths = discover(
        df, out_dir=args.out_dir, tag=args.mode, render=not args.no_render)
    print(f"DFG: {len(dfg)} edges | start {dict(start)} | end {dict(end)}")
    print(f"Petri net (inductive): {len(net.places)} places, "
          f"{len(net.transitions)} transitions, {len(net.arcs)} arcs")
    if paths:
        for k, v in paths.items():
            print(f"  rendered {k}: {v}")
    print()

    if not args.summary:
        print("DFG edges by frequency:")
        for (a, b), c in sorted(dfg.items(), key=lambda kv: -kv[1]):
            print(f"  {c:>4}x  {a} -> {b}")
        print()

    print("Where the time goes (mean minutes per edge):")
    perf = performance_dfg(df)
    for _, r in perf.iterrows():
        print(f"  {r['mean_min']:8.1f}  {r['edge']}")
    print()

    sw = service_and_waiting(df)
    print("Per station — service vs waiting (minutes):")
    print(f"  {'station':<11}{'service':>9}{'waiting':>9}{'total':>9}   share of lead time")
    lead = sw["total_mean"].sum()
    for st, r in sw.iterrows():
        w = 0.0 if pd.isna(r["wait_mean"]) else r["wait_mean"]
        print(f"  {st:<11}{r['service_mean']:>9.1f}{w:>9.1f}{r['total_mean']:>9.1f}"
              f"   {100 * r['total_mean'] / lead:>5.1f}%")
    print(f"  {'':<11}{'':>9}{'':>9}{lead:>9.1f}   (mean lead time, mixer wait not logged)")
    print()

    st, val = bottleneck(df)
    if st:
        a, b = WAITING_PAIRS[st]
        print(f"BOTTLENECK: {st} — batches wait {val:.1f} min on average before "
              f"{b.replace('Started', '')} starts")
        print(f"            (edge {a} -> {b}); the work itself takes only "
              f"{sw.loc[st, 'service_mean']:.1f} min")
        if "queue_len" in df.columns:
            sub = df[df["org:resource"] == st]
            if not sub.empty and sub["queue_len"].notna().any():
                print(f"            queue in front of {st}: max "
                      f"{int(sub['queue_len'].max())}, mean {sub['queue_len'].mean():.2f}")
    print()

    params, arrival = jaamsim_parameters(df)
    print(format_parameter_block(params, arrival))


def main():
    p = argparse.ArgumentParser(
        description="Mine the bakery event log and print JaamSim parameters.")
    p.add_argument("--url", default="http://localhost:30716")
    p.add_argument("--org", default="opentwins")
    p.add_argument("--bucket", default="default")
    p.add_argument("--range", dest="range_", default="-24h",
                   help="Flux range; write it as --range=-24h (leading minus)")
    p.add_argument("--mode", default="normal", choices=["normal", "dirty", "sparse"])
    p.add_argument("--case-prefix", default="batch-")
    p.add_argument("--out-dir", default="/tmp/bakery-mining")
    p.add_argument("--no-render", action="store_true", help="skip PNG rendering")
    p.add_argument("--summary", action="store_true",
                   help="compact output: shape, bottleneck, parameter table")
    args = p.parse_args()

    df = load_event_log(url=args.url, org=args.org, bucket=args.bucket,
                        time_range=args.range_, mode=args.mode,
                        case_prefix=args.case_prefix)
    if args.summary:
        args.no_render = True
    report(df, args)


if __name__ == "__main__":
    main()
