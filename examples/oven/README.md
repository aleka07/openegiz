# Генератор данных для цифрового двойника печи

Генерирует и отправляет реалистичные данные электрических параметров
двух промышленных печей (`org.openegiz:oven-01`, `org.openegiz:oven-02`) в OpenEgiz через MQTT (Mosquitto).

## Параметры (features)

| Feature | Описание | Диапазон |
|---|---|---|
| `voltage_v` | Напряжение (В) | 215–235 |
| `current_a` | Ток (А) | 5–50 |
| `active_power_kw` | Активная мощность (кВт) | 1–10 |
| `power_factor` | Коэффициент мощности (cosφ) | 0.75–0.99 |

## Запуск

Из корня репозитория, при запущенной платформе (`make up`):

```bash
make generate-data
```

Команда при первом запуске создаёт `examples/.venv`, затем создаёт (или
обновляет) двойники печей в Ditto из [`twins.json`](twins.json) и шлёт
телеметрию каждые 5 секунд. Остановить: `Ctrl+C`.

Порты и пароль Ditto берутся из `deploy/compose/.env`. Для Helm-развёртывания
их нужно передать явно:

```bash
make generate-data MQTT_PORT=30511 DITTO_URL=http://localhost:30525 DITTO_PASSWORD=...
```

Генератор можно запускать и напрямую:

```bash
examples/.venv/bin/python examples/oven/data_generator.py --mqtt-port 1883 --interval 2
```

## Проверка данных

```bash
set -a; . deploy/compose/.env; set +a
curl -s -u "ditto:$DITTO_PASSWORD" http://localhost:8080/api/2/things/org.openegiz:oven-01/features | python3 -m json.tool
```
