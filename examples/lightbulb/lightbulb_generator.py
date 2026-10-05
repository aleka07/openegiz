#!/usr/bin/env python3
"""
Data generator for OpenTwins Lightbulb digital twin (summerschool:lightbulb-01).

Sends simulated telemetry data via MQTT (Mosquitto) using the Eclipse Ditto protocol.
Features: brightness, power_consumption, voltage, temperature.

Includes a simple HTTP endpoint to toggle the lightbulb state (on/off).
"""

import argparse
import json
import math
import os
import random
import signal
import subprocess
import sys
import time
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

import paho.mqtt.client as mqtt


# ── Default configuration ────────────────────────────────────────────
DEFAULT_MQTT_HOST = "localhost"
DEFAULT_MQTT_PORT = 30511
DEFAULT_THING_ID = "summerschool:lightbulb-01"
DEFAULT_INTERVAL = 5  # seconds
DEFAULT_HTTP_PORT = 8090


# ── Lightbulb simulator ─────────────────────────────────────────────

class LightbulbSimulator:
    """Simulates realistic parameters for a lightbulb."""

    def __init__(self):
        self._step = 0
        self._state = "on"  # "on" or "off"
        self._lock = threading.Lock()

        # Internal thermal state (for smooth transitions)
        self._current_temp = 25.0  # ambient
        self._current_brightness = 0.0

        # Lightbulb specs
        self._max_brightness = 800.0   # lumens
        self._max_power = 60.0         # watts
        self._max_temp = 85.0          # °C at full power
        self._ambient_temp = 25.0      # °C
        self._base_voltage = 220.0     # V

        # Flicker simulation period (steps)
        self._flicker_period = 40

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @state.setter
    def state(self, value: str):
        with self._lock:
            self._state = value

    def generate(self) -> dict:
        """Generate one set of readings."""
        self._step += 1
        t = self._step
        is_on = self.state == "on"

        # ── Voltage: grid fluctuations (~220V ± 2V) ──
        voltage = self._base_voltage + random.gauss(0, 1.5)
        voltage = round(max(210.0, min(235.0, voltage)), 1)

        # ── Brightness ──
        if is_on:
            # Target brightness with slight flicker effect
            flicker = 1.0 + 0.02 * math.sin(2 * math.pi * t / self._flicker_period)
            target = self._max_brightness * flicker + random.gauss(0, 5)
            # Smooth ramp-up
            self._current_brightness += (target - self._current_brightness) * 0.3
        else:
            # Smooth fade-out
            self._current_brightness *= 0.5

        brightness = round(max(0, min(self._max_brightness * 1.05, self._current_brightness)), 1)

        # ── Power consumption: proportional to brightness ──
        power_ratio = brightness / self._max_brightness if self._max_brightness > 0 else 0
        power_consumption = self._max_power * power_ratio + random.gauss(0, 0.3)
        power_consumption = round(max(0, min(self._max_power * 1.1, power_consumption)), 2)

        # ── Temperature: heats up when on, cools down when off ──
        if is_on:
            target_temp = self._ambient_temp + (self._max_temp - self._ambient_temp) * power_ratio
        else:
            target_temp = self._ambient_temp

        # Thermal inertia
        self._current_temp += (target_temp - self._current_temp) * 0.1
        self._current_temp += random.gauss(0, 0.3)
        temperature = round(max(self._ambient_temp - 2, min(self._max_temp + 5, self._current_temp)), 1)

        return {
            "brightness": brightness,
            "power_consumption": power_consumption,
            "voltage": voltage,
            "temperature": temperature,
        }


# ── Ditto protocol message builder ──────────────────────────────────

def build_ditto_message(thing_id: str, features: dict) -> dict:
    """
    Build an Eclipse Ditto protocol envelope to update all features.

    Topic format: {namespace}/{name}/things/twin/commands/modify
    Path: /features
    """
    namespace, name = thing_id.split(":", 1)
    now = datetime.now(timezone.utc).isoformat()

    ditto_features = {}
    for feat_name, feat_value in features.items():
        ditto_features[feat_name] = {
            "properties": {
                "value": feat_value,
                "timestamp": now,
            }
        }

    return {
        "topic": f"{namespace}/{name}/things/twin/commands/modify",
        "path": "/features",
        "value": ditto_features,
    }


# ── MQTT publisher ───────────────────────────────────────────────────

class MqttPublisher:
    """Publishes Ditto protocol messages to Mosquitto."""

    def __init__(self, host: str, port: int, thing_id: str):
        self.host = host
        self.port = port
        self.thing_id = thing_id
        self.topic = f"telemetry/{thing_id}"

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"lightbulb-gen-{random.randint(1000,9999)}",
            protocol=mqtt.MQTTv5,
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.connected = False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0 or (hasattr(rc, 'value') and rc.value == 0):
            self.connected = True
            print(f"✅ Подключено к MQTT брокеру {self.host}:{self.port}")
        else:
            print(f"❌ Ошибка подключения к MQTT: код={rc}")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self.connected = False
        print(f"⚠️  Отключено от MQTT брокера (код={rc})")

    def connect(self):
        """Connect to the MQTT broker."""
        print(f"🔌 Подключение к Mosquitto ({self.host}:{self.port})...")
        self.client.connect(self.host, self.port, keepalive=60)
        self.client.loop_start()
        for _ in range(10):
            if self.connected:
                break
            time.sleep(0.5)
        if not self.connected:
            print("❌ Не удалось подключиться к MQTT брокеру!")
            sys.exit(1)

    def publish(self, message: dict):
        """Publish a Ditto protocol message."""
        payload = json.dumps(message)
        result = self.client.publish(self.topic, payload, qos=0)
        result.wait_for_publish(timeout=5)

    def disconnect(self):
        """Disconnect from the broker."""
        self.client.loop_stop()
        self.client.disconnect()
        print("🔌 Отключено от MQTT брокера")


# ── HTTP API for state control ───────────────────────────────────────

class StateHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for lightbulb state control."""

    simulator: LightbulbSimulator = None  # set from main

    def do_GET(self):
        """GET /state — returns current state."""
        if self.path == "/state":
            self._json_response(200, {
                "thing_id": DEFAULT_THING_ID,
                "state": self.simulator.state,
            })
        elif self.path == "/health":
            self._json_response(200, {"status": "ok"})
        else:
            self._json_response(404, {"error": "Not found. Use GET/POST /state"})

    def do_POST(self):
        """POST /state — set state to on/off. Body: {"state": "on"} or {"state": "off"}"""
        if self.path == "/state":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                new_state = body.get("state", "").lower()

                if new_state not in ("on", "off"):
                    self._json_response(400, {"error": "Invalid state. Use 'on' or 'off'"})
                    return

                old_state = self.simulator.state
                self.simulator.state = new_state
                print(f"💡 Состояние: {old_state} → {new_state}")
                self._json_response(200, {
                    "thing_id": DEFAULT_THING_ID,
                    "previous_state": old_state,
                    "state": new_state,
                })
            except (json.JSONDecodeError, ValueError) as e:
                self._json_response(400, {"error": f"Invalid JSON: {e}"})
        else:
            self._json_response(404, {"error": "Not found. Use GET/POST /state"})

    def _json_response(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def log_message(self, format, *args):
        """Suppress default HTTP logs to keep console clean."""
        pass


def start_http_server(simulator: LightbulbSimulator, port: int):
    """Start a background HTTP server for state control."""
    StateHandler.simulator = simulator
    server = HTTPServer(("0.0.0.0", port), StateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"🌐 HTTP API запущен на порту {port}")
    print(f"   GET  http://localhost:{port}/state   — текущее состояние")
    print(f"   POST http://localhost:{port}/state   — переключить (body: {{\"state\": \"on/off\"}})")
    return server


# ── Main loop ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Генератор данных для цифрового двойника лампочки (OpenTwins)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python3 lightbulb_generator.py
  python3 lightbulb_generator.py --interval 2
  python3 lightbulb_generator.py --mqtt-host 192.168.1.100

Управление состоянием (в другом терминале):
  curl http://localhost:8090/state                              # Получить состояние
  curl -X POST -d '{"state":"off"}' http://localhost:8090/state # Выключить
  curl -X POST -d '{"state":"on"}'  http://localhost:8090/state # Включить
        """,
    )
    parser.add_argument(
        "--mqtt-host", default=DEFAULT_MQTT_HOST,
        help=f"Адрес MQTT-брокера (по умолчанию: {DEFAULT_MQTT_HOST})",
    )
    parser.add_argument(
        "--mqtt-port", type=int, default=DEFAULT_MQTT_PORT,
        help=f"Порт MQTT-брокера (по умолчанию: {DEFAULT_MQTT_PORT})",
    )
    parser.add_argument(
        "--thing-id", default=DEFAULT_THING_ID,
        help=f"ID вещи в Ditto (по умолчанию: {DEFAULT_THING_ID})",
    )
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL,
        help=f"Интервал отправки данных в секундах (по умолчанию: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--http-port", type=int, default=DEFAULT_HTTP_PORT,
        help=f"Порт HTTP API для управления состоянием (по умолчанию: {DEFAULT_HTTP_PORT})",
    )
    parser.add_argument(
        "--initial-state", default="on", choices=["on", "off"],
        help="Начальное состояние лампочки (по умолчанию: on)",
    )
    parser.add_argument(
        "--daemon", action="store_true",
        help="Запуск в фоновом режиме (логи → lightbulb_generator.log)",
    )
    parser.add_argument(
        "--stop", action="store_true",
        help="Остановить фоновый процесс",
    )

    args = parser.parse_args()

    # ── Handle --stop ──
    pid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lightbulb_generator.pid")
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lightbulb_generator.log")

    if args.stop:
        if os.path.exists(pid_file):
            with open(pid_file) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                os.remove(pid_file)
                print(f"🛑 Генератор остановлен (PID {pid})")
            except ProcessLookupError:
                os.remove(pid_file)
                print(f"⚠️  Процесс {pid} уже не существует, PID-файл удалён")
        else:
            print("⚠️  PID-файл не найден. Генератор не запущен?")
        return

    # ── Handle --daemon ──
    if args.daemon:
        cmd = [sys.executable] + [a for a in sys.argv if a != "--daemon"]
        with open(log_file, "a") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=lf, start_new_session=True)
        with open(pid_file, "w") as f:
            f.write(str(proc.pid))
        print(f"🚀 Генератор запущен в фоне (PID {proc.pid})")
        print(f"   📄 Логи: {log_file}")
        print(f"   🛑 Остановить: python3 {sys.argv[0]} --stop")
        return

    # Setup simulator
    simulator = LightbulbSimulator()
    simulator.state = args.initial_state

    # Setup MQTT
    publisher = MqttPublisher(args.mqtt_host, args.mqtt_port, args.thing_id)

    # Graceful shutdown
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        print("\n🛑 Остановка генератора...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start HTTP server
    http_server = start_http_server(simulator, args.http_port)

    # Connect MQTT
    publisher.connect()

    print(f"\n💡 Генератор данных для лампочки:")
    print(f"   📡 {args.thing_id} → telemetry/{args.thing_id}")
    print(f"   ⏱️  Интервал: {args.interval}с")
    print(f"   🔆 Начальное состояние: {args.initial_state}")
    header = f"{'Время':<12} {'Состояние':<10} {'Яркость(lm)':<14} {'Мощн.(Вт)':<12} {'Напр.(В)':<10} {'Темп.(°C)':<10}"
    print(f"{'─' * len(header)}")
    print(header)
    print(f"{'─' * len(header)}")

    count = 0
    try:
        while running:
            ts = datetime.now().strftime("%H:%M:%S")

            # Generate data
            readings = simulator.generate()

            # Build & publish Ditto message
            message = build_ditto_message(args.thing_id, readings)
            publisher.publish(message)

            count += 1
            state_icon = "🟢" if simulator.state == "on" else "🔴"
            print(
                f"{ts:<12} "
                f"{state_icon} {simulator.state:<7} "
                f"{readings['brightness']:<14} "
                f"{readings['power_consumption']:<12} "
                f"{readings['voltage']:<10} "
                f"{readings['temperature']:<10}"
            )

            time.sleep(args.interval)

    finally:
        publisher.disconnect()
        http_server.shutdown()
        print(f"\n📊 Всего отправлено сообщений: {count}")


if __name__ == "__main__":
    main()
