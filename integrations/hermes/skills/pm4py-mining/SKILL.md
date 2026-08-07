---
name: pm4py-mining
description: "Process mining on the OpenEgiz stack with pm4py: build an event log (from InfluxDB telemetry or a CSV/XES file) into pandas, discover a Petri net or DFG, check fitness, and render the process map. Includes the ready-made bakery production-line analysis (measurement batch_events -> bottleneck -> parameters for JaamSim). Use for any request to mine, discover or analyse a process, analyse a production line or bakery line, find a bottleneck, build an event log, compute fitness/conformance, or draw a process map."
version: 1.1.0
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [process-mining, pm4py, influxdb, pandas, openegiz]
---

# pm4py on gx10-11

## Environment

pm4py lives in a dedicated venv. **Do not `pip install` into the system
Python and do not `source activate`** — just call the interpreter by path:

```bash
~/course/venv/bin/python your_script.py
```

Installed there: `pm4py`, `pandas`, `influxdb-client`, `paho-mqtt`,
`requests`, `fastmcp`. Graphviz `dot` is on PATH, so process maps render
headless to PNG.

Working end-to-end example to copy from: `~/course/pm4py_check.py` — it builds
a synthetic log, discovers an inductive Petri net, computes token-based-replay
fitness, discovers a DFG and saves a PNG. Read it before writing anything new:

```bash
cat ~/course/pm4py_check.py
```

## The bakery production line — start here if the question is about it

If the user asks about the **bakery**, the **production line**, **batches**, a
**bottleneck** or a **process map of the line**, do not write a new script.
A finished, tested pipeline already exists:

```bash
# compact text report: log shape, DFG, bottleneck, parameter table for JaamSim
~/course/venv/bin/python ~/course/bakery/mining.py --summary

# the same on the deliberately damaged dataset (15% of events dropped)
~/course/venv/bin/python ~/course/bakery/mining.py --summary --mode dirty

# full report incl. every DFG edge, and PNGs into /tmp/bakery-mining/
~/course/venv/bin/python ~/course/bakery/mining.py
```

`--summary` runs in a few seconds and prints everything needed to answer:
number of cases, the directly-follows graph, per-station service vs waiting
time, the bottleneck, and the **PARAMETERS FOR JAAMSIM** table. That table is
the hand-off to the `jaamsim` skill — copy its numbers into the
`PARAMETERS — EDIT HERE` block of `~/course/bakery/jaamsim/BakeryLine.cfg`.

`--range` takes a leading minus, which argparse reads as a flag. Always write
`--range=-24h`, never `--range -24h`.

The teaching notebook with the same analysis and the narrative is
`~/course/bakery/mining.ipynb`; the runbook for the whole loop is
`docs/runbook-bakery-scenario.md` in the repo.

### Where the data is, and the three ways to get it wrong

Measurement `batch_events` in bucket `default`. Tags: `case_id`, `activity`,
`station`, `mode`. Fields: `ts`, `seq`, `queue_len`, `wip`.

| Trap | Why it is fatal | What to do |
|---|---|---|
| `_time` vs `ts` | `_time` is *ingestion* time; the line was replayed at 200x speed, so every duration comes out 200x too short. `ts` is *process* time. | timestamp column = `ts` |
| simultaneous events | `MixingDone` and `ProofingStarted` share a second by design, so the order inside a case is arbitrary | sort with a tie-break on field `seq` |
| foreign cases | old smoke-test runs live in the same measurement | keep only `case_id` starting with `batch-` |

One more Flux-level trap: `ts` is a **string** field and `seq`/`queue_len`/`wip`
are floats, and Flux refuses to `pivot()` string and float into one `_value`
column (`schema collision`). Pull them with two queries and join on `_time`.
Both queries are already written in `~/course/bakery/mining.py`
(`FLUX_LOG` / `FLUX_NUM`) — import that module rather than rewriting them:

```python
import sys; sys.path.insert(0, "/home/gx10-11/course/bakery")
import mining
df = mining.load_event_log(time_range="-24h", mode="normal", case_prefix="batch-")
params, arrival = mining.jaamsim_parameters(df)
print(mining.format_parameter_block(params, arrival))
```

Datasets currently in InfluxDB:

| `--mode` | cases | events | what it is |
|---|---|---|---|
| `normal` | `batch-0001`..`batch-0020` | 160 | 20 complete batches, the reference log |
| `dirty` | `batch-0101`..`batch-0110` | 68 | same line, 15% of events never recorded |

The `dirty` run is not a broken copy — it is the point of an exercise. The
same code on it reports the oven wait as 44 min instead of 106 min and the
release interval as 16.4 min instead of 12.8, which flips the business
decision. If asked to compare, run both and say so plainly.

## The event-log contract

pm4py works on a DataFrame with three mandatory columns:

| Column | Meaning |
|---|---|
| `case:concept:name` | Case ID — one process instance (an order, a part, a batch) |
| `concept:name` | Activity name |
| `time:timestamp` | Timezone-aware timestamp |

Then:

```python
log = pm4py.format_dataframe(df, case_id="case:concept:name",
                             activity_key="concept:name",
                             timestamp_key="time:timestamp")
net, im, fm = pm4py.discover_petri_net_inductive(log)
```

## Getting data out of InfluxDB

Helper script, already wired to `~/.config/openegiz-mcp.env` so no token is
needed on the command line:

```bash
~/course/venv/bin/python ~/.hermes/skills/openegiz/pm4py-mining/scripts/influx_to_dataframe.py \
    --thing test:winterschool-1 --hours 24
```

Importable from your own script:

```python
import sys
sys.path.insert(0, "/home/gx10-11/.hermes/skills/openegiz/pm4py-mining/scripts")
from influx_to_dataframe import fetch

df = fetch(thing_id="test:winterschool-1", hours=24)
# columns: time (UTC), thingId, field, value
```

**Be honest about what this data is.** InfluxDB here holds *numeric telemetry
time-series* (`value_temperature_properties_value` and friends), not a process
event log — there are no case IDs and no activities. To mine it you must first
*derive* activities, and you should say so rather than pretending the mining
result is ground truth. Two defensible derivations:

1. **State binning** — turn a numeric signal into discrete states and treat
   each transition as an activity:

   ```python
   import pandas as pd, pm4py
   d = df[df.field == "value_temperature_properties_value"].sort_values("time").copy()
   d["state"] = pd.cut(d.value, [-1e9, 30, 45, 1e9], labels=["cold", "normal", "hot"])
   d = d[d.state != d.state.shift()]              # keep transitions only
   d["case:concept:name"] = d.time.dt.floor("1h").astype(str)   # one case per hour
   d["concept:name"] = d.state.astype(str)
   d["time:timestamp"] = d.time
   log = pm4py.format_dataframe(d, case_id="case:concept:name",
                                activity_key="concept:name",
                                timestamp_key="time:timestamp")
   ```

2. **Use a real event log instead** — the repo's `data-generator/` produces
   process-shaped data, and any CSV/XES the user supplies is read directly:

   ```python
   log = pm4py.read_xes("/path/log.xes")            # XES
   df  = pd.read_csv("/path/log.csv")               # CSV, then format_dataframe
   ```

## Discovery, conformance, rendering

```python
net, im, fm = pm4py.discover_petri_net_inductive(log)   # sound by construction
print(len(net.places), len(net.transitions), len(net.arcs))

fit = pm4py.fitness_token_based_replay(log, net, im, fm)
print(fit)          # look at 'log_fitness' — 1.0 means the model replays every trace

dfg, start, end = pm4py.discover_dfg(log)               # cheaper, more readable

pm4py.save_vis_petri_net(net, im, fm, "/tmp/net.png")   # needs `dot`, works headless
pm4py.save_vis_dfg(dfg, start, end, "/tmp/dfg.png")
```

Other discovery algorithms when inductive mining gives an over-general
"flower" model: `pm4py.discover_petri_net_heuristics(log)`,
`pm4py.discover_petri_net_alpha(log)`.

## Reporting results

State the case count, activity count and variant count before interpreting
anything — a log with 4 cases supports no conclusions, and saying so is part
of the answer. Useful one-liners:

```python
print("cases:", log["case:concept:name"].nunique(),
      "activities:", log["concept:name"].nunique(),
      "events:", len(log))
print(pm4py.get_variants(log).keys())
```

Write scripts to `/tmp/` and PNGs to `/tmp/` — do not litter `~/course/`.
