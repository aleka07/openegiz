# Генератор данных для цифрового двойника печи

Генерирует и отправляет реалистичные данные электрических параметров
промышленной печи (`org.digitalegiz:oven-01`) в OpenTwins через MQTT (Mosquitto).

## Параметры (features)

| Feature | Описание | Диапазон |
|---|---|---|
| `voltage_v` | Напряжение (В) | 215–235 |
| `current_a` | Ток (А) | 5–50 |
| `active_power_kw` | Активная мощность (кВт) | 1–10 |
| `power_factor` | Коэффициент мощности (cosφ) | 0.75–0.99 |

## Установка

```bash
cd data-generator
pip install -r requirements.txt
```

## Запуск

```bash
# Базовый запуск (localhost:30511, интервал 5 сек)
python3 data_generator.py

# С другим интервалом
python3 data_generator.py --interval 2

# С указанием хоста
python3 data_generator.py --mqtt-host 192.168.1.100 --mqtt-port 1883
```

Остановить: `Ctrl+C`

## Проверка данных

```bash
curl -s -u ditto:ditto http://localhost:30525/api/2/things/org.digitalegiz:oven-01/features | python3 -m json.tool
```
