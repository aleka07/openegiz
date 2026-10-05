# OpenEgiz docs

*Русский: короткая сводка внизу.*

**New here? You don't need this folder.** To run OpenEgiz on a laptop, follow the [Quick start in the root README](../README.md#quick-start-docker-compose): `make up`, then `make example-mine`. To build your own twins, start from the [Example Mine](../examples/mine/).

This folder is for the **Helm path** (a long-running k3s server, our ARM64 lab host) and for the engineering history behind the platform.

## Helm guides (in Russian)

[guides/](guides/) — step-by-step installation and operation of the Helm chart on k3s, written for our lab host (ASUS Ascent GX10, arm64). Start with [guides/README.md](guides/README.md). `bootstrap.sh` points into these guides when a step fails.

## Engineering notes

Why things are the way they are. Read them when you change the matching part of the platform.

| File | What it covers |
|---|---|
| [arm64-audit.md](arm64-audit.md) | Every image in the Helm chart checked for aarch64 support |
| [notes-extended-api-build.md](notes-extended-api-build.md) | Building the Ditto extended API image from source |
| [notes-mongodb-arm64.md](notes-mongodb-arm64.md) | Why the Bitnami MongoDB chart was replaced with a plain StatefulSet |
| [notes-rebrand-plugins.md](notes-rebrand-plugins.md) | Vendoring and rebranding the ERTIS Grafana plugins |
| [notes-course-tools.md](notes-course-tools.md) | pm4py and JaamSim, installed by `bootstrap.sh --with-course-tools` |
| [runbook-bakery-scenario.md](runbook-bakery-scenario.md) | Lab-host runbook for the bakery scenario in [examples/bakery/](../examples/bakery/) (in Russian) |
| [notes-hermes-integration.md](notes-hermes-integration.md) | Connecting the Hermes agent to the twins — [integrations/hermes/](../integrations/hermes/) (in Russian) |
| [notes-hermes-research.md](notes-hermes-research.md) | Research behind that integration; not an install guide (in Russian) |

## Installation journal

[install-log.md](install-log.md) — the raw chronological log of the first lab-host installation: every step, every error message and its fix. The guides link to it where the history explains a decision. It is a record, not instructions.

---

**По-русски.** Чтобы запустить OpenEgiz на ноутбуке, эта папка не нужна: см. [быстрый старт в README](../README.ru.md#быстрый-старт-docker-compose) и [Пример рудника](../examples/mine/README.ru.md). Здесь лежат гайды по Helm на k3s ([guides/](guides/README.md)), инженерные заметки о том, почему платформа устроена так, и сырой журнал первой установки ([install-log.md](install-log.md)).
