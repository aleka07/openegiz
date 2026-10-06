# Пример рудника

*English version: [README.md](README.md)*

Самый маленький цифровой рудник, который задействует все части OpenEgiz: образец того, как устроен цифровой рудник на платформе, и наш собственный сквозной тест. Для конкурса это иллюстрация, а не отправная точка: стройте свой рудник. Части Примера, взятые без изменений, баллов не приносят.

```text
excavator-01 ──грузит──▶ truck-01, truck-02 ──везут 3,2 км──▶ crusher-01
      ▲                                                            │
      └──────────────────────── возвращаются пустыми ◀─────────────┘
```

## Запуск

Из корня репозитория (нужен Docker и 6 ГБ памяти для него):

```bash
make example-mine
```

Команда поднимет платформу, если она не запущена, создаст двойников, запустит симулятор и подключит дашборд. Откройте Grafana (адрес и логин печатает `make up`) → **Dashboards → OpenEgiz Examples → Example Mine**. Двойники видны и в приложении **OpenEgiz** → **Twins**.

После этого `make down` и `make up` останавливают и поднимают рудник вместе с платформой, включая дашборд; `make clean` удаляет его вместе со всеми данными. `make example-mine-stop` останавливает симулятор до следующего `make up`, двойники и данные остаются. `make smoke` проверяет и пример, если он запущен.

## Как идут данные

```text
simulator.py ──MQTT telemetry/<двойник>──▶ Ditto (состояние) ──MQTT opentwins/#──▶ Telegraf ──▶ InfluxDB ──▶ Grafana
```

Симулятор не обращается к Ditto или InfluxDB напрямую: он публикует в MQTT команды `modify` [протокола Ditto](https://eclipse.dev/ditto/protocol-overview.html) — так же, как это делал бы настоящий полевой шлюз.

## Двойники

| Двойник | Features |
|---|---|
| `org.openegiz.mine:mine-01` | `tonnes_mined`, `avg_grade`, `trucks_hauling` |
| `org.openegiz.mine:excavator-01` | `state`, `face_grade`, `passes_total` |
| `org.openegiz.mine:truck-01`, `truck-02` | `state`, `payload`, `speed`, `route_position`, `fuel`, `trips_total` |
| `org.openegiz.mine:crusher-01` | `state`, `throughput`, `feed_grade`, `tonnes_total` |

У каждой единицы техники есть `attributes._parents = org.openegiz.mine:mine-01`: по нему приложение OpenEgiz строит иерархию, а Telegraf пишет тег `parent`. В InfluxDB feature превращается в поле `value_<feature>_properties_value` измерения `mqtt_consumer` с тегом `thingId`.

## Чего здесь сознательно нет

Содержание меди — случайное блуждание, скорости постоянны с шумом, дорога одна; нет буровзрывных работ, оптимизации диспетчеризации, ТО, вентиляции, безопасности, энергетики. Эти направления перечисляет карта рудника конкурса: стройте их в своём руднике.
