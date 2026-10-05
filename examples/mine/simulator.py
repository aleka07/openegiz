#!/usr/bin/env python3
"""
Example Mine simulator for OpenEgiz.

A deliberately small open-pit haul cycle that drives the twins in twins.json:

    excavator loads a truck -> truck hauls ore to the crusher -> dumps
    -> returns empty -> queues at the excavator again

Every tick it publishes the twins' features to MQTT as Eclipse Ditto
protocol "modify" commands (topic telemetry/<thing-name>); Ditto updates the
twins, and the platform's own pipeline carries the events on to InfluxDB and
Grafana. The simulator never talks to Ditto or InfluxDB directly.

It is a baseline, not a model of a real mine: ore grade is a random walk,
speeds are constant with noise, there is no road network or blasting.
Contest submissions are expected to go far beyond it.
"""

import argparse
import json
import logging
import os
import random
import signal
import sys
import time

import paho.mqtt.client as mqtt

NAMESPACE = "org.openegiz.mine"
TOPIC_PREFIX = "telemetry"

# Haul cycle parameters (simulated seconds, km, km/h, tonnes).
ROUTE_KM = 3.2
SPEED_LOADED_KMH = 22.0
SPEED_EMPTY_KMH = 35.0
TRUCK_CAPACITY_T = 90.0
BUCKET_T = 22.0
PASS_SECONDS = 35.0
DUMP_SECONDS = 60.0
REFUEL_SECONDS = 600.0
REFUEL_BELOW_PCT = 15.0
FUEL_PCT_PER_KM_LOADED = 0.9
FUEL_PCT_PER_KM_EMPTY = 0.5
CRUSHER_WINDOW_S = 3600.0

log = logging.getLogger("mine")


class Truck:
    def __init__(self, name, start_km, fuel):
        self.name = name
        self.state = "queued_at_excavator"
        self.position_km = start_km
        self.payload_t = 0.0
        self.grade = 0.0
        self.speed_kmh = 0.0
        self.fuel_pct = fuel
        self.trips = 0
        self.timer = 0.0

    def features(self):
        return {
            "state": {"value": self.state},
            "payload": {"value": round(self.payload_t, 1), "unit": "t"},
            "speed": {"value": round(self.speed_kmh, 1), "unit": "km/h"},
            "route_position": {"value": round(self.position_km, 3), "unit": "km"},
            "fuel": {"value": round(self.fuel_pct, 1), "unit": "%"},
            "trips_total": {"value": self.trips, "unit": "trips"},
        }


class Mine:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.face_grade = 0.65
        self.excavator_state = "idle"
        self.passes_total = 0
        self.loading = None  # truck currently under the excavator
        self.dumping = None  # truck currently at the crusher
        self.crusher_tonnes = 0.0
        self.crusher_grade_tonnes = 0.0  # sum of grade * tonnes, for the average
        self.crusher_log = []  # (sim_time, tonnes) dumps inside the window
        self.sim_time = 0.0
        # Trucks start spread around the cycle so the dashboard is busy at once.
        self.trucks = [
            Truck("truck-01", 0.0, self.rng.uniform(70, 100)),
            Truck("truck-02", ROUTE_KM * 0.5, self.rng.uniform(70, 100)),
        ]
        self.trucks[1].state = "returning"

    # -- one simulated step ------------------------------------------------
    def step(self, dt):
        self.sim_time += dt
        self.face_grade = min(1.2, max(0.2, self.face_grade + self.rng.gauss(0, 0.004 * dt ** 0.5)))
        for truck in self.trucks:
            self._step_truck(truck, dt)
        self.crusher_log = [(t, w) for t, w in self.crusher_log if self.sim_time - t <= CRUSHER_WINDOW_S]

    def _step_truck(self, truck, dt):
        rng = self.rng
        if truck.state == "queued_at_excavator":
            truck.speed_kmh = 0.0
            if self.loading is None:
                self.loading = truck
                truck.state = "loading"
                truck.timer = 0.0
        elif truck.state == "loading":
            self.excavator_state = "loading"
            truck.timer += dt
            while truck.timer >= PASS_SECONDS and truck.payload_t < TRUCK_CAPACITY_T - 1:
                truck.timer -= PASS_SECONDS
                bucket = min(BUCKET_T * rng.uniform(0.9, 1.05), TRUCK_CAPACITY_T - truck.payload_t)
                # Grade of the load is the tonnage-weighted grade of its buckets.
                truck.grade = (truck.grade * truck.payload_t + self.face_grade * bucket) / (truck.payload_t + bucket)
                truck.payload_t += bucket
                self.passes_total += 1
            if truck.payload_t >= TRUCK_CAPACITY_T - 1:
                self.loading = None
                self.excavator_state = "idle"
                truck.state = "hauling"
        elif truck.state == "hauling":
            truck.speed_kmh = SPEED_LOADED_KMH * rng.uniform(0.85, 1.1)
            km = truck.speed_kmh * dt / 3600
            truck.position_km = min(ROUTE_KM, truck.position_km + km)
            truck.fuel_pct -= km * FUEL_PCT_PER_KM_LOADED
            if truck.position_km >= ROUTE_KM:
                truck.state = "queued_at_crusher"
        elif truck.state == "queued_at_crusher":
            truck.speed_kmh = 0.0
            if self.dumping is None:
                self.dumping = truck
                truck.state = "dumping"
                truck.timer = 0.0
        elif truck.state == "dumping":
            truck.timer += dt
            if truck.timer >= DUMP_SECONDS:
                self.crusher_tonnes += truck.payload_t
                self.crusher_grade_tonnes += truck.grade * truck.payload_t
                self.crusher_log.append((self.sim_time, truck.payload_t))
                truck.payload_t = 0.0
                truck.grade = 0.0
                truck.trips += 1
                self.dumping = None
                truck.state = "refueling" if truck.fuel_pct < REFUEL_BELOW_PCT else "returning"
                truck.timer = 0.0
        elif truck.state == "refueling":
            truck.timer += dt
            if truck.timer >= REFUEL_SECONDS:
                truck.fuel_pct = 100.0
                truck.state = "returning"
        elif truck.state == "returning":
            truck.speed_kmh = SPEED_EMPTY_KMH * rng.uniform(0.85, 1.1)
            km = truck.speed_kmh * dt / 3600
            truck.position_km = max(0.0, truck.position_km - km)
            truck.fuel_pct -= km * FUEL_PCT_PER_KM_EMPTY
            if truck.position_km <= 0.0:
                truck.state = "queued_at_excavator"

    # -- what gets published -------------------------------------------------
    def snapshot(self):
        avg_grade = self.crusher_grade_tonnes / self.crusher_tonnes if self.crusher_tonnes else 0.0
        window_t = sum(w for _, w in self.crusher_log)
        window_s = min(self.sim_time, CRUSHER_WINDOW_S) or 1.0
        hauling = sum(1 for t in self.trucks if t.state in ("hauling", "returning"))
        things = {
            "mine-01": {
                "tonnes_mined": {"value": round(self.crusher_tonnes, 1), "unit": "t"},
                "avg_grade": {"value": round(avg_grade, 3), "unit": "% Cu"},
                "trucks_hauling": {"value": hauling, "unit": "trucks"},
            },
            "excavator-01": {
                "state": {"value": self.excavator_state},
                "face_grade": {"value": round(self.face_grade, 3), "unit": "% Cu"},
                "passes_total": {"value": self.passes_total, "unit": "passes"},
            },
            "crusher-01": {
                "state": {"value": "crushing" if self.dumping else "idle"},
                "throughput": {"value": round(window_t * 3600 / window_s, 1), "unit": "t/h"},
                "feed_grade": {"value": round(avg_grade, 3), "unit": "% Cu"},
                "tonnes_total": {"value": round(self.crusher_tonnes, 1), "unit": "t"},
            },
        }
        for truck in self.trucks:
            things[truck.name] = truck.features()
        return things


def ditto_modify_features(name, features):
    """A Ditto protocol command replacing all features of one twin."""
    return {
        "topic": f"{NAMESPACE}/{name}/things/twin/commands/modify",
        "path": "/features",
        "value": {feature: {"properties": props} for feature, props in features.items()},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mqtt-host", default=os.environ.get("MQTT_HOST", "localhost"))
    p.add_argument("--mqtt-port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    p.add_argument("--interval", type=float, default=float(os.environ.get("SIM_INTERVAL", "2")),
                   help="real seconds between publishes (default 2)")
    p.add_argument("--speedup", type=float, default=float(os.environ.get("SIM_SPEEDUP", "10")),
                   help="simulated seconds per real second (default 10)")
    p.add_argument("--seed", type=int, default=int(os.environ.get("SIM_SEED", "42")))
    p.add_argument("--dry-run", action="store_true", help="print messages instead of publishing")
    p.add_argument("--steps", type=int, default=0, help="stop after N publishes (0 = run forever)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    mine = Mine(args.seed)

    client = None
    if not args.dry_run:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"openegiz-mine-sim-{os.getpid()}")
        for attempt in range(30):
            try:
                client.connect(args.mqtt_host, args.mqtt_port, keepalive=30)
                break
            except OSError as exc:
                log.warning("MQTT %s:%s not reachable (%s), retrying", args.mqtt_host, args.mqtt_port, exc)
                time.sleep(2)
        else:
            log.error("giving up on MQTT %s:%s", args.mqtt_host, args.mqtt_port)
            return 1
        client.loop_start()
        log.info("publishing to mqtt://%s:%s every %.1fs at %.0fx speed",
                 args.mqtt_host, args.mqtt_port, args.interval, args.speedup)

    stop = False

    def on_signal(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    published = 0
    while not stop:
        mine.step(args.interval * args.speedup)
        for name, features in mine.snapshot().items():
            message = json.dumps(ditto_modify_features(name, features))
            if client:
                client.publish(f"{TOPIC_PREFIX}/{name}", message, qos=0)
            else:
                print(message)
        published += 1
        if published % 30 == 0:
            snap = mine.snapshot()
            log.info("sim %5.0f min | crusher %7.1f t at %.3f %% Cu | %s",
                     mine.sim_time / 60, mine.crusher_tonnes, snap["mine-01"]["avg_grade"]["value"],
                     ", ".join(f"{t.name}:{t.state}" for t in mine.trucks))
        if args.steps and published >= args.steps:
            break
        time.sleep(args.interval)

    if client:
        client.loop_stop()
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
