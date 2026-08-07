# Генератор данных для цифрового двойника лампочки

Генерирует и отправляет реалистичные данные лампочки (`summerschool:lightbulb-01`) в OpenTwins через MQTT (Mosquitto).
Включает HTTP-эндпоинт для управления состоянием (on/off).

## Параметры (features)

| Feature | Описание | Диапазон |
|---|---|---|
| `brightness` | Яркость (люмен) | 0–800 |
| `power_consumption` | Потребление (Вт) | 0–60 |
| `voltage` | Напряжение (В) | 210–235 |
| `temperature` | Температура (°C) | 25–85 |

## Установка

```bash
cd data-generator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Запуск

```bash
source data-generator/venv/bin/activate
python3 data-generator/lightbulb_generator.py
```

С другим интервалом:
```bash
python3 data-generator/lightbulb_generator.py --interval 2
```

Остановить: `Ctrl+C`

## Запуск в фоне

Чтобы терминал не был занят:

```bash
python3 data-generator/lightbulb_generator.py --daemon
```

Логи пишутся в `data-generator/lightbulb_generator.log`.

Остановить фоновый процесс:
```bash
python3 data-generator/lightbulb_generator.py --stop
```

Посмотреть логи в реальном времени:
```bash
tail -f data-generator/lightbulb_generator.log
```

## Управление состоянием (on/off)

Генератор поднимает HTTP API на порту `8090`. Из другого терминала:

```bash
# Получить текущее состояние
curl http://localhost:8090/state

# Выключить лампочку
curl -X POST -d '{"state":"off"}' http://localhost:8090/state

# Включить лампочку
curl -X POST -d '{"state":"on"}' http://localhost:8090/state
```

При переключении:
- **on → off** — яркость плавно гаснет, мощность падает до 0, температура медленно снижается
- **off → on** — яркость плавно нарастает, температура растёт

## Проверка данных в Ditto

```bash
curl -s -u ditto:ditto http://localhost:30525/api/2/things/summerschool:lightbulb-01/features | python3 -m json.tool
```

## Аргументы

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `--mqtt-host` | `localhost` | Адрес MQTT-брокера |
| `--mqtt-port` | `30511` | Порт MQTT-брокера |
| `--thing-id` | `summerschool:lightbulb-01` | ID вещи в Ditto |
| `--interval` | `5` | Интервал отправки (сек) |
| `--http-port` | `8090` | Порт HTTP API |
| `--initial-state` | `on` | Начальное состояние |
| `--daemon` | — | Запуск в фоновом режиме |
| `--stop` | — | Остановить фоновый процесс |
