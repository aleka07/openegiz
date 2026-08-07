# Course tools on gx10-11 — pm4py + JaamSim

Two analysis tools used by the course loop, installed **outside** the k3s cluster.
Nothing here touches k3s, Docker, or the OpenEgiz digital-twin stack.

Verified: 2026-08-07 · host `gx10-11` (Ubuntu 24.04, aarch64, Python 3.12.3, OpenJDK 1.8.0_492).

```
~/course/
├── README.md                 # this file
├── requirements.txt          # top-level deps (what we asked for)
├── requirements-frozen.txt   # pip freeze — exact reproducible set
├── pm4py_check.py            # functional smoke test for pm4py
├── venv/                     # Python 3.12 virtualenv
└── jaamsim/
    ├── JaamSim2026-05.jar
    └── models/CourseLine.cfg # minimal source→queue→server→sink model
```

---

## 1. pm4py (process mining, Python)

### Re-setup from scratch

```bash
sudo apt-get install -y python3-venv python3-pip graphviz   # graphviz = the `dot` binary, needed to render process maps
mkdir -p ~/course
python3 -m venv ~/course/venv
~/course/venv/bin/pip install --upgrade pip setuptools wheel
~/course/venv/bin/pip install -r ~/course/requirements.txt
# byte-for-byte reproducible instead:
# ~/course/venv/bin/pip install -r ~/course/requirements-frozen.txt
```

Everything installed from prebuilt aarch64 wheels — no compilation, ~70 s total.

### Versions (2026-08-07)

| Package | Version |
|---|---|
| Python | 3.12.3 |
| pm4py | 2.7.23.3 |
| pandas | 3.0.5 |
| numpy | 2.5.1 |
| scipy | 1.18.0 |
| matplotlib | 3.11.1 |
| jupyterlab | 4.6.2 |
| paho-mqtt | 2.1.0 |
| influxdb-client | 1.50.0 |
| graphviz (python binding) | 0.21 |
| graphviz (system, `dot`) | 2.42.2-9ubuntu0.1 |

`paho-mqtt` and `influxdb-client` are what wire pm4py into the course loop: MQTT for
live event ingestion, InfluxDB for pulling the historical event log the miner runs on.

### Functional check

```bash
~/course/venv/bin/python ~/course/pm4py_check.py
```

Builds a 19-row synthetic event log (4 cases, 7 activities, columns
`case:concept:name` / `concept:name` / `time:timestamp`), then runs inductive miner +
token-based replay + DFG discovery + a PNG export through graphviz.

Expected output (verified):

```
rows=19 cases=4 activities=7
PETRI NET: places=7 transitions=8 arcs=16
initial_marking=['source:1'] final_marking=['sink:1']
visible transitions: ['Backorder', 'Cancel', 'Check Stock', 'Invoice', 'Pack', 'Receive Order', 'Ship']
fitness (token-based replay): {'perc_fit_traces': 100.0, 'average_trace_fitness': 1.0, 'log_fitness': 1.0, ...}
DFG edges=7 start={'Receive Order': 4} end={'Invoice': 3, 'Cancel': 1}
rendered PNG bytes: 44783
PM4PY FUNCTIONAL CHECK OK
```

Fitness 1.0 is the correct answer here — the inductive miner is guaranteed to produce a
model that replays its own input log perfectly. It confirms the pipeline ran end to end,
not that the model is good.

### JupyterLab (optional, for labs)

```bash
~/course/venv/bin/jupyter lab --no-browser --ip=127.0.0.1 --port=8888
# from the student's laptop:  ssh -L 8888:127.0.0.1:8888 gx10-11
```

Bind to `127.0.0.1` and reach it over an SSH tunnel — do not expose the port.

---

## 2. JaamSim (discrete-event simulation, Java)

### Version and source

- **JaamSim 2026-05** (release tag `v2026-05`, published 2026-07-06) — the latest stable.
- URL: <https://github.com/jaamsim/jaamsim/releases/download/v2026-05/JaamSim2026-05.jar>
- sha256: `be8229bbe0a545e1e4a10338aa66dfd3c9e23d933c6f65bc3baa904d6f8fceb9`
- size: 19 533 050 bytes

```bash
mkdir -p ~/course/jaamsim && cd ~/course/jaamsim
curl -sSL -O https://github.com/jaamsim/jaamsim/releases/download/v2026-05/JaamSim2026-05.jar
sha256sum JaamSim2026-05.jar   # must match the hash above
```

### Java choice: the system OpenJDK 8 is enough — nothing was installed

The jar's manifest says `Created-By: 25+36-LTS`, which looks like it needs a modern JDK,
but that is only the JDK that *built* it. The actual class files are **bytecode major
version 52 = Java 8 target**, so the newest JaamSim runs on the stock
`/usr/lib/jvm/java-8-openjdk-arm64` already on the host.

So: **no `openjdk-17-jre-headless` was installed, and `update-alternatives` was not
touched.** Newest JaamSim + existing Java, no system change — the best of both options.

### Headless batch run

```bash
cd ~/course/jaamsim/models
java -jar ~/course/jaamsim/JaamSim2026-05.jar CourseLine.cfg -headless
```

Produces, next to the `.cfg`:

- `CourseLine.rep` — full per-replication report (state times, utilisation, queue-length
  distribution, statistics collector output)
- `CourseLine.dat` — one tab-separated row per replication for the entries in
  `RunOutputList`, plus a final mean ± std row

**Gotcha — the flag is `-headless`, not `-b` or `-batch`.**
`-b` is silently ignored, and `-batch` on its own still constructs the Swing GUI and dies
with `java.awt.HeadlessException: No X11 DISPLAY variable was set`. Only `-headless`
skips the GUI entirely. Both failures exit with **status 0**, so never trust the exit
code — check that the `.rep`/`.dat` files actually appeared.

Verified output from `CourseLine.dat` (3 replications):

```
Scenario Replication [PartStats].SampleAverage/1[min]  [WaitQueue].QueueLengthAverage  [Machine].Utilisation
1        1           2.346238757658468                1.5293214293516755              0.7913585537183333
1        2           2.4753701582103385               1.6793641707416689              0.8029958646016666
1        3           2.594805740438258                1.8251774990700023              0.8140866982783332
1                    2.4721382187690213  0.3088…      1.6779543663877823  0.3675…     0.8028137055327778  0.0282…
```

Sanity check against theory: arrivals are exponential with mean 1 min, service is
uniform on [0.70, 0.90] min, so E[S] = 0.8 min and utilisation should be
ρ = λ·E[S] = 0.8. Measured 0.8028 ± 0.028. The model is genuinely simulating, not
just producing a file.

### The model (`models/CourseLine.cfg`)

Minimal `EntityGenerator → Queue → Server → Statistics → EntitySink` line. Deliberately
carries **no graphics blocks** (no `View`, no `DisplayModel`, no `Position`) — a config
with graphics still loads fine headless, but leaving them out keeps the teaching example
readable. `Simulation PrintReport { TRUE }` is what produces the `.rep` file;
`RunOutputList` is what produces the `.dat` file.

Watch out: an invalid output name in `RunOutputList` is **not** an error. JaamSim writes
the literal expression text into the column instead of a number (we hit this with
`[WaitQueue].TimeAverage`, which does not exist — the real one is
`QueueLengthAverage`). Always eyeball the `.dat` header row against its values.

Bundled examples worth stealing from live inside the jar:

```bash
unzip -l ~/course/jaamsim/JaamSim2026-05.jar 'resources/examples/*'
unzip -p ~/course/jaamsim/JaamSim2026-05.jar 'resources/documents/JaamSim User Manual.pdf' > /tmp/JaamSim-manual.pdf
```

### GUI options for the course

The verification above covers **headless batch only** — model runs, reports, and
parameter sweeps with no display. It does not cover the model editor.

For students who need the GUI (building or editing a model) there are two options:

1. **X11 forwarding** — `ssh -X gx10-11`, then `java -jar ~/course/jaamsim/JaamSim2026-05.jar model.cfg`.
   Requires an X server on the student's own machine: XQuartz on macOS, VcXsrv/X410 on
   Windows, native on Linux. *Not installed or tested by this setup.* JaamSim's 3D view
   is OpenGL, so expect it to be slow or to fall back to software rendering over X11 —
   `-safe_graphics` helps.
2. **Run JaamSim on the laptop.** The jar is the same file, cross-platform, and only
   needs a JRE. This is the recommended path for model authoring; use gx10-11 for
   headless batch runs and replications.
