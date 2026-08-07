# Hermes Agent (Nous Research) — ресерч для AI-слоя над стеком цифрового двойника

Дата: 2026-08-07
Автор: research-заметка (проверено по первоисточникам, ссылки в конце каждого раздела)
Контекст железа: ASUS GX10 (NVIDIA GB10 Grace Blackwell, 128 ГБ unified memory / ~121 ГБ доступно, 20 CPU, aarch64, Ubuntu), k3s: Eclipse Ditto + MQTT + InfluxDB + Grafana + pm4py + JaamSim CLI.

---

## 1. Что такое Hermes Agent

**Короткий ответ: это open-source агентский фреймворк (CLI + TUI + web-dashboard + desktop-приложение + messaging-шлюз), а не хостинговый сервис.** Хостинговая часть (Nous Portal) — опциональный провайдер моделей и «tool gateway», её можно не использовать вообще.

Факты:

- Репозиторий: `github.com/NousResearch/hermes-agent`, язык — Python, лицензия **MIT**, создан 2025-07-22, активно пушится (последний push на момент проверки — 2026-08-07). Топики репы включают `openclaw`, `clawdbot`, `moltbot` — то есть это ребренд/продолжение линейки OpenClaw, отсюда огромное число звёзд (~227k) и очень большой объём кода (9.5k файлов в дереве).
- Позиционирование: «self-improving agent» — замкнутая петля обучения: агент сам создаёт и правит скиллы (`~/.hermes/skills/`), ведёт память, ищет по прошлым сессиям (FTS5 + LLM-суммаризация).
- Архитектура по сути классическая агентская: **системный промпт + набор tool-схем → LLM (любой OpenAI-совместимый endpoint) → цикл tool-calls → результаты в контекст**. Плюс поверх: профили, cron, субагенты (делегирование), песочницы выполнения, шлюзы в мессенджеры.
- Поверхности взаимодействия: CLI (`hermes`), TUI, web-dashboard (`hermes dashboard`, порт 9119, встраивает тот же TUI через xterm.js), Desktop-приложение (macOS/Windows/Linux), REST/OpenAI-совместимый API-сервер, и 20+ мессенджеров (Telegram, Discord, Slack, Matrix, IRC, Home Assistant, Open WebUI как фронт и т.д.).

Источники:
- https://hermes-agent.nousresearch.com/
- https://github.com/NousResearch/hermes-agent
- https://api.github.com/repos/NousResearch/hermes-agent (лицензия MIT, метаданные)
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/web-dashboard.md

---

## 2. Self-hosting: да, полностью

### 2.1 Платформа

Официальная матрица поддержки (`getting-started/platform-support.md`):

- **Tier 1**: Linux (x86_64 и **aarch64**) через `install.sh`; **Docker-контейнер (x86_64 и aarch64)**; macOS Apple Silicon; Windows 10/11.
- Tier 2: Android/Termux, Nix.
- Не поддерживается: установка через pip/pypi, brew, AUR.

То есть **наш aarch64 Ubuntu — Tier 1**, это первый приоритет поддержки, не «best effort».

**Проверено фактически**: образ `nousresearch/hermes-agent:latest` на Docker Hub — мульти-арх OCI-индекс, содержит `linux/amd64` **и** `linux/arm64`. (Проверял через registry API, манифест-лист отдаёт обе платформы.)

Установка на хост:
```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```
Ставит uv, Python 3.11, Node.js v22, ripgrep, ffmpeg, клонирует репу в `~/.hermes/hermes-agent/`, данные — в `~/.hermes/`. Единственная предпосылка на Linux: `git`, `curl`, `xz-utils`. Есть флаг `--skip-browser` (не тянуть Playwright/Chromium — для headless-сервера это то, что нужно). Поддержан root-режим (FHS: `/usr/local/lib/hermes-agent/`) и запуск от отдельного непривилегированного сервисного пользователя + systemd.

### 2.2 Модель: свой endpoint, без облака

Hermes работает с **любым OpenAI-совместимым API**. В конфиге это провайдер `custom` — first-class, не алиас:

```yaml
# ~/.hermes/config.yaml
model:
  default: <имя модели>
  provider: custom
  base_url: http://localhost:8000/v1
  api_key: ""      # локально не нужен
```

Явно перечислены как рабочие: Ollama, **vLLM**, llama.cpp server, SGLang, LocalAI.

Важные практические детали из их же доков:

- **Минимальный контекст — 64k токенов.** Hermes на каждом вызове шлёт системный промпт + схемы всех включённых тулов; при 2048-токенном дефолте Ollama агент просто не работает. Контекст задаётся при настройке модели (`Context length: 64000`) и на стороне сервера (`--max-model-len` у vLLM, `num_ctx` у Ollama).
- **Tool calling обязателен.** Модель без function calling может только болтать, не действовать. Для vLLM нужны флаги `--enable-auto-tool-choice --tool-call-parser hermes`; для llama.cpp — `--jinja`. Если модель печатает сырой JSON вместо вызова тула — это почти всегда неправильно настроенный сервер, а не модель.
- Таймауты для локальных моделей: `HERMES_API_TIMEOUT=1800` в `~/.hermes/.env`; Hermes сам поднимает stream read timeout до 1800 с при детекте локального endpoint (`HERMES_STREAM_READ_TIMEOUT`).
- Есть `hermes prompt-size` — показывает байтовую раскладку системного промпта и tool-схем, чтобы урезать лишние toolsets (`hermes tools`) и скиллы. На локальной модели это напрямую бьёт по prefill-задержке первого ответа.
- Есть fallback-провайдеры: локальная модель по умолчанию, облако — только когда локальная трижды не справилась. Для курса можно оставить только локальную.

### 2.3 Модели Hermes: что реально влезет в GB10

Nous поставляет **скаффолдинг агента отдельно от моделей** — Hermes Agent не привязан к моделям Hermes, а модели Hermes — обычные open-weight веса на Hugging Face. Это независимые продукты.

Актуальная линейка (по HF API, автор `NousResearch`, отсортировано по дате):

| Модель | База | Веса | Дата | Оценка под GB10 (121 ГБ unified) |
|---|---|---|---|---|
| **Hermes-4.3-36B** + **Hermes-4.3-36B-GGUF** | ByteDance Seed-OSS 36B, Apache 2.0 | BF16 + GGUF Q4/Q5/Q6/Q8 | 2025-12 | **основной кандидат.** Q4 ≈ 20–22 ГБ, Q8 ≈ 38 ГБ, BF16 ≈ 72 ГБ — всё влезает, Q8/BF16 с запасом под длинный контекст |
| Hermes-4-14B, Hermes-4-14B-FP8 | Qwen3-14B | BF16/FP8 | 2025-09 / обновл. 2026-01 | влезает легко (~28 ГБ BF16), самый быстрый вариант, слабее в многошаговых рассуждениях |
| Hermes-4-70B, Hermes-4-70B-FP8 | Llama 3.1 70B | BF16/FP8 | 2025-09 | FP8 ≈ 70 ГБ — формально влезает, но при 273 ГБ/с пропускной способности памяти генерация будет медленной; риск по контексту |
| Hermes-4-405B(-FP8) | Llama 3.1 405B | BF16/FP8 | 2025-09 | **не влезает**, даже FP8 ≈ 405 ГБ |

Hermes 4.3 (36B) — самая свежая и самая скачиваемая модель линейки; в карточке модели явно указано: tool calling через `<tool_call>{...}</tool_call>`, автопарсеры **vLLM (`--tool-call-parser hermes`)** и SGLang (`qwen25`), рекомендуемый сэмплинг `temperature=0.6, top_p=0.95, top_k=20`, лицензия Apache 2.0. Hermes 5 на 2026-08 не анонсирован.

**Осторожно с инференс-стеком на GB10.** Это sm_121 (consumer Blackwell) + aarch64 + unified memory, и это самая рискованная часть плана, а не сам Hermes:
- Готовые arm64-бинарники llama.cpp/Ollama из дистрибутивов часто откатываются в CPU-only на GB10 — нужна сборка под платформу.
- Официальный `vllm/vllm-openai:latest` на Docker Hub собран под amd64; на aarch64 даст `exec format error`. Нужен arm64/CUDA-образ (NGC-контейнеры NVIDIA под DGX Spark) или локальная сборка.
- Практический вывод: сначала поднять и **проверить сам inference-сервер с tool calling**, и только потом подключать Hermes. Hermes тут — тонкий клиент, он не диктует движок.

Источники:
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/getting-started/platform-support.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/getting-started/installation.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/local-ollama-setup.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/faq.md
- https://huggingface.co/NousResearch/Hermes-4.3-36B , https://huggingface.co/NousResearch/Hermes-4.3-36B-GGUF
- https://huggingface.co/NousResearch/Hermes-4-14B , https://huggingface.co/NousResearch/Hermes-4-70B , https://huggingface.co/NousResearch/Hermes-4-405B
- https://vlaicu.io/posts/dgx-vllm-playbook/ , https://vlaicu.io/posts/dgx-llamacpp-playbook/ (сообщество, про arm64/sm_121 подводные камни)

---

## 3. Как подключать наш стек: тулы и расширения

Hermes даёт **четыре** независимых механизма расширения. Для нашей задачи нужны три из них.

### 3.1 Встроенные тулы (уже готовы «из коробки»)

Toolsets, релевантные проекту:

- `terminal` — `terminal` (выполнить shell-команду, есть `background=true` + `process` для управления фоновыми процессами с poll/log/wait/kill). **Это прямой путь для JaamSim CLI**: сборка команды, запуск симуляции в фоне, опрос статуса, чтение лога.
- `file` — `read_file`, `write_file`, `patch` (fuzzy find-and-replace с unified diff и авто-syntax-check), `search_files` (ripgrep). **Это прямой путь для редактирования `.cfg`-моделей JaamSim.** Причём `patch` заметно безопаснее, чем sed из шелла.
- `code_execution` — `execute_code`: запускает Python-скрипт, который может **программно вызывать тулы Hermes**, фильтровать/сжимать большие выходы до попадания в контекст. Идеальный шов для pm4py и для агрегации временных рядов InfluxDB (не тащить 100k точек в контекст, а посчитать в Python и вернуть сводку).
- `cronjob` — расписания (например, ночной прогон process mining).
- `delegation` — субагенты в изолированных сессиях.
- `todo`, `memory`, `session_search`, `skills`, `web`, `vision`.

Toolsets включаются/выключаются командой `hermes tools` — для курса лишние (`spotify`, `discord_admin`, `image_gen`, `video`, `x_search`, `browser`) стоит выключить, это уменьшит системный промпт и ускорит локальную модель.

### 3.2 MCP-клиент (главный путь для Ditto и InfluxDB)

MCP идёт в стандартной поставке, дополнительных шагов нет. Поддержаны **оба** транспорта:

- **stdio** — локальный подпроцесс (`command` + `args` + `env`), с фильтрацией окружения (в подпроцесс уходит только явно заданный `env` + безопасный базовый набор — меньше риска утечки секретов).
- **HTTP** — `url` + `headers`, включая OAuth и mTLS (`client_cert` / `client_key`).

Конфиг в `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  ditto:
    url: "http://ditto-mcp.openegiz.svc:8080"
    headers:
      Authorization: "Bearer ${DITTO_TOKEN}"     # поддерживается ${ENV_VAR}-подстановка
  influx:
    command: "uv"
    args: ["run", "/opt/openegiz/mcp/influx_server.py"]
    env:
      INFLUX_URL: "http://influxdb.openegiz.svc:8086"
      INFLUX_TOKEN: "${INFLUX_TOKEN}"
```

Полезное для курса:
- **Пофайловая фильтрация тулов**: whitelist/blacklist с glob-паттернами на каждый сервер. Можно дать студентам read-only срез Ditto (`things:read*`), спрятав мутации.
- `idle_timeout_seconds` / `max_lifetime_seconds` — переработка «тяжёлых» stdio-серверов.
- Dynamic Tool Discovery и `hermes mcp add` с пресетами.
- Ограничение: встроенный `hermes mcp serve` (Hermes **как** MCP-сервер для чужих клиентов) — только stdio. Нам это не нужно, нам нужна клиентская сторона, и она умеет и stdio, и HTTP.

**Встроенного импортёра OpenAPI-спеки нет.** Ditto REST API и InfluxDB придётся оборачивать либо своим MCP-сервером (питоновский FastMCP — 100–200 строк), либо скиллом на `curl`+`execute_code`, либо плагином.

### 3.3 Skills — процедурная память (самый дешёвый путь)

Скилл — это папка с `SKILL.md` (инструкции + примеры команд) плюс опционально скрипты и шаблоны. Формально совместимо с открытым стандартом agentskills.io. Официальное правило от Nous:

> Делай **Skill**, если возможность выражается через инструкции + shell-команды + существующие тулы. Делай **Tool**, если нужна сквозная интеграция с API-ключами, кастомной обработкой, бинарными данными или стримингом.

По этому критерию **JaamSim, pm4py и Grafana — это скиллы, а не тулы**. Скилл «запусти JaamSim-прогон» = инструкция + шаблон `.cfg` + скрипт-обёртка; агент дальше сам вызывает `patch`/`terminal`. Плюс агент умеет создавать и улучшать скиллы сам по ходу работы, что для учебного стенда скорее фича, чем риск (но см. открытые вопросы).

### 3.4 Плагины — кастомные Python-тулы без правки ядра

Кладём каталог в `~/.hermes/plugins/<name>/` с `plugin.yaml` и `__init__.py`:

```python
def register(ctx):
    ctx.register_tool(name=..., toolset=..., schema=..., handler=...)
    ctx.register_hook("post_tool_call", cb)
    ctx.register_command("/twin", handler, "query digital twin")
    ctx.register_cli_command(...)
    ctx.register_skill(name, path)
```

Плагины **opt-in** (нужен allow-list), есть хуки, слэш-команды, регистрация провайдеров моделей/памяти/контекст-движков. Если захотим «родные» тулы `ditto_query`, `influx_range`, `jaamsim_run` с нормальными JSON-схемами — это путь, и он не требует форка репы. Правила для хендлера: возвращать JSON-строку, ошибки — как `{"error": "..."}`, не бросать исключения.

Источники:
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/tools-reference.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/plugins.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/adding-tools.md

---

## 4. Многопользовательский режим, auth, оффлайн

### 4.1 Оффлайн

- «API-вызовы идут **только** к тому LLM-провайдеру, который вы настроили. Hermes Agent не собирает телеметрию, статистику использования и аналитику. Разговоры, память и скиллы хранятся локально в `~/.hermes/`» — прямая цитата из их FAQ.
- Полностью локальная работа заявлена как поддерживаемый сценарий (Ollama/vLLM/llama.cpp/SGLang/LocalAI).
- Что всё-таки ходит в интернет по умолчанию и должно быть отключено/предзагружено для LAN-курса: онлайновый **model-catalog manifest** (`hermes-agent.nousresearch.com/docs/api/model-catalog.json` — курируемые списки моделей для пикера; переопределяется в конфиге), `hermes update`, установка MCP-серверов через `npx`/`uvx` (тянет из npm/PyPI), веб-поиск и браузерные тулы. Всё это выключаемо, но **режима «air-gapped» одной галочкой в доках не нашёл** — это открытый вопрос, нужна практическая проверка на изолированной сети.

### 4.2 Auth и много пользователей

Есть три разных поверхности, у каждой своя аутентификация:

1. **Web-dashboard** (`hermes dashboard`): по умолчанию `127.0.0.1:9119` без авторизации (только loopback). При бинде на `0.0.0.0` **обязателен** провайдер аутентификации, иначе сервер падает на старте («fails closed»). Встроенный basic-провайдер:
   ```bash
   HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin
   HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=<сильный пароль>
   HERMES_DASHBOARD_BASIC_AUTH_SECRET=<openssl rand -base64 32>
   ```
   Есть защита от DNS-rebinding (проверка Host-заголовка) и peer-IP guard. Флаг `--insecure` больше не отключает auth (no-op).
   Проверка: `curl -s http://IP:9119/api/status | jq '.auth_required, .auth_providers'`.

2. **API-сервер** (OpenAI-совместимый): bearer-токен `API_SERVER_KEY`, **обязателен для любого деплоя, включая loopback**, потому что API даёт полный доступ к тулсету, включая выполнение shell-команд. Бинд по умолчанию `127.0.0.1` (`API_SERVER_HOST`), CORS — `API_SERVER_CORS_ORIGINS`. Эндпоинты: `/v1/chat/completions`, `/v1/responses`, `/v1/runs` (SSE-стрим событий, tool-progress, approval), `/api/jobs`, Sessions API, `/health`. Есть заголовок `X-Hermes-Session-Key` для стабильного per-user скоупа памяти — сделан ровно под мультиюзерные фронты типа Open WebUI.

3. **Messaging gateway**: несколько пользователей общаются с одним инстансом через Telegram/Discord/Slack/Matrix/Home Assistant; доступ ограничивается allowlist и DM-pairing.

**Изоляция пользователей — через профили** (`hermes -p <name> …`, отдельный `HERMES_HOME` на профиль: своя модель, скиллы, память, история, свой gateway-процесс). Dashboard — машинного уровня, переключает профили из сайдбара (`?profile=<name>`).

**Честная оценка для курса**: это НЕ полноценная многопользовательская SaaS-система с ролями и SSO. Это однопользовательский агент, который можно (а) выставить в LAN за одним общим паролем/токеном, (б) размножить по профилям на студента, (в) отдать через мессенджер/Open WebUI с per-user session key. Для группы студентов самый чистый вариант — **Open WebUI (или свой фронт) → API-сервер Hermes с bearer-токеном → per-student `X-Hermes-Session-Key`**, либо по профилю на студента.

### 4.3 Безопасность выполнения

- Approvals: режимы `smart` / `manual` / `off` для опасных команд (`approvals` в конфиге, доступно из dashboard).
- Семь terminal-бэкендов: local, Docker, SSH, Singularity, Modal, Daytona, Vercel Sandbox. Для курса разумно — **Docker-бэкенд**, чтобы `terminal` студента не выполнялся прямо на хосте k3s.
- Docker-образ мультиарх, есть compose-примеры и раздел про подключение к локальным inference-серверам (vLLM/Ollama) из контейнера, персистентные volume под `~/.hermes/`, мульти-профильная супервизия через s6.

Источники:
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/faq.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/api-server.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/web-dashboard.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/docker.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/environment-variables.md

---

## 5. Рекомендуемый путь интеграции (черновик, не выполнено)

Порядок именно такой — каждый шаг проверяем до перехода к следующему:

1. **Инференс-сервер отдельно от Hermes.** Поднять на GX10 vLLM (arm64/CUDA-образ или сборка) либо llama.cpp с Hermes-4.3-36B (Q8 или BF16). Обязательно `--enable-auto-tool-choice --tool-call-parser hermes`, `--max-model-len 65536`. Критерий приёмки: `curl /v1/chat/completions` с `tools` возвращает настоящий `tool_calls`, а не текст.
2. **Hermes на хосте** (`install.sh --skip-browser`), `hermes model` → Custom endpoint → `http://127.0.0.1:8000/v1`, context 64000. `HERMES_API_TIMEOUT=1800`. Проверка: `hermes doctor`, затем `hermes chat -q "run: uname -a"`.
3. **Обрезать тулсеты** (`hermes tools`) до `terminal`, `file`, `code_execution`, `todo`, `skills`, `memory`, `cronjob`. Сверить размер промпта через `hermes prompt-size`.
4. **MCP-серверы для Ditto и InfluxDB** — два маленьких Python FastMCP-сервера (things read/query, telemetry range-query с агрегацией на стороне сервера). Подключить по stdio, наложить whitelist тулов.
5. **Скиллы для JaamSim и pm4py** — `SKILL.md` + шаблоны `.cfg` + скрипты-обёртки; агент работает через `patch` + `terminal(background=true)` + `process`.
6. **Доступ для студентов**: API-сервер с `API_SERVER_KEY` + Open WebUI как фронт, per-student `X-Hermes-Session-Key`; либо профиль на студента. `terminal.backend: docker`, `approvals: smart`.
7. Отключить всё исходящее: свой model-catalog URL, без `hermes update` во время занятий, MCP-серверы предустановлены (никаких `npx -y` на живом занятии — это сетевой поход в npm).

---

## 6. Альтернативы (только как fallback-информация — не предложение отказаться от Hermes)

**Open WebUI + инструменты/MCP.** Самый популярный self-hosted чат-фронт для локальных LLM. Своя система «Tools» на Python прямо в UI, плюс подключение MCP-серверов через прослойку `mcpo` (MCP→OpenAPI). Сильные стороны — настоящая многопользовательность с ролями, регистрацией, RBAC и группами, что у Hermes слабое место. Слабая сторона — агентская петля примитивнее: нет самообучающихся скиллов, субагентов, cron-джобов, семи бэкендов выполнения. Интересно, что Hermes официально документирует Open WebUI как фронт к своему API-серверу — то есть это не «или-или», а комбинируемо, и это, вероятно, лучшая связка для курса.

**LibreChat.** Зрелый мультиюзерный self-hosted чат (MongoDB + Meilisearch), настоящая аутентификация (локальная, OAuth, LDAP), права по пользователям, поддержка MCP-серверов и «Agents» с тулами и файлами. Ближе всех к «класс на 20 студентов с личными аккаунтами». Ценой того, что агентская автономия слабее, чем у Hermes: нет полноценного shell-доступа к машине как первоклассного тула — а нам он нужен для JaamSim, и его пришлось бы вносить своим MCP-сервером.

**Свой цикл vLLM + MCP.** ~300–500 строк Python: OpenAI-клиент к локальному vLLM, MCP-клиент (официальный SDK), цикл tool-call, простой web-фронт. Даёт полный контроль над промптом, аудитом и правами — и как учебный артефакт это, возможно, ценнее готового продукта: студенты видят, как агент устроен внутри. Минус очевидный: всё, что у Hermes уже есть (память, компрессия контекста, approvals, session storage, фоновые процессы, cron), придётся писать самому либо жить без этого.

---

## 7. Открытые вопросы (требуют проверки на железе)

1. **Инференс на GB10** — главный риск. Заработает ли vLLM с `--tool-call-parser hermes` на sm_121/aarch64 без бубна; какая реальная скорость Hermes-4.3-36B при 64k контекста и 273 ГБ/с памяти. Prefill системного промпта + tool-схем может занимать десятки секунд на каждом первом ходе — на живом занятии это критично.
2. **Качество tool-calling локальной 36B-модели** в многошаговых сценариях (Ditto → InfluxDB → pm4py → JaamSim в одной задаче). Hermes умеет авто-починку кривых tool-call, но 36B ≠ Sonnet. Нужен прогон реальных учебных заданий.
3. **Реальная air-gapped работа**: полный список исходящих запросов при старте и в рантайме. Доки телеметрию отрицают, но model-catalog, update-check и `npx`-установки MCP — это сетевые походы. Проверять через `tcpdump`/сетевую политику.
4. **Модель доступа для группы**: профиль на студента (изоляция хорошая, ресурсоёмко — каждый профиль тянет свою сессию и память) против одного инстанса за Open WebUI (дёшево, но общая память и общий шелл). Решать до курса.
5. **Самомодификация агента**: Hermes по дизайну сам пишет и правит скиллы и файлы. На учебном стенде это может тихо разломать эталонную конфигурацию между занятиями. Нужен либо read-only монтаж эталона, либо ежедневный откат состояния (в Hermes есть checkpoints/rollback — не изучено детально).
6. **Зрелость проекта**: репа огромная и меняется каждый день (это ребренд OpenClaw). Для курса **обязательно пиновать конкретный тег/образ** и не обновляться в семестре.
7. Не проверено: работает ли `execute_code` (Python-скрипты, вызывающие тулы) с локальной моделью так же стабильно, как с облачной — это ключевой шов для pm4py.
