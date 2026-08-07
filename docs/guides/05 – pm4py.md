# 05. pm4py — process mining

pm4py — библиотека process mining на Python. В курсовой петле она отвечает за анализ: берёт журнал событий (из InfluxDB или живой из MQTT), восстанавливает по нему модель процесса и сравнивает её с тем, как процесс идёт на самом деле.

Ставится **вне k3s**, обычной user-space установкой в `~/course`. Ничего в кластере, Docker или `update-alternatives` не трогается.

Полная справочная заметка (она же зеркалится на хосте в `~/course/README.md`) — [notes-course-tools.md](../notes-course-tools.md).

## Что должно быть на хосте

Ubuntu 24.04, aarch64, Python 3.12.3. `python3-venv` на gx10-11 уже стоял.

## Установка с нуля

```bash
sudo apt-get install -y python3-venv python3-pip graphviz
mkdir -p ~/course
python3 -m venv ~/course/venv
~/course/venv/bin/pip install --upgrade pip setuptools wheel
~/course/venv/bin/pip install pm4py pandas matplotlib jupyterlab paho-mqtt influxdb-client
```

Про `graphviz` из apt: это системный бинарь `dot`, которым рендерятся карты процессов. Питоновский пакет `graphviz` — только обёртка, без бинаря он ничего не нарисует.

**Главный риск этой установки не оправдался.** pm4py тянет `cvxopt` и `scipy` — оба под ARM компилировались бы мучительно долго. По факту **все пакеты встали из готовых aarch64-колёс**, ни одной сборки из исходников, вся установка заняла 68 секунд.

Зачем в списке `paho-mqtt` и `influxdb-client`: это как раз стыковка с платформой — MQTT для приёма живых событий, InfluxDB для выгрузки исторического журнала, по которому работает майнер.

### Версии (проверено 2026-08-07)

| Пакет | Версия |
|---|---|
| Python | 3.12.3 |
| pm4py | 2.7.23.3 |
| pandas | 3.0.5 |
| numpy | 2.5.1 |
| scipy | 1.18.0 |
| cvxopt | 1.3.3 |
| networkx | 3.6.1 |
| matplotlib | 3.11.1 |
| jupyterlab | 4.6.2 |
| paho-mqtt | 2.1.0 |
| influxdb-client | 1.50.0 |
| graphviz (python) | 0.21 |
| graphviz (system, `dot`) | 2.42.2-9ubuntu0.1 |

Зафиксированные наборы лежат рядом:

```bash
~/course/requirements.txt           # 6 строк верхнего уровня — что мы просили
~/course/requirements-frozen.txt    # 112 строк pip freeze — точное воспроизведение
```

Для побайтово воспроизводимой установки:

```bash
~/course/venv/bin/pip install -r ~/course/requirements-frozen.txt
```

## Функциональная проверка

Не «импортировалось — значит работает», а настоящий прогон майнера:

```bash
~/course/venv/bin/python ~/course/pm4py_check.py
```

Скрипт собирает синтетический журнал на 19 строк (4 кейса, 7 активностей, колонки `case:concept:name` / `concept:name` / `time:timestamp`) через `pm4py.format_dataframe`, потом гоняет inductive miner, token-based replay, построение DFG и экспорт PNG через graphviz.

Ожидаемый вывод:

```text
rows=19 cases=4 activities=7
PETRI NET: places=7 transitions=8 arcs=16
initial_marking=['source:1'] final_marking=['sink:1']
visible transitions: ['Backorder', 'Cancel', 'Check Stock', 'Invoice', 'Pack', 'Receive Order', 'Ship']
fitness (token-based replay): {'perc_fit_traces': 100.0, 'average_trace_fitness': 1.0, 'log_fitness': 1.0, ...}
DFG edges=7 start={'Receive Order': 4} end={'Invoice': 3, 'Cancel': 1}
rendered PNG bytes: 44783
PM4PY FUNCTIONAL CHECK OK
```

Почему это именно функциональная проверка, а не smoke-тест импорта: все 7 активностей вернулись как помеченные переходы, а количество рёбер DFG (7) совпадает с числом различных пар «непосредственно следует» во входных данных, посчитанным руками. Экспорт PNG дополнительно доказывает, что путь через graphviz работает без дисплея.

> **`fitness = 1.0` — это НЕ признак хорошей модели.** Inductive miner по построению гарантирует идеальное воспроизведение своего же входного лога. Единица здесь означает «конвейер отработал целиком», и ничего больше. На реальных данных сравнивать надо модель с *другим* логом.

Две косметические особенности, которые обязательно всплывут у студентов в ноутбуках:

- pm4py при импорте печатает в stderr большой баннер про лицензию AGPL;
- token-based replay рисует прогресс-бар tqdm.

Обе — нормальны, пугаться не надо.

## JupyterLab для лабораторных

```bash
~/course/venv/bin/jupyter lab --no-browser --ip=127.0.0.1 --port=8888
```

С ноутбука студента:

```bash
ssh -L 8888:127.0.0.1:8888 gx10-11
```

Дальше открываем `http://127.0.0.1:8888` уже у себя, токен берём из вывода jupyter на хосте.

> **Биндим строго на `127.0.0.1` и ходим через SSH-туннель.** Открывать порт наружу нельзя: JupyterLab — это выполнение произвольного кода на машине, и на стенде с уже опубликованными наружу дефолтными паролями лишняя дырка совсем не нужна.

## Минимальный пример майнинга

Отправная точка для лабы — на своём датафрейме с тремя обязательными колонками:

```python
import pandas as pd
import pm4py

df = pd.DataFrame({
    "case:concept:name": ["1", "1", "1", "2", "2"],
    "concept:name":      ["Receive Order", "Check Stock", "Ship",
                          "Receive Order", "Cancel"],
    "time:timestamp":    pd.to_datetime([
        "2026-01-01 10:00", "2026-01-01 10:05", "2026-01-01 10:30",
        "2026-01-01 11:00", "2026-01-01 11:07"]),
})

log = pm4py.format_dataframe(df,
                             case_id="case:concept:name",
                             activity_key="concept:name",
                             timestamp_key="time:timestamp")

# 1. модель процесса
net, im, fm = pm4py.discover_petri_net_inductive(log)

# 2. насколько модель воспроизводит лог
print(pm4py.fitness_token_based_replay(log, net, im, fm))

# 3. граф "непосредственно следует" — самое наглядное для первого занятия
dfg, start, end = pm4py.discover_dfg(log)
print(dfg, start, end)
```

Три колонки — это весь контракт pm4py с данными: **что за экземпляр процесса** (`case`), **что произошло** (`activity`), **когда** (`timestamp`). Любой лог, который можно привести к этим трём колонкам, годится — включая выгрузку из InfluxDB, где `thingId` становится case, имя фичи — активностью, а `_time` — временной меткой.

## Итоговая раскладка

```text
~/course/
├── README.md                 # инструкции по переустановке (= notes-course-tools.md)
├── requirements.txt
├── requirements-frozen.txt
├── pm4py_check.py
├── venv/
└── jaamsim/                  # см. гайд 06
```

Дальше — [06 – JaamSim](06%20–%20JaamSim.md).
