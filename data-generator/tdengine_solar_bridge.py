#!/usr/bin/env python3
import argparse
import json
import random
import signal
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


TDENGINE_HOST = "mqtt.tdengine.com"
TDENGINE_PORT = 1883
TDENGINE_TOPIC = "sites"

OPENGIZ_MQTT_HOST = "localhost"
OPENGIZ_MQTT_PORT = 30511


SITE_TO_THING = {
    "SITE_001": "summerschool:solar-site-001",
    "SITE_002": "summerschool:solar-site-002",
    "SITE_003": "summerschool:solar-site-003",
    "SITE_004": "summerschool:solar-site-004",
    "SITE_005": "summerschool:solar-site-005",
}


def site_to_features(data):
    now = datetime.now(timezone.utc).isoformat()

    mapping = {
        "AC_Power_MW": "ac_power_mw",
        "Expected_Power_MW": "expected_power_mw",
        "Performance_Ratio": "performance_ratio",
        "Availability_%": "availability_percent",
        "Curtailment_%": "curtailment_percent",
        "Energy_Today_MWh": "energy_today_mwh",
        "POA_Irradiance_Wm2": "poa_irradiance_wm2",
        "Soiling_Index": "soiling_index",
        "Active_Alarms": "active_alarms",
    }

    features = {}

    for source_key, feature_name in mapping.items():
        if source_key in data:
            features[feature_name] = {
                "properties": {
                    "value": data[source_key],
                    "timestamp": data.get("ts", now),
                }
            }

    # Дополнительно сохраняем статус источника как feature.
    features["source_status"] = {
        "properties": {
            "value": "online",
            "source": "TDengine public MQTT",
            "topic": TDENGINE_TOPIC,
            "timestamp": now,
        }
    }

    return features


def build_ditto_message(thing_id, features):
    namespace, name = thing_id.split(":", 1)

    return {
        "topic": f"{namespace}/{name}/things/twin/commands/merge",
        "headers": {
            "content-type": "application/merge-patch+json",
        },
        "path": "/features",
        "value": features,
    }


class SolarBridge:
    def __init__(self, site_id, openegiz_host, openegiz_port):
        self.site_id = site_id
        self.openegiz_host = openegiz_host
        self.openegiz_port = openegiz_port
        self.running = True
        self.count_in = 0
        self.count_out = 0

        self.out_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"openegiz-solar-out-{random.randint(1000, 9999)}",
            protocol=mqtt.MQTTv5,
        )

        self.in_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"openegiz-solar-in-{random.randint(1000, 9999)}",
        )

        self.in_client.on_connect = self.on_connect
        self.in_client.on_message = self.on_message
        self.in_client.on_disconnect = self.on_disconnect

    def connect(self):
        print(f"Подключаемся к OpenEgiz MQTT: {self.openegiz_host}:{self.openegiz_port}")
        self.out_client.connect(self.openegiz_host, self.openegiz_port, keepalive=60)
        self.out_client.loop_start()

        print(f"Подключаемся к TDengine MQTT: {TDENGINE_HOST}:{TDENGINE_PORT}")
        self.in_client.connect(TDENGINE_HOST, TDENGINE_PORT, keepalive=60)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"TDengine connected: {reason_code}")
        client.subscribe(TDENGINE_TOPIC, qos=0)
        print(f"Слушаем topic: {TDENGINE_TOPIC}")

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        print(f"TDengine disconnected: {reason_code}")

    def on_message(self, client, userdata, msg):
        try:
            self.count_in += 1
            payload = msg.payload.decode("utf-8")
            data = json.loads(payload)

            external_site_id = data.get("Site_ID")
            if not external_site_id:
                return

            if self.site_id != "all" and external_site_id != self.site_id:
                return

            thing_id = SITE_TO_THING.get(external_site_id)
            if not thing_id:
                return

            openegiz_topic = f"telemetry/{thing_id}"
            features = site_to_features(data)
            ditto_message = build_ditto_message(thing_id, features)

            result = self.out_client.publish(
                openegiz_topic,
                json.dumps(ditto_message),
                qos=0,
            )
            result.wait_for_publish(timeout=5)

            self.count_out += 1

            ac_power = data.get("AC_Power_MW")
            pr = data.get("Performance_Ratio")
            alarms = data.get("Active_Alarms")

            print(
                f"{datetime.now().strftime('%H:%M:%S')} "
                f"{external_site_id} -> {thing_id} | "
                f"AC={ac_power} MW | PR={pr} | alarms={alarms}"
            )

        except Exception as e:
            print(f"Ошибка обработки сообщения: {e}")

    def loop(self):
        self.in_client.loop_start()

        try:
            while self.running:
                time.sleep(1)
        finally:
            self.stop()

    def stop(self):
        print("Останавливаем bridge...")
        self.in_client.loop_stop()
        self.out_client.loop_stop()
        self.in_client.disconnect()
        self.out_client.disconnect()
        print(f"Получено сообщений: {self.count_in}")
        print(f"Отправлено в OpenEgiz: {self.count_out}")


def main():
    parser = argparse.ArgumentParser(
        description="Bridge: TDengine public MQTT -> OpenEgiz/OpenTwins"
    )
    parser.add_argument(
        "--site-id",
        default="SITE_001",
        help="SITE_001, SITE_002, SITE_003, SITE_004, SITE_005 или all",
    )
    parser.add_argument(
        "--openegiz-mqtt-host",
        default=OPENGIZ_MQTT_HOST,
        help="Адрес OpenEgiz Mosquitto",
    )
    parser.add_argument(
        "--openegiz-mqtt-port",
        type=int,
        default=OPENGIZ_MQTT_PORT,
        help="Порт OpenEgiz Mosquitto",
    )

    args = parser.parse_args()

    if args.site_id != "all" and args.site_id not in SITE_TO_THING:
        print("site-id должен быть SITE_001..SITE_005 или all")
        sys.exit(1)

    bridge = SolarBridge(
        site_id=args.site_id,
        openegiz_host=args.openegiz_mqtt_host,
        openegiz_port=args.openegiz_mqtt_port,
    )

    def handle_stop(sig, frame):
        bridge.running = False

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    bridge.connect()
    bridge.loop()


if __name__ == "__main__":
    main()
