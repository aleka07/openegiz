---
name: jaamsim
description: "Run discrete-event simulations of the OpenEgiz production line with JaamSim headless on this host, read the .dat/.rep results, and edit model parameters. Use for any request to simulate, run a what-if scenario, change arrival/service rates or replication counts, or report utilisation, queue length or throughput of a simulated line."
version: 1.0.0
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [simulation, digital-twin, discrete-event, jaamsim, openegiz]
---

# JaamSim on gx10-11

JaamSim is a discrete-event simulator. On this host it runs **headless only**,
from a `.cfg` model file, and writes results next to the model as `.dat`
(machine-readable outputs) and `.rep` (full report).

- Jar: `~/course/jaamsim/JaamSim2026-05.jar`
- Models: `~/course/jaamsim/models/`
- Reference model: `~/course/jaamsim/models/CourseLine.cfg` — a minimal
  source → queue → server → sink line (M/U/1).

## The one thing you must know

**JaamSim's exit code is always 0, even when the run failed.** A wrong entity
name in `RunOutputList`, a malformed `.cfg`, a missing `Define` — all exit 0
and quietly leave the previous `.dat` in place. Never report success because
the command "worked".

Always run through the wrapper, which checks that `.dat` and `.rep` were
actually rewritten by this run and then prints the `.dat`:

```bash
bash ~/.hermes/skills/openegiz/jaamsim/scripts/run_jaamsim.sh ~/course/jaamsim/models/CourseLine.cfg
```

Wrapper exit codes: `0` verified fresh output, `2` java failed, `3` java
"succeeded" but produced nothing new — that is a silent model failure, go read
the `.cfg`.

A 10000-minute / 3-replication run of `CourseLine.cfg` takes a few seconds.

## Reading the results

`.dat` is tab-separated:

```
Scenario  Replication  [PartStats].SampleAverage/1[min]  [WaitQueue].QueueLengthAverage  [Machine].Utilisation
1  1  2.346...  1.529...  0.791...
1  2  2.475...  1.679...  0.802...
1  3  2.594...  1.825...  0.814...
1     2.472  0.308  1.677  0.367  0.802  0.028
```

- One row per replication, in the column order of `Simulation RunOutputList`.
- The **last row has no replication number**: it is the summary across
  replications, and each output takes **two** columns there — mean followed by
  standard deviation. Report the mean, and mention the spread when it matters.
- For `CourseLine.cfg` the server (`Machine`) utilisation is ≈ **0.80**, mean
  time in system ≈ 2.5 min, mean queue length ≈ 1.7.

`.rep` is the long human report (per-entity statistics per replication). Grep
it rather than reading it whole:

```bash
grep -i utilisation ~/course/jaamsim/models/CourseLine.rep | head
```

## Changing model parameters (what-if scenarios)

The `.cfg` is plain text with a `Keyword { value }` grammar. Edit it with the
`patch` tool, not with sed — a broken keyword fails silently.

**Never edit the reference model in place.** Copy it first, so the baseline
stays reproducible:

```bash
cp ~/course/jaamsim/models/CourseLine.cfg ~/course/jaamsim/models/CourseLine-faster.cfg
```

Parameters worth touching in `CourseLine.cfg`:

| What | Line | Effect |
|---|---|---|
| Arrival rate | `ArrivalDist Mean { 1 min }` | Smaller mean ⇒ more arrivals ⇒ higher utilisation |
| Service time | `ServiceDist MinValue/MaxValue { 0.70/0.90 min }` | Directly sets the server's load |
| Run length | `Simulation RunDuration { 10000 min }` | Longer ⇒ tighter statistics, slower |
| Replications | `Simulation NumberOfReplications { 3 }` | More ⇒ meaningful stddev in the summary row |
| Seeds | `ArrivalDist RandomSeed { 1 }`, `ServiceDist RandomSeed { 2 }` | Change to get an independent sample |
| Outputs | `Simulation RunOutputList { { … } { … } }` | What ends up as `.dat` columns |

Utilisation is roughly `mean service time / mean interarrival time`
(0.80 min / 1 min ≈ 0.80 here), which is a good sanity check on any result.

**`RunOutputList` is the classic trap.** Each entry is `{ [EntityName].Output }`
and the entity name must match a `Define`d name character for character. A typo
does not raise an error — the run just produces nothing new, and the wrapper
exits 3. When that happens, compare the names in `RunOutputList` against the
`Define` block at the top of the file.

## Connecting a run back to the twin

Simulation results are not written to Ditto or InfluxDB automatically. If the
user wants a simulated value to show up in the digital twin, take the number
from the `.dat` and publish it with the Ditto MCP tool `publish_telemetry`.
