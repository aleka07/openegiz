# Example Mine

*Русская версия: [README.ru.md](README.ru.md)*

The smallest digital mine that exercises every part of OpenEgiz. It is the reference starting point for contest submissions and our own end-to-end test of the platform.

```text
excavator-01 ──loads──▶ truck-01, truck-02 ──haul 3.2 km──▶ crusher-01
      ▲                                                          │
      └─────────────────────── return empty ◀────────────────────┘
```

## Run it

From the repository root, with the compose stack prerequisites (Docker, 6 GB for Docker):

```bash
make example-mine
```

This brings up the platform if it is not running, creates the twins, starts the simulator and provisions the dashboard. Open Grafana (the URL and login are printed by `make up`) → **Dashboards → OpenEgiz Examples → Example Mine**. The twins are also listed in the **OpenEgiz** app → **Twins**.

From then on `make down` and `make up` stop and start the mine together with the platform, dashboard included; `make clean` removes it along with all data. `make example-mine-stop` stops the simulator until the next `make up`; the twins and the data stay. `make smoke` checks the example as well when it is running.

## How the data flows

```text
simulator.py ──MQTT telemetry/<twin>──▶ Ditto (twin state) ──MQTT opentwins/#──▶ Telegraf ──▶ InfluxDB ──▶ Grafana
```

The simulator never talks to Ditto or InfluxDB directly: it publishes [Ditto protocol](https://eclipse.dev/ditto/protocol-overview.html) `modify` commands to MQTT, exactly as a real field gateway would.

## Twins

| Twin | Features |
|---|---|
| `org.openegiz.mine:mine-01` | `tonnes_mined`, `avg_grade`, `trucks_hauling` |
| `org.openegiz.mine:excavator-01` | `state`, `face_grade`, `passes_total` |
| `org.openegiz.mine:truck-01`, `truck-02` | `state`, `payload`, `speed`, `route_position`, `fuel`, `trips_total` |
| `org.openegiz.mine:crusher-01` | `state`, `throughput`, `feed_grade`, `tonnes_total` |

Every equipment twin carries `attributes._parents = org.openegiz.mine:mine-01`, which the OpenEgiz app uses for the hierarchy and Telegraf stores as the `parent` tag. In InfluxDB a feature appears as the field `value_<feature>_properties_value` on the measurement `mqtt_consumer`, tagged with `thingId`.

## Files

| File | Purpose |
|---|---|
| `twins.json` | Twin definitions (created idempotently by `setup_twins.py`) |
| `simulator.py` | Haul-cycle simulation; `--speedup`, `--interval`, `--dry-run` |
| `dashboard.json` | Grafana dashboard |
| `compose.yml`, `Dockerfile` | Overlay on `deploy/compose/` used by `make example-mine` |

## What it deliberately leaves out

Grade is a random walk, speeds are constant with noise, there is one road and no blasting, drilling, dispatch optimisation, maintenance, ventilation, safety or energy model. These are exactly the directions the contest's mine map invites you to build.
