#!/usr/bin/env python3
"""Run the bakery JaamSim models and print one comparison table.

Baseline vs what-if is the whole point of the exercise, and reading three
.dat files by eye is where mistakes happen — the summary row interleaves
mean and standard deviation, so column 5 is not the fifth output.

    python3 compare_runs.py                       # all three models
    python3 compare_runs.py BakeryLine.cfg        # just one

Runs each model through run_jaamsim.sh, because JaamSim exits 0 even when it
silently produced nothing.
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODELS = ["BakeryLine.cfg", "BakeryLine_TwoOvens.cfg",
                  "BakeryLine_FasterProofing.cfg"]
LABELS = {"BakeryLine": "Baseline (as-is)",
          "BakeryLine_TwoOvens": "What-if 1: second oven",
          "BakeryLine_FasterProofing": "What-if 2: proofing -25%"}

WRAPPER = os.path.expanduser("~/.hermes/skills/openegiz/jaamsim/scripts/run_jaamsim.sh")


def run(cfg):
    if not os.path.exists(WRAPPER):
        sys.exit(f"wrapper not found: {WRAPPER} (deploy the jaamsim skill first)")
    r = subprocess.run(["bash", WRAPPER, cfg], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        sys.exit(f"{os.path.basename(cfg)}: run_jaamsim.sh exited {r.returncode} "
                 "(2 = java failed, 3 = silent model failure — read the .cfg)")


def read_dat(cfg):
    """Return {output_name: (mean, stddev)} from the summary row of the .dat.

    The summary row is the last line and has no replication number; each
    output occupies TWO columns there, mean then standard deviation.
    """
    dat = os.path.splitext(cfg)[0] + ".dat"
    lines = [l.rstrip("\n") for l in open(dat) if l.strip()]
    names = [t for t in lines[0].split("\t") if t.strip()][2:]   # drop Scenario/Replication
    vals = [t for t in lines[-1].split("\t") if t.strip()][1:]   # drop Scenario
    if len(vals) != 2 * len(names):
        sys.exit(f"{dat}: expected {2 * len(names)} summary values, got {len(vals)}. "
                 "Did NumberOfReplications drop to 1? Then there is no summary row.")
    return {n: (float(vals[2 * i]), float(vals[2 * i + 1])) for i, n in enumerate(names)}


def oven_capacity(cfg):
    m = re.search(r"^Oven\s+Capacity\s*\{\s*(\d+)", open(cfg).read(), re.M)
    return int(m.group(1)) if m else 1


def shift_minutes(cfg):
    m = re.search(r"^Simulation\s+RunDuration\s*\{\s*([\d.]+)\s*min", open(cfg).read(), re.M)
    return float(m.group(1)) if m else float("nan")


def main():
    models = sys.argv[1:] or DEFAULT_MODELS
    rows = []
    for m in models:
        cfg = m if os.path.isabs(m) else os.path.join(HERE, m)
        run(cfg)
        d = read_dat(cfg)
        base = os.path.basename(cfg)[:-4]
        cap = oven_capacity(cfg)
        rows.append(dict(
            label=LABELS.get(base, base),
            shift=shift_minutes(cfg),
            thru=d["[Shipped].NumberAdded"],
            lead=d["[LeadTime].SampleAverage/1[min]"],
            oq=d["[OvenQueue].QueueLengthAverage"],
            oqmax=d["[OvenQueue].QueueLengthMaximum"],
            owait=d["[OvenQueue].AverageQueueTime/1[min]"],
            outil=(d["[Oven].UnitsInUseAverage"][0] / cap,
                   d["[Oven].UnitsInUseAverage"][1] / cap),
            pwait=d["[ProoferQueue].AverageQueueTime/1[min]"],
            cap=cap))

    w = max(len(r["label"]) for r in rows) + 2
    print(f"Shift = {rows[0]['shift']:.0f} min, 3 replications. "
          "Mean across replications, +- standard deviation.")
    print()
    hdr = (f"{'scenario':<{w}}{'batches/shift':>15}{'lead time,min':>15}"
           f"{'oven queue':>13}{'oven wait,min':>15}{'oven util':>11}"
           f"{'proof wait,min':>16}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['label']:<{w}}"
              f"{r['thru'][0]:>9.1f} ±{r['thru'][1]:<4.1f}"
              f"{r['lead'][0]:>9.1f} ±{r['lead'][1]:<4.1f}"
              f"{r['oq'][0]:>8.1f} ±{r['oq'][1]:<3.1f}"
              f"{r['owait'][0]:>9.1f} ±{r['owait'][1]:<4.1f}"
              f"{100 * r['outil'][0]:>9.0f}% "
              f"{r['pwait'][0]:>10.1f} ±{r['pwait'][1]:<4.1f}")
    print("-" * len(hdr))
    b = rows[0]
    for r in rows[1:]:
        print(f"{r['label']}: throughput "
              f"{100 * (r['thru'][0] / b['thru'][0] - 1):+.0f}%, "
              f"lead time {100 * (r['lead'][0] / b['lead'][0] - 1):+.0f}%, "
              f"oven wait {100 * (r['owait'][0] / b['owait'][0] - 1):+.0f}%")
    print()
    print("oven util is UnitsInUseAverage divided by the oven Capacity, so it stays")
    print("comparable when the second oven is added. It never reaches 100% because")
    print("the shift starts with an empty line: the first batch reaches the oven")
    print("only after mixing + proofing (~50 min).")


if __name__ == "__main__":
    main()
