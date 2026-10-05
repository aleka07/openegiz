# Examples

| Example | What it is | Deployment |
|---|---|---|
| [mine/](mine/) | **Example Mine**: a minimal open-pit digital mine. Start here. `make example-mine` | Compose |
| [oven/](oven/) | Two industrial ovens streaming electrical telemetry. `make generate-data` | Compose or Helm |
| [lightbulb/](lightbulb/) | A light bulb twin with an on/off HTTP endpoint | Helm (summer school) |
| [bakery/](bakery/) | Bakery line simulator with process-mining and JaamSim scenarios | Helm (winter school) |
| [ar-lamp/](ar-lamp/) | AR.js page that shows the light bulb twin over a printed marker | Helm (summer school) |
| [solar/](solar/) | Solar-site ML service and a TDengine bridge | Helm (summer school) |

The Raspberry Pi + DHT22 example is part of the Helm chart itself:
[`post-install/example-raspberry/`](../post-install/example-raspberry/).

The Python demos share one dependency list, [`requirements.txt`](requirements.txt):

```bash
python3 -m venv examples/.venv
examples/.venv/bin/pip install -r examples/requirements.txt
```

Helm demos default to the chart's NodePorts (MQTT 30511, Ditto 30525). On a
Compose stack pass the Compose ports instead (MQTT 1883, Ditto 8080 — see
`deploy/compose/.env`).
