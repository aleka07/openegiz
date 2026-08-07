---
name: pm4py-mining
description: "Process mining on the OpenEgiz stack with pm4py: build an event log (from InfluxDB telemetry or a CSV/XES file) into pandas, discover a Petri net or DFG, check fitness, and render the process map. Use for any request to mine, discover or analyse a process, build an event log, compute fitness/conformance, or draw a process map."
version: 1.0.0
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
