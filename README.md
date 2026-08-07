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

## Quick Start

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

Default credentials (LAN use only — change before any real deployment): Grafana `admin`/`admin`, Ditto `ditto`/`ditto`, InfluxDB `admin`/`password` (org `opentwins`, bucket `default`). MongoDB is exposed unauthenticated on a NodePort by default — set `plainMongodb.service.type: ClusterIP` to close it.

## Creating Digital Twins

1. Open Grafana (`make endpoints` shows the URL) and log in
2. Open the **OpenEgiz** app in the left sidebar → **Twins** → **New twin**
3. Set **Namespace** `org.openegiz`, **ID** `oven-01`, strategy **From scratch**, **Policy ID** `default:basic-policy`, **Name** `Oven 1`
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

MIT (see [LICENSE](LICENSE)). Built on [OpenTwins](https://github.com/ertis-research/opentwins) and its Grafana plugins by ERTIS Research; Eclipse Ditto, Grafana, InfluxDB, Telegraf, Mosquitto and MongoDB are their respective projects under their own licenses.
