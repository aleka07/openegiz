# OpenEgiz

<p align="center">
  <img src="docs/img/logo-readme.svg" alt="OpenEgiz logo" width="420">
</p>

*Русская версия: [README.ru.md](README.ru.md)*

An open-source digital twin platform for industry: live twin state (Eclipse Ditto), telemetry (MQTT → Telegraf → InfluxDB), dashboards and a twin management UI (Grafana), 3D visualization (Unity WebGL).

It runs two ways, both complete:

- **Docker Compose** — one command on a laptop, in CI, or on a contest judge machine. Start here.
- **Helm on k3s** — the server path, used on our ARM64 lab host.

Based on [OpenTwins](https://github.com/ertis-research/opentwins) by ERTIS Research (University of Málaga). This fork adds the Compose deployment with an end-to-end smoke test, ARM64 support, vendored Grafana plugins (no runtime dependency on upstream releases), stability fixes, and the [Example Mine](examples/mine/).

**If OpenEgiz is useful to you, please ⭐ star the repository** — it is how other people and companies find the project.

## Quick start (Docker Compose)

**You need:** Docker with Compose v2.20+ (Docker Desktop on macOS/Windows, Docker Engine on Linux), `git`, `make`, and **6 GB of memory for Docker** (the stack uses about 3.2 GB). amd64 and arm64 both work. On Ubuntu/Debian, `make` is not installed by default: `sudo apt install make`. On Windows, run everything inside WSL2 — first do the [Windows setup](#windows-wsl2).

```bash
git clone https://github.com/aleka07/openegiz.git
cd openegiz
make up
```

The first run generates credentials, downloads about 2.3 GB of images and builds one image from source, so give it a few minutes; later starts take under a minute. When it finishes it prints the URLs and logins:

```text
  Grafana        http://localhost:3000        admin / <generated>
  Ditto API      http://localhost:8080/api/2  ditto / <generated>
  ...
```

Then put a small digital mine on top and check that everything works end to end:

```bash
make example-mine   # twins, a haul-cycle simulator and a Grafana dashboard
make smoke          # end-to-end check: MQTT -> Ditto -> Telegraf -> InfluxDB -> Grafana
```

Open Grafana → **Dashboards → OpenEgiz Examples → Example Mine**. The twins are listed in the **OpenEgiz** app → **Twins**. What the example contains and how its data flows: [examples/mine/](examples/mine/).

| Command | What it does |
|---|---|
| `make up` | Start the platform (first run: generate credentials into `deploy/compose/.env`) |
| `make example-mine` | Start the platform plus the Example Mine; from then on `make up` / `make down` include the mine too |
| `make example-mine-stop` | Stop the mine simulator; twins and data stay |
| `make smoke` | End-to-end check of the running stack |
| `make ps` / `make logs S=<service>` | Service status / follow logs |
| `make generate-data` | Oven demo: two oven twins with simulated telemetry ([examples/oven/](examples/oven/)) |
| `make down` | Stop, keep data |
| `make clean` | Stop and **delete all data and credentials** |

Credentials are generated once per checkout and live in `deploy/compose/.env` (git-ignored). There are no default passwords. Ports are bound to `127.0.0.1` only.

### Windows (WSL2)

OpenEgiz runs inside a Linux distribution under WSL2, not in PowerShell. Tested on Windows 11 24H2 with Docker Desktop 28 and WSL 2.4.

1. Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) with the WSL 2 backend and start it.
2. In PowerShell, install Ubuntu 24.04 and make it the default WSL distribution:

   ```powershell
   wsl --update
   wsl --install -d Ubuntu-24.04
   wsl --set-default Ubuntu-24.04
   ```

   Name `Ubuntu-24.04` exactly: plain `Ubuntu` now installs 26.04, which did not start on WSL 2.4 in our test. On first start Ubuntu asks you to create a Linux user.

   `--set-default` matters: Docker Desktop connects to the *default* WSL distribution, and out of the box that is its own internal `docker-desktop`. Instead you can enable Ubuntu-24.04 in Docker Desktop → Settings → Resources → WSL integration.
3. Open **Ubuntu 24.04** from the Start menu, check that `docker version` works, and install `make`:

   ```bash
   sudo apt update && sudo apt install -y make
   ```

4. Follow the quick start above in that Ubuntu terminal. Clone into your Linux home directory (`cd ~` first), not under `/mnt/c`: files on the Windows side are much slower to reach from WSL.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `Docker is not running` | Start Docker Desktop, or `sudo systemctl start docker` on Linux |
| `make: command not found` | `sudo apt install make` (Ubuntu/Debian) |
| Windows: `docker: command not found` inside Ubuntu | Docker Desktop is not connected to this distribution: `wsl --set-default Ubuntu-24.04` in PowerShell, or Docker Desktop → Settings → Resources → WSL integration. See [Windows (WSL2)](#windows-wsl2) |
| `Ports already in use: MQTT_PORT=1883` (or another) | Something else holds the port (often a local Mosquitto). Stop it, or change the port in `deploy/compose/.env` and run `make up` again |
| `Docker has N GiB of memory` warning, containers restarting | Give Docker 6 GB: Docker Desktop → Settings → Resources |
| `Docker Compose ... is too old` | Update Docker; the `docker-compose` v1 binary is not supported |
| `make up` fails on the init job | `make logs S=init`; usually Ditto was still starting — run `make up` again |
| Anything else | `make ps`, then `make logs S=<service>`; `make clean && make up` starts from scratch |

## Build your own twins

A twin is a [Ditto thing](https://eclipse.dev/ditto/basic-thing.html). Create it in Grafana (**OpenEgiz** app → **Twins** → **New twin**, policy `default:basic_policy`) or with one HTTP call — [examples/mine/twins.json](examples/mine/twins.json) and [setup_twins.py](examples/mine/setup_twins.py) show both the shape and the call.

Send telemetry as [Ditto protocol](https://eclipse.dev/ditto/protocol-overview.html) messages to any MQTT topic under `telemetry/` (by convention `telemetry/<thing-name>`), anonymous MQTT on `localhost:1883`:

```json
{
  "topic": "org.openegiz.mine/truck-01/things/twin/commands/modify",
  "path": "/features",
  "value": {
    "payload": { "properties": { "value": 92.5, "unit": "t" } },
    "speed":   { "properties": { "value": 31.0, "unit": "km/h" } }
  }
}
```

Use exactly this shape — `modify` on `/features` with every feature of the twin. It replaces all features, so send them all each time. A narrower path (for example `/features/payload/properties/value`) updates Ditto too, but Telegraf then stores the number in a field called just `value`, without the feature name, and dashboards cannot tell features apart.

Ditto updates the twin and republishes the change; Telegraf writes it to InfluxDB (bucket `default`, measurement `mqtt_consumer`, field `value_<feature>_properties_value`, tag `thingId`); Grafana reads it from there. Telegraf flushes every 10 s, so new points appear with that delay. [examples/mine/simulator.py](examples/mine/simulator.py) is a complete, small publisher to copy from.

## 3D: Unity WebGL contract

3D is optional. The vendored **Unity** Grafana panel runs a Unity WebGL build inside a dashboard, sends it twin data and can send events back. This is what a build has to do.

**Build.** Target WebGL with *Player Settings → Publishing Settings → Compression Format* = **Disabled**. The panel loads exactly four files: `*.loader.js`, `*.framework.js`, `*.data`, `*.wasm` — `.gz`, `.br` and `.unityweb` builds will not load (the server sends no `Content-Encoding`). Avoid spaces in the build name, or write them as `%20` in URLs. Set `WebGLInput.captureAllKeyboardInput = false;` in an always-active script, otherwise the build swallows the dashboard's keyboard input.

**Serve it.**

| | Compose | Helm |
|---|---|---|
| Put the files | into `build/` (or `make copy-build SRC=<Unity output dir>`); served immediately | `make copy-build SRC=…`, then `make upload-build` |
| File URL | `http://localhost:8090/build/<file>` | `http://<node-ip>:30530/build/<file>` |
| After a restart | still there | gone (`emptyDir`) — upload again |

Link each file directly: `/build/` itself has no index and returns 403. The viewer's browser fetches these URLs, so the host must be reachable from it.

**Configure the panel.** In a dashboard, add a visualization of type **Unity**:

1. **Unity model** → Mode `External links`, paste the four file URLs.
2. Add a query that returns one row per twin with a `thingId` column, for example:

   ```flux
   import "types"

   from(bucket: "default")
   |> range(start: -1m)
   |> filter(fn: (r) => r["_measurement"] == "mqtt_consumer" and r["_field"] =~ /_properties_value$/)
   |> filter(fn: (r) => types.isNumeric(v: r._value))
   |> group(columns: ["thingId", "_field"])
   |> last()
   |> group(columns: ["thingId"])
   |> pivot(rowKey: ["thingId"], columnKey: ["_field"], valueColumn: "_value")
   ```

   Text values (such as a truck's `state`) cannot share a pivot with numbers; fetch them in a second query of the same shape with `types.isType(v: r._value, type: "string")`.

3. **Send data to Unity** → Mode `Send data to GameObjects by ID column`, ID column `thingId`, Unity function `SetValues`.

**Grafana → Unity.** For every distinct `thingId` the panel calls `SendMessage(<thingId>, "SetValues", json)`: the **active** GameObject named exactly like the twin receives one `string` argument:

```text
{"series": {"value_temperature_properties_value": 182.5, "value_power_kw_properties_value": 3.2}}
```

The `thingId` key is removed. When a twin has several rows with overlapping columns, `series` is an array of row objects instead of one object — handle both. Messages are re-sent with the full state on every dashboard refresh, not in panel edit mode. A missing GameObject or method fails silently (only the browser console shows it). `JsonUtility` cannot read dynamic keys; use Newtonsoft JSON.

```csharp
public class TwinReceiver : MonoBehaviour {   // on a GameObject named "org.openegiz:oven-01"
    public void SetValues(string json) { /* parse {"series": ...} */ }
}
```

**Unity → Grafana.** Under **Receive data from Unity**, map an event name to an existing dashboard variable (a textbox variable is easiest). When the build fires the event, the panel sets `var-<variable>` to its first argument, so clicking a 3D object can filter the rest of the dashboard:

```js
// Assets/Plugins/WebGL/Grafana.jslib
mergeInto(LibraryManager.library, {
  SelectTwin: function (id) { window.dispatchReactUnityEvent("SelectTwin", UTF8ToString(id)); }
});
```

```csharp
[DllImport("__Internal")] static extern void SelectTwin(string id);   // panel event name: SelectTwin
```

Known panel quirks: the "Grafana query" selector is ignored (frames from all the panel's queries are sent), and the `Drag and drop` model mode does not work — use `External links`.

## Server deployment (Helm on k3s)

The same platform as a Helm chart, for a long-running server. Verified on single-node [k3s](https://k3s.io) v1.36, Ubuntu 24.04, arm64 (NVIDIA GB10 / ASUS Ascent GX10). amd64 on Helm is not verified yet — on amd64, prefer Compose.

On a clean aarch64 Ubuntu host, [`bootstrap.sh`](bootstrap.sh) does the whole path — k3s + Helm, the arm64 `ditto-extended-api` image, the Helm release, and a post-install smoke test — in one idempotent run:

```bash
# 1. put the repo on the host and create the credentials file
mkdir -p ~/openegiz-deploy
cp secrets.values.yaml.example ~/openegiz-deploy/secrets.values.yaml
chmod 600 ~/openegiz-deploy/secrets.values.yaml
$EDITOR ~/openegiz-deploy/secrets.values.yaml   # replace every CHANGE_ME
                                                # openssl rand -base64 18

# 2. run it from the repo checkout, on the host
bash bootstrap.sh
```

Optional extras, both off by default: `--with-course-tools` (pm4py venv + JaamSim, see [docs/notes-course-tools.md](docs/notes-course-tools.md)) and `--with-bakery` (the bakery twins from [examples/bakery/](examples/bakery/)). Hermes is installed separately — [integrations/hermes/install.sh](integrations/hermes/install.sh).

> [!IMPORTANT]
> `values.yaml` ships deliberately **invalid** placeholders for every credential. [`secrets.values.yaml.example`](secrets.values.yaml.example) lists the keys a fresh install needs; the filled-in copy lives at `~/openegiz-deploy/secrets.values.yaml` (chmod 600) and is never committed. Every helm command must be given it with `-f`.

> [!WARNING]
> `bootstrap.sh` has **not yet been executed on a clean machine** — it is validated by review, `bash -n` and `helm template` only. Treat the first real run as supervised; every failure message points at the guide that explains the step.

Day-to-day operation goes through the Makefile:

| Command | What it does |
|---|---|
| `make install` / `upgrade` / `uninstall` | Manage the Helm release `opentwins` in namespace `opentwins` (the name is fixed: several values derive from it) |
| `make status` | Pod status (~1–2 min to converge on a fast host) |
| `make endpoints` | Service URLs (Grafana, Ditto, InfluxDB, MQTT) |
| `make upload-build` / `make copy-build SRC=…` | Unity WebGL build to the nginx pod / into `build/` |
| `make generate-data MQTT_PORT=30511 DITTO_URL=http://localhost:30525 DITTO_PASSWORD=…` | Oven demo against the Helm NodePorts |

Usernames are fixed — Grafana `admin`, Ditto `ditto` and `devops`, InfluxDB `admin` (org `opentwins`, bucket `default`). There are **no default passwords**: you generate them before the first install. MongoDB is `ClusterIP` and not exposed; Mosquitto and the extended API have no authentication, so the Helm stand is LAN-only.

The step-by-step guides (in Russian, written for the lab host) are in [docs/guides/](docs/guides/); the full installation journal is [docs/install-log.md](docs/install-log.md).

## Repository layout

| Path | What it is |
|---|---|
| `deploy/compose/` | Docker Compose deployment (`make up`) |
| `examples/` | [Example Mine](examples/mine/) and older demos: oven, bakery, light bulb, AR lamp, solar |
| `scripts/` | Compose helpers (credentials, preflight, smoke test) and Helm helpers |
| `values.yaml`, `templates/`, `charts/` | Helm chart: values, platform glue, vendored subcharts |
| `post-install/` | Helm post-install jobs: default policy, Ditto connections, Raspberry Pi example |
| `vendor/grafana-plugins/` | Vendored and rebranded ERTIS Grafana plugins |
| `rebuild/extended-api/` | Reproducible arm64 build of the Ditto extended API image |
| `build/` | Unity WebGL build served to the Unity panel |
| `docs/` | Helm guides (in Russian), installation journal, engineering notes — see [docs/README.md](docs/README.md). Not needed for the Compose quick start |

## Contributing

Bug reports and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

OpenEgiz's own code is [MIT](LICENSE). OpenEgiz is a fork of [OpenTwins](https://github.com/ertis-research/opentwins) by ERTIS Research (University of Málaga): the parts derived from it, including the vendored ERTIS Grafana plugins, remain under the [Apache License 2.0](LICENSES/Apache-2.0.txt). [NOTICE](NOTICE) lists what comes from where. Eclipse Ditto, Grafana, InfluxDB, Telegraf, Mosquitto and MongoDB are their respective projects under their own licenses.
