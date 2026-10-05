# OpenEgiz

<p align="center">
  <img src="docs/img/logo-readme.svg" alt="OpenEgiz logo" width="420">
</p>

An open-source digital twin platform for industry: live twin state (Eclipse Ditto), telemetry (MQTT → Telegraf → InfluxDB), dashboards and twin management UI (Grafana), 3D visualization (Unity WebGL) — deployed as a single Helm chart.

Based on [OpenTwins](https://github.com/ertis-research/opentwins) by ERTIS Research (University of Málaga). This fork adds:

- **ARM64 support** — runs on aarch64 hosts (verified on NVIDIA GB10 / ASUS Ascent GX10): the `ditto-extended-api` image is rebuilt natively (see [rebuild/extended-api/](rebuild/extended-api/)), and the bitnami MongoDB (amd64-only) is replaced with a plain StatefulSet on the official `mongo:6.0` image.
- **No runtime dependency on upstream releases** — Grafana plugins are vendored in [vendor/grafana-plugins/](vendor/grafana-plugins/) (rebranded display-level only; plugin ids and ERTIS attribution preserved) and survive offline boots via an on-PVC cache fallback.
- **Stability fixes** — Ditto JVM heap sizing on hosts where the JDK ignores cgroup limits; Grafana upgrade crashloop fix.
- **A full installation journal** — every step, failure and fix: [docs/install-log.md](docs/install-log.md).

## Prerequisites

- A Kubernetes cluster (verified on single-node [k3s](https://k3s.io) v1.36, Ubuntu 24.04, arm64)
- Helm v3
- Outbound internet on first install (images + vendored plugin download)

<details>
<summary>Install k3s + Helm (verified commands)</summary>

```bash
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml   # add to ~/.bashrc
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

Note: k3s bundles its own containerd. To import locally built images use `sudo k3s ctr images import`, not the Docker `ctr` that may shadow it on PATH. Full walkthrough: [docs/install-log.md](docs/install-log.md).

</details>

## Fresh machine install

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

Optional extras, both off by default: `--with-course-tools` (pm4py venv + JaamSim, see [docs/notes-course-tools.md](docs/notes-course-tools.md)) and `--with-bakery` (the bakery twins from [data-generator/bakery/](data-generator/bakery/)). Hermes is installed separately — [integrations/hermes/install.sh](integrations/hermes/install.sh).

> [!IMPORTANT]
> `values.yaml` ships deliberately **invalid** placeholders for every credential. [`secrets.values.yaml.example`](secrets.values.yaml.example) lists the nine keys a fresh install needs; the filled-in copy lives at `~/openegiz-deploy/secrets.values.yaml` (chmod 600) and is never committed. Every helm command must be given it with `-f`.

> [!WARNING]
> `bootstrap.sh` has **not yet been executed on a clean machine** — it is validated by review, `bash -n` and `helm template` only. Treat the first real run as supervised; every failure message points at the guide that explains the step.

You still need to arrange two things yourself first (step 0 checks both and tells you how): passwordless sudo, and your user in the `docker` group. The full manual walkthrough is [docs/guides/01](docs/guides/01%20–%20Подготовка%20машины,%20k3s%20и%20Helm.md) → [02](docs/guides/02%20–%20Установка%20платформы%20на%20ARM64.md) → [03](docs/guides/03%20–%20Проверка%20и%20сквозной%20тест.md).

## Quick Start

Once the platform is installed, day-to-day operation goes through the Makefile:

```bash
make install     # helm release "opentwins" in namespace "opentwins"
make status      # watch pods converge (~1-2 min on a fast host)
make endpoints   # list service URLs (Grafana, Ditto, InfluxDB, MQTT)
```

> [!IMPORTANT]
> The Helm release must be named `opentwins` (the Makefile does this): several
> values reference names derived from the release name.

> [!NOTE]
> On arm64 the `ditto-extended-api` image must be present in the k3s containerd
> store before install — build it once with [rebuild/extended-api/build.sh](rebuild/extended-api/build.sh).
> Hono and Kafka-ML are disabled by default.

Usernames are fixed — Grafana `admin`, Ditto `ditto` and `devops`, InfluxDB `admin` (org `opentwins`, bucket `default`). There are **no default passwords**: you generate them into `~/openegiz-deploy/secrets.values.yaml` before the first install (see [Fresh machine install](#fresh-machine-install)). MongoDB is `ClusterIP` and not exposed; Mosquitto and the extended API have no authentication, so this stand is LAN-only.

## Creating Digital Twins

1. Open Grafana (`make endpoints` shows the URL) and log in
2. Open the **OpenEgiz** app in the left sidebar → **Twins** → **New twin**
3. Set **Namespace** `org.openegiz`, **ID** `oven-01`, strategy **From scratch**, **Policy ID** `default:basic_policy`, **Name** `Oven 1`
4. Add 4 features: `voltage_v`, `current_a`, `active_power_kw`, `power_factor`
5. Repeat for `oven-02` / `Oven 2`

### Send telemetry

```bash
make generate-data   # simulated telemetry for the two ovens via MQTT
```

Data flows MQTT → Ditto (twin state) → MQTT → Telegraf → InfluxDB → Grafana. Telegraf flushes every 10 s — the first points appear with that delay.

## 3D Dashboard (Unity WebGL)

1. Put a Unity WebGL build into `build/` (or `make copy-build SRC=/path`) and run `make upload-build`
2. **Dashboards** → **Create dashboard** → **Add visualization**, datasource **opentwins**, visualization **Unity**
3. Query the latest twin values:

   ```flux
   from(bucket: "default")
   |> range(start: -30s)
   |> filter(fn: (r) => r["_field"] == "value_active_power_kw_properties_value" or r["_field"] == "value_current_a_properties_value" or r["_field"] == "value_power_factor_properties_value" or r["_field"] == "value_voltage_v_properties_value")
   |> last()
   |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
   |> keep(columns: ["thingId", "value_voltage_v_properties_value", "value_current_a_properties_value", "value_active_power_kw_properties_value", "value_power_factor_properties_value"])
   ```

4. **Unity model** → Mode `External links`, paste the four links printed by `make upload-build`
5. **Send data to Unity** → Grafana query name, Mode `Send data to GameObjects by ID column`, ID column `thingId`, Unity function `SetValues`

## Repository Layout

| Path | What it is |
|---|---|
| `values.yaml` | Single control panel for the whole platform |
| `charts/` | Vendored subcharts (Ditto, Grafana, InfluxDB2, Telegraf, Mosquitto, …) |
| `templates/` | Platform glue: extended API, MongoDB, secrets, post-install connection jobs, Telegraf config |
| `vendor/grafana-plugins/` | Vendored + rebranded Grafana plugins, originals, repatch script |
| `rebuild/extended-api/` | Reproducible arm64 build of the Ditto extended API image |
| `data-generator/` | Python telemetry generators (MQTT) |
| `build/` | Unity WebGL build served by the nginx pod |
| `docs/` | Installation journal, ARM64 image audit, working notes |

## Makefile Commands

| Command | Description |
|---|---|
| `make install` / `upgrade` / `uninstall` | Manage the Helm release (ns `opentwins`) |
| `make status` | Show pod statuses |
| `make endpoints` | Show all service endpoints (IP + port) |
| `make upload-build` | Upload Unity WebGL build files to the nginx pod |
| `make copy-build SRC=…` | Copy a Unity build into `build/` |
| `make generate-data` | Run the telemetry generator |

## License

OpenEgiz's own code is [MIT](LICENSE). OpenEgiz is a fork of [OpenTwins](https://github.com/ertis-research/opentwins) by ERTIS Research (University of Málaga): the parts derived from it, including the vendored ERTIS Grafana plugins, remain under the [Apache License 2.0](LICENSES/Apache-2.0.txt). [NOTICE](NOTICE) lists what comes from where. Eclipse Ditto, Grafana, InfluxDB, Telegraf, Mosquitto and MongoDB are their respective projects under their own licenses.
