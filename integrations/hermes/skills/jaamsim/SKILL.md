---
name: jaamsim
description: "Run discrete-event simulations of the OpenEgiz production line with JaamSim headless on this host, read the .dat/.rep results, and edit model parameters. Includes the ready-made bakery line models (baseline, second oven, faster proofing) and a one-command comparison. Use for any request to simulate, run a what-if scenario, evaluate buying equipment or adding capacity, change arrival/service rates or replication counts, or report utilisation, queue length, lead time or throughput of a simulated line."
version: 1.1.0
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

## The bakery line — start here if the question is about it

If the user asks about the **bakery**, the **production line**, a **second
oven**, **faster proofing**, or any what-if on throughput or lead time, the
models already exist in `~/course/bakery/jaamsim/`. Do not build a new one.

**First, though: if the request also mentions the event log, the process, the
bottleneck, or "analyse", run the mining step before simulating.**

```bash
~/course/venv/bin/python ~/course/bakery/mining.py --summary
```

This is not optional politeness — the parameters in the `.cfg` files are a
*snapshot* of an earlier mining run, quoted in the header comment. Simulating
without re-mining answers "what would happen if the line still behaved the way
it did last time", which is a different question and a weaker answer. The
mining step also produces the one number the simulation cannot: the **measured**
106.5-minute wait in front of the oven in the real log. Report the measurement
and the simulation side by side; if they disagree, say so.

The `pm4py-mining` skill documents that command in full.

| File | What it is |
|---|---|
| `BakeryLine.cfg` | baseline, the line as it runs today |
| `BakeryLine_TwoOvens.cfg` | what-if 1: `Oven Capacity` 1 → 2, one line changed |
| `BakeryLine_FasterProofing.cfg` | what-if 2: `ProoferDist Scale` 38.99 → 29.24 min (−25%), one line changed |
| `BakeryLine_Calibration.cfg` | not a scenario: baseline cut to the 250-min window the mined log covers, used to check the model against reality |

**Run all three and get the comparison table in one command:**

```bash
python3 ~/course/bakery/jaamsim/compare_runs.py
```

It calls `run_jaamsim.sh` for each model (so a silent failure still fails
loudly), parses the summary rows, and prints throughput per shift, lead time,
oven queue, oven waiting time and oven utilisation side by side, plus the
percentage change against the baseline. Prefer it over reading three `.dat`
files by hand — the summary row interleaves mean and standard deviation, so
"the fifth number" is not the fifth output.

To run a single model:

```bash
bash ~/.hermes/skills/openegiz/jaamsim/scripts/run_jaamsim.sh \
     ~/course/bakery/jaamsim/BakeryLine.cfg
```

### The model, in one paragraph

`Launch` (EntityGenerator, lognormal interarrival) → `MixerQueue`/`Mixer` →
`ProoferQueue`/`Proofer` → `OvenQueue`/`Oven` → `PackerQueue`/`Packer` →
`LeadTime` (Statistics) → `Shipped` (EntitySink). Each station is an
`EntityProcessor` — unlike `Server` it has a `Capacity` keyword, which is what
lets the proofer hold 3 batches at once. Shift = 540 min, 3 replications.

### Editing the parameter block

Every model has one block marked `PARAMETERS — EDIT HERE (from mining)` near
the top. Nothing outside it should ever be touched. Its numbers come from
`~/course/bakery/mining.py --summary`, table "PARAMETERS FOR JAAMSIM".

```
ArrivalDist Scale                   { 12.53 min }   # median interarrival
ArrivalDist NormalStandardDeviation { 0.133 }       # spread in log space
Oven     Capacity                { 1 }              # batches at once
OvenDist Scale                   { 24.93 min }      # median bake time
OvenDist NormalStandardDeviation { 0.153 }
Simulation RunDuration          { 540 min }         # one shift
Simulation NumberOfReplications { 3 }
```

`NormalMean` is 0 in every distribution, so **`Scale` is the median** duration
and the mean lands ~0.7% higher. Take `Scale` straight from the `median`
column of the mining table; do not convert anything.

To build a new what-if: copy `BakeryLine.cfg`, change **one** line in the
parameter block, and keep the random seeds — then any difference in the result
is caused by that one change and nothing else.

### The expected answer

The line launches a batch every ~12.5 min; the oven needs ~25 min and holds
one. That is the whole story: the oven can pass at most half of what is
launched, so the queue in front of it grows for as long as the shift runs.
A second oven roughly doubles throughput; making proofing faster changes
throughput by a few percent and makes the oven queue slightly *worse*, because
batches reach the constraint sooner. If a run contradicts that, suspect the
run, not the arithmetic.

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
