#!/usr/bin/env python3
import argparse
import base64
import json
import math
import random
import signal
import sys
import time
import urllib.request
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient


DEFAULT_INFLUX_URL = "http://localhost:30716"
DEFAULT_INFLUX_ORG = "opentwins"
DEFAULT_INFLUX_BUCKET = "default"
DEFAULT_INFLUX_TOKEN = "Hjh3ysMQ6evK=qqpFSYqn-s3JGovJLfHxyCDM=eNNZkdM-uuro93dNtJcodejLYYob2geKQ/29z3Kxui=y6FlL?dZeU9EFRxrYn284V/kZG5==jxLVAMJrYOv?LF79ahwIbhvstMN6gmfQ3DH7/IzUB7VlBZK-cd8aN7YqiFrYRLkBUv7H0QkbqPxgf2dMgCMCwZaLMk9RUeMaBfx2lQ=Mq1EEJJw-Jp!BmpCDnhlc!6D22PaE=Y3sgWWNhRv8oP"

DEFAULT_MQTT_HOST = "localhost"
DEFAULT_MQTT_PORT = 30511
DEFAULT_DITTO_URL = "http://localhost:30525"
DEFAULT_DITTO_USER = "ditto"
DEFAULT_DITTO_PASSWORD = "ditto"

SITE_THINGS = [
    "summerschool:solar-site-001",
]


FIELDS = {
    "ac_power": "value_ac_power_mw_properties_value",
    "expected_power": "value_expected_power_mw_properties_value",
    "performance_ratio": "value_performance_ratio_properties_value",
    "availability": "value_availability_percent_properties_value",
    "curtailment": "value_curtailment_percent_properties_value",
    "energy_today": "value_energy_today_mwh_properties_value",
    "irradiance": "value_poa_irradiance_wm2_properties_value",
    "alarms": "value_active_alarms_properties_value",
}

DITTO_FEATURES = {
    "ac_power": "ac_power_mw",
    "expected_power": "expected_power_mw",
    "performance_ratio": "performance_ratio",
    "availability": "availability_percent",
    "curtailment": "curtailment_percent",
    "energy_today": "energy_today_mwh",
    "irradiance": "poa_irradiance_wm2",
    "alarms": "active_alarms",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


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


def feature(value, timestamp=None):
    return {
        "properties": {
            "value": value,
            "timestamp": timestamp or now_iso(),
        }
    }


class SolarMLService:
    def __init__(self, args):
        self.args = args
        self.running = True
        self.model_version = "summer-school-ml-v1"

        self.influx = InfluxDBClient(
            url=args.influx_url,
            token=args.influx_token,
            org=args.influx_org,
        )
        self.query_api = self.influx.query_api()

        self.mqtt = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"openegiz-ml-service-{random.randint(1000, 9999)}",
            protocol=mqtt.MQTTv5,
        )

    def connect(self):
        print(f"Подключаемся к OpenEgiz MQTT: {self.args.mqtt_host}:{self.args.mqtt_port}")
        self.mqtt.connect(self.args.mqtt_host, self.args.mqtt_port, keepalive=60)
        self.mqtt.loop_start()

    def read_latest_values(self, thing_id):
        result = self.read_latest_values_from_influx(thing_id)
        if result:
            return result

        return self.read_latest_values_from_ditto(thing_id)

    def read_latest_values_from_influx(self, thing_id):
        field_filters = " or ".join([
            f'r["_field"] == "{field}"'
            for field in FIELDS.values()
        ])

        query = f'''
from(bucket: "{self.args.influx_bucket}")
  |> range(start: -10m)
  |> filter(fn: (r) => r["thingId"] == "{thing_id}")
  |> filter(fn: (r) => {field_filters})
  |> last()
'''

        result = {}

        tables = self.query_api.query(query, org=self.args.influx_org)
        for table in tables:
            for record in table.records:
                field = record.get_field()
                value = record.get_value()

                for short_name, influx_field in FIELDS.items():
                    if field == influx_field:
                        result[short_name] = value

        return result

    def read_latest_values_from_ditto(self, thing_id):
        url = f"{self.args.ditto_url.rstrip('/')}/api/2/things/{thing_id}/features"
        request = urllib.request.Request(url)

        credentials = f"{self.args.ditto_user}:{self.args.ditto_password}".encode("utf-8")
        auth_header = "Basic " + base64.b64encode(credentials).decode("ascii")
        request.add_header("Authorization", auth_header)

        with urllib.request.urlopen(request, timeout=10) as response:
            features = json.loads(response.read().decode("utf-8"))

        result = {}
        for short_name, feature_name in DITTO_FEATURES.items():
            value = (
                features
                .get(feature_name, {})
                .get("properties", {})
                .get("value")
            )
            if value is not None:
                result[short_name] = value

        return result

    def predict(self, values):
        actual = float(values.get("ac_power", 0) or 0)
        expected = float(values.get("expected_power", actual) or actual)
        performance_ratio = float(values.get("performance_ratio", 1) or 1)
        availability = float(values.get("availability", 100) or 100)
        curtailment = float(values.get("curtailment", 0) or 0)
        alarms = float(values.get("alarms", 0) or 0)
        irradiance = float(values.get("irradiance", 0) or 0)

        # Учебная модель.
        # В реальном проекте тут может быть sklearn/xgboost/lstm/api запрос к ML серверу.
        irradiance_factor = min(max(irradiance / 1000.0, 0.0), 1.2)
        operational_factor = max(0.0, availability / 100.0)
        curtailment_factor = max(0.0, 1.0 - curtailment / 100.0)

        predicted_power = expected * operational_factor * curtailment_factor

        if irradiance > 0:
            predicted_power = (predicted_power * 0.75) + (expected * irradiance_factor * 0.25)

        gap = expected - actual
        relative_gap = abs(gap) / max(expected, 1.0)

        anomaly_score = 0.0
        anomaly_score += min(relative_gap * 1.8, 0.55)
        anomaly_score += max(0.0, 0.98 - performance_ratio) * 4.0
        anomaly_score += max(0.0, 98.0 - availability) / 100.0
        anomaly_score += min(curtailment / 100.0, 0.2)
        anomaly_score += min(alarms * 0.25, 0.5)
        anomaly_score = round(min(max(anomaly_score, 0.0), 1.0), 3)

        predicted_power = round(predicted_power, 3)
        gap = round(gap, 3)

        if anomaly_score >= 0.75 or alarms >= 2:
            health_status = "critical"
            risk_level = "high"
            recommendation = "Check inverter/string performance and active alarms"
        elif anomaly_score >= 0.45 or alarms >= 1:
            health_status = "warning"
            risk_level = "medium"
            recommendation = "Monitor power gap and inspect site if trend continues"
        else:
            health_status = "normal"
            risk_level = "low"
            recommendation = "No action required"

        return {
            "ml_predicted_power_mw": predicted_power,
            "ml_expected_power_gap_mw": gap,
            "ml_anomaly_score": anomaly_score,
            "ml_health_status": health_status,
            "ml_risk_level": risk_level,
            "ml_recommendation": recommendation,
            "ml_model_version": self.model_version,
            "ml_last_run": now_iso(),
        }

    def publish_ml_result(self, thing_id, prediction):
        features = {
            name: feature(value)
            for name, value in prediction.items()
        }

        topic = f"telemetry/{thing_id}"
        message = build_ditto_message(thing_id, features)

        result = self.mqtt.publish(topic, json.dumps(message), qos=0)
        result.wait_for_publish(timeout=5)

    def run_once(self, thing_id):
        values = self.read_latest_values(thing_id)

        if not values:
            print(f"{thing_id}: нет данных в InfluxDB за последние 10 минут")
            return

        prediction = self.predict(values)
        self.publish_ml_result(thing_id, prediction)

        print(
            f"{datetime.now().strftime('%H:%M:%S')} {thing_id} | "
            f"pred={prediction['ml_predicted_power_mw']} MW | "
            f"gap={prediction['ml_expected_power_gap_mw']} MW | "
            f"anomaly={prediction['ml_anomaly_score']} | "
            f"health={prediction['ml_health_status']} | "
            f"risk={prediction['ml_risk_level']}"
        )

    def run(self):
        self.connect()

        things = [self.args.thing_id]

        try:
            while self.running:
                for thing_id in things:
                    self.run_once(thing_id)

                if self.args.once:
                    break

                time.sleep(self.args.interval)
        finally:
            self.stop()

    def stop(self):
        print("Останавливаем ML service...")
        self.mqtt.loop_stop()
        self.mqtt.disconnect()
        self.influx.close()


def main():
    parser = argparse.ArgumentParser(
        description="ML service: InfluxDB -> prediction/anomaly -> OpenEgiz"
    )
    parser.add_argument("--thing-id", default="summerschool:solar-site-001")
    parser.add_argument("--interval", type=float, default=15)
    parser.add_argument("--once", action="store_true")

    parser.add_argument("--influx-url", default=DEFAULT_INFLUX_URL)
    parser.add_argument("--influx-org", default=DEFAULT_INFLUX_ORG)
    parser.add_argument("--influx-bucket", default=DEFAULT_INFLUX_BUCKET)
    parser.add_argument("--influx-token", default=DEFAULT_INFLUX_TOKEN)

    parser.add_argument("--mqtt-host", default=DEFAULT_MQTT_HOST)
    parser.add_argument("--mqtt-port", type=int, default=DEFAULT_MQTT_PORT)
    parser.add_argument("--ditto-url", default=DEFAULT_DITTO_URL)
    parser.add_argument("--ditto-user", default=DEFAULT_DITTO_USER)
    parser.add_argument("--ditto-password", default=DEFAULT_DITTO_PASSWORD)

    args = parser.parse_args()

    service = SolarMLService(args)

    def handle_stop(sig, frame):
        service.running = False

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    service.run()


if __name__ == "__main__":
    main()
