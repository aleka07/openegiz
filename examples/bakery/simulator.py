#!/usr/bin/env python3
"""Virtual bakery production line for OpenEgiz.

Simulates a four-station bakery line and feeds the OpenEgiz stack with two
independent MQTT streams:

  1. TELEMETRY  -> topic  telemetry/<thingId>   (Eclipse Ditto Protocol envelopes)
     Continuous sensor readings per station. Ditto applies them to the twin,
     the twin change is republished on opentwins/#, Telegraf writes it to
     InfluxDB measurement `mqtt_consumer`.

  2. BATCH EVENTS -> topic  bakery/events       (plain JSON, one event per line)
     The process event log: case_id / activity / station / ts. Telegraf writes
     it to InfluxDB measurement `batch_events` with case_id, activity, station
     and mode as tags. This is the log pm4py and JaamSim consume.

The line is a queueing system with limited station capacity, so a real
bottleneck forms at the oven (capacity 1, longest service time). That is
deliberate: process mining must have something to discover.

Only third-party dependency: paho-mqtt.

Usage:
    python3 simulator.py --batches 20 --speedup 200 --mode normal
    python3 simulator.py --batches 6 --speedup 200 --mode dirty --case-start 101
"""

import argparse
import heapq
import itertools
import json
import math
import random
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

# --------------------------------------------------------------------------
# Line configuration — tune the process here.
# Durations are in SIMULATED minutes. --speedup only changes how fast the
# simulated clock runs against the wall clock; it never changes the process.
# --------------------------------------------------------------------------

NAMESPACE = "bakery"

# station -> capacity (how many batches fit at once), mean service time,
# and the activity name pair written into the event log.
STATIONS = {
    "mixer-1":   {"capacity": 1, "duration_min":  8.0, "activity": "Mixing"},
    "proofer-1": {"capacity": 3, "duration_min": 40.0, "activity": "Proofing"},
    "oven-1":    {"capacity": 1, "duration_min": 25.0, "activity": "Baking"},
    "packer-1":  {"capacity": 1, "duration_min":  5.0, "activity": "Packing"},
}

# Order the batches travel through the line.
ROUTE = ["mixer-1", "proofer-1", "oven-1", "packer-1"]

# A new batch is released to the line every ARRIVAL_INTERVAL_MIN simulated
# minutes. 12 min < the oven's 25 min service time, so work piles up in front
# of the oven — that is the bottleneck the course is supposed to find.
ARRIVAL_INTERVAL_MIN = 12.0

# Relative lognormal-ish spread applied to every service time and interarrival.
DURATION_JITTER = 0.12

# --mode sparse: these stations only report that work STARTED — the operator
# never confirms completion. Produces an incomplete but still minable log.
SPARSE_STARTED_ONLY = ("proofer-1", "packer-1")

# --mode dirty: probability that any single event is simply never recorded.
DIRTY_DROP_PROB = 0.15

# --------------------------------------------------------------------------
# Telemetry model — per-station sensor behaviour.
# --------------------------------------------------------------------------

# Thermal/mechanical inertia is expressed as a TIME CONSTANT in simulated
# minutes, not as a per-tick factor: --speedup changes how often telemetry is
# sampled, and a per-tick factor would silently make the oven heat faster on a
# faster run. tau = the time to cover ~63% of the gap to the setpoint.
OVEN_TEMP_IDLE = 175.0      # standby setpoint, °C
OVEN_TEMP_BAKING = 231.0    # setpoint while a batch is inside, °C
OVEN_TAU_MIN = 4.0          # oven thermal time constant, simulated minutes
OVEN_DOOR_DROP = 18.0       # instant loss when a batch is loaded/unloaded, °C

MIXER_LOAD_IDLE = 3.0       # motor load, %
MIXER_LOAD_MIXING = 68.0
MIXER_LOAD_TAU_MIN = 0.5
MIXER_DOUGH_TEMP_IDLE = 21.5
MIXER_DOUGH_TEMP_MIXING = 27.5
MIXER_DOUGH_TAU_MIN = 2.5

PROOFER_TEMP = 30.0         # °C
PROOFER_HUMIDITY = 82.0     # %

PACKER_THROUGHPUT = 24.0    # packs per minute while packing
PACKER_TAU_MIN = 0.4


def iso(dt):
    """ISO8601 UTC with a trailing Z, second resolution."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ditto_topic(thing_id):
    """bakery:oven-1 -> bakery/oven-1 (Ditto Protocol uses '/', thing ids ':')."""
    return thing_id.replace(":", "/", 1)


class Publisher:
    """Thin MQTT wrapper. --dry-run turns every publish into a no-op print."""

    def __init__(self, host, port, dry_run=False, verbose=False):
        self.dry_run = dry_run
        self.verbose = verbose
        self.sent_telemetry = 0
        self.sent_events = 0
        self.client = None
        if dry_run:
            return
        # paho 2.x requires the callback API version; 1.x does not know it.
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                      client_id="bakery-simulator")
        except AttributeError:  # paho-mqtt 1.x
            self.client = mqtt.Client(client_id="bakery-simulator")
        self.client.connect(host, port, keepalive=60)
        self.client.loop_start()

    def publish(self, topic, payload, is_event=False):
        body = json.dumps(payload, separators=(",", ":"))
        if is_event:
            self.sent_events += 1
        else:
            self.sent_telemetry += 1
        if self.dry_run:
            if self.verbose or is_event:
                print(f"  [dry-run] {topic} {body}")
            return
        self.client.publish(topic, body, qos=1)
        if self.verbose:
            print(f"  -> {topic} {body}")

    def close(self):
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()


class Station:
    def __init__(self, name, cfg):
        self.name = name
        self.capacity = cfg["capacity"]
        self.duration_min = cfg["duration_min"]
        self.activity = cfg["activity"]
        self.queue = []      # batches waiting
        self.busy = []       # batches in service
        self.processed = 0

    @property
    def free(self):
        return self.capacity - len(self.busy)


class Batch:
    def __init__(self, case_id):
        self.case_id = case_id
        self.stage = -1      # index into ROUTE
        self.entered_queue_at = {}


class BakerySim:
    def __init__(self, args):
        self.args = args
        self.rng = random.Random(args.seed)
        self.mode = args.mode

        self.stations = {n: Station(n, c) for n, c in STATIONS.items()}
        self.events = []                  # heap of (sim_seconds, seq, fn)
        self._seq = itertools.count()
        self.now = 0.0                    # simulated seconds since start
        self.wall_start = datetime.now(timezone.utc)

        self.batches_started = 0
        self.batches_completed = 0
        self.wip = 0
        self.event_seq = 0
        self.emitted = 0
        self.dropped = 0

        # telemetry state
        self.oven_temp = OVEN_TEMP_IDLE
        self.mixer_load = MIXER_LOAD_IDLE
        self.dough_temp = MIXER_DOUGH_TEMP_IDLE
        self.packer_rate = 0.0
        self.last_telemetry_at = 0.0

        self.pub = Publisher(args.mqtt_host, args.mqtt_port,
                             dry_run=args.dry_run, verbose=args.verbose)
        self.stopping = False

    # ---------------- simulated clock ----------------

    def sim_clock(self):
        """Wall-clock timestamp the simulated process would have."""
        return self.wall_start + timedelta(seconds=self.now)

    def jitter(self, mean_min):
        return max(0.2, self.rng.lognormvariate(math.log(mean_min), DURATION_JITTER)) * 60.0

    def schedule(self, delay_sec, fn):
        heapq.heappush(self.events, (self.now + delay_sec, next(self._seq), fn))

    # ---------------- event log ----------------

    def keep_event(self, station, activity):
        """Apply the mode's data-quality damage. True = record the event."""
        if self.mode == "sparse":
            return not (station in SPARSE_STARTED_ONLY and activity.endswith("Done"))
        if self.mode == "dirty":
            return self.rng.random() >= DIRTY_DROP_PROB
        return True

    def emit_event(self, batch, station, activity):
        st = self.stations[station]
        if not self.keep_event(station, activity):
            self.dropped += 1
            print(f"[{self.hhmm()}] {batch.case_id:<12} {activity:<15} {station:<10} "
                  f"(NOT RECORDED — {self.mode} mode)")
            return
        self.event_seq += 1
        self.emitted += 1
        payload = {
            "case_id": batch.case_id,
            "activity": activity,
            "station": station,
            "ts": iso(self.sim_clock()),
            "mode": self.mode,
            "run_id": self.args.run_id,
            "seq": self.event_seq,
            "queue_len": len(st.queue),
            "wip": self.wip,
        }
        self.pub.publish("bakery/events", payload, is_event=True)
        print(f"[{self.hhmm()}] {batch.case_id:<12} {activity:<15} {station:<10} "
              f"queue={len(st.queue)} wip={self.wip}")

    def hhmm(self):
        total = int(self.now)
        return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"

    # ---------------- line mechanics ----------------

    def arrive(self, batch):
        if self.stopping:
            return
        self.batches_started += 1
        self.wip += 1
        self.enqueue(batch, 0)

    def enqueue(self, batch, stage):
        batch.stage = stage
        station = self.stations[ROUTE[stage]]
        batch.entered_queue_at[station.name] = self.now
        station.queue.append(batch)
        self.try_start(station)

    def try_start(self, station):
        while station.free > 0 and station.queue:
            batch = station.queue.pop(0)
            station.busy.append(batch)
            if station.name == "oven-1":
                self.oven_door()
            self.emit_event(batch, station.name, station.activity + "Started")
            dur = self.jitter(station.duration_min)
            self.schedule(dur, lambda b=batch, s=station: self.finish(b, s))

    def finish(self, batch, station):
        station.busy.remove(batch)
        station.processed += 1
        if station.name == "oven-1":
            self.oven_door()
        self.emit_event(batch, station.name, station.activity + "Done")
        nxt = batch.stage + 1
        if nxt < len(ROUTE):
            self.enqueue(batch, nxt)
        else:
            self.batches_completed += 1
            self.wip -= 1
        self.try_start(station)

    # ---------------- telemetry ----------------

    def modify_features(self, thing_name, features):
        thing_id = f"{NAMESPACE}:{thing_name}"
        ts = iso(self.sim_clock())
        value = {k: {"properties": {"value": v, "timestamp": ts}}
                 for k, v in features.items()}
        self.pub.publish(
            f"telemetry/{thing_id}",
            {"topic": f"{ditto_topic(thing_id)}/things/twin/commands/modify",
             "path": "/features",
             "value": value},
        )

    @staticmethod
    def approach(current, target, tau_min, dt_min):
        """First-order lag: move `current` toward `target` over dt simulated
        minutes. Independent of --speedup, because dt is in simulated time."""
        alpha = 1.0 - math.exp(-dt_min / tau_min) if tau_min > 0 else 1.0
        return current + (target - current) * alpha

    def telemetry_tick(self):
        r = self.rng
        mixer, proofer, oven, packer = (self.stations[n] for n in ROUTE)
        dt_min = max(0.001, (self.now - self.last_telemetry_at) / 60.0)
        self.last_telemetry_at = self.now

        # Mixer: motor draws current only while dough is in the bowl.
        mixing = bool(mixer.busy)
        self.mixer_load = self.approach(
            self.mixer_load, MIXER_LOAD_MIXING if mixing else MIXER_LOAD_IDLE,
            MIXER_LOAD_TAU_MIN, dt_min) + r.gauss(0, 1.4)
        self.mixer_load = max(0.0, self.mixer_load)
        self.dough_temp = self.approach(
            self.dough_temp,
            MIXER_DOUGH_TEMP_MIXING if mixing else MIXER_DOUGH_TEMP_IDLE,
            MIXER_DOUGH_TAU_MIN, dt_min) + r.gauss(0, 0.12)
        self.modify_features("mixer-1", {
            "motor_load": round(self.mixer_load, 2),
            "dough_temp": round(self.dough_temp, 2),
        })

        # Proofer: climate chamber, drifts slightly with how full it is.
        load = len(proofer.busy) / proofer.capacity
        self.modify_features("proofer-1", {
            "temp": round(PROOFER_TEMP + 0.8 * load + r.gauss(0, 0.25), 2),
            "humidity": round(PROOFER_HUMIDITY + 2.5 * load + r.gauss(0, 0.9), 2),
        })

        # Oven: temperature follows the setpoint with lag, so it visibly
        # correlates with whether a batch is actually being baked.
        target = OVEN_TEMP_BAKING if oven.busy else OVEN_TEMP_IDLE
        self.oven_temp = self.approach(self.oven_temp, target,
                                       OVEN_TAU_MIN, dt_min) + r.gauss(0, 0.9)
        self.modify_features("oven-1", {"temp": round(self.oven_temp, 2)})

        # Packer: throughput is zero unless something is being packed.
        target_rate = PACKER_THROUGHPUT if packer.busy else 0.0
        self.packer_rate = self.approach(self.packer_rate, target_rate,
                                         PACKER_TAU_MIN, dt_min) + r.gauss(0, 0.5)
        self.packer_rate = max(0.0, self.packer_rate)
        self.modify_features("packer-1", {"throughput": round(self.packer_rate, 2)})

        # Line-level counters — the business view of the same process.
        self.modify_features("line", {
            "batches_started": self.batches_started,
            "batches_completed": self.batches_completed,
            "wip": self.wip,
        })

        if not self.stopping:
            self.schedule(self.args.telemetry_interval * self.args.speedup,
                          self.telemetry_tick)

    def oven_door(self):
        """Loading/unloading the oven costs heat — makes the curve believable."""
        self.oven_temp -= OVEN_DOOR_DROP

    # ---------------- run ----------------

    def run(self):
        a = self.args
        print(f"Bakery line simulator — mode={a.mode} batches={a.batches} "
              f"speedup={a.speedup}x seed={a.seed} run_id={a.run_id}")
        print(f"Cases: {a.case_prefix}-{a.case_start:04d} .. "
              f"{a.case_prefix}-{a.case_start + a.batches - 1:04d}")
        print(f"MQTT: {a.mqtt_host}:{a.mqtt_port}"
              + ("  (DRY RUN — nothing is published)" if a.dry_run else ""))
        print(f"Route: {' -> '.join(ROUTE)}   "
              + "  ".join(f"{n}(cap {c['capacity']}, {c['duration_min']:g}m)"
                          for n, c in STATIONS.items()))
        print("-" * 78)

        # Release the batches.
        t = 0.0
        for i in range(a.batches):
            case_id = f"{a.case_prefix}-{a.case_start + i:04d}"
            self.schedule(t, lambda b=Batch(case_id): self.arrive(b))
            t += self.jitter(ARRIVAL_INTERVAL_MIN)

        self.schedule(0.0, self.telemetry_tick)

        t0 = time.monotonic()
        try:
            while self.events:
                sim_t, _, fn = heapq.heappop(self.events)
                # Sleep the real time that corresponds to the simulated gap.
                target_wall = t0 + sim_t / a.speedup
                delay = target_wall - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                self.now = sim_t
                fn()
                if self.batches_completed >= a.batches:
                    # Drain remaining telemetry ticks: stop rescheduling and
                    # send one last snapshot so the final counters land.
                    self.stopping = True
                    self.events = []
                    self.telemetry_tick()
                    break
        except KeyboardInterrupt:
            print("\nInterrupted — flushing.")
        finally:
            time.sleep(1.0)  # let paho drain its outbound queue
            self.pub.close()

        print("-" * 78)
        elapsed = time.monotonic() - t0
        print(f"Simulated {self.hhmm()} of production in {elapsed:.1f}s real time.")
        print(f"Batches started={self.batches_started} completed={self.batches_completed}")
        print(f"Events recorded={self.emitted} dropped={self.dropped} "
              f"({self.mode} mode)")
        print(f"MQTT messages: telemetry={self.pub.sent_telemetry} "
              f"events={self.pub.sent_events}")
        for name in ROUTE:
            st = self.stations[name]
            print(f"  {name:<10} processed={st.processed:<4} "
                  f"still queued={len(st.queue)} in service={len(st.busy)}")


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Virtual bakery production line -> MQTT (telemetry + event log)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--mqtt-host", default="localhost")
    p.add_argument("--mqtt-port", type=int, default=30511)
    p.add_argument("--batches", type=int, default=20,
                   help="how many batches to push through the line")
    p.add_argument("--speedup", type=float, default=1.0,
                   help="simulated seconds per real second; 200 turns a "
                        "9-hour shift into ~3 minutes")
    p.add_argument("--mode", choices=("normal", "sparse", "dirty"), default="normal",
                   help="normal=complete log, sparse=Done events missing on "
                        f"{'/'.join(SPARSE_STARTED_ONLY)}, "
                        f"dirty={int(DIRTY_DROP_PROB * 100)}%% of all events lost")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--case-prefix", default="batch")
    p.add_argument("--case-start", type=int, default=1,
                   help="first case number; use a distinct range per dataset")
    p.add_argument("--run-id", default=None,
                   help="free-form label stored on every event (default: mode+seed)")
    p.add_argument("--telemetry-interval", type=float, default=2.0,
                   help="REAL seconds between telemetry publishes; one sample "
                        "therefore covers interval*speedup simulated seconds, "
                        "so keep it <= 1.0 at speedup 200 if you want the oven "
                        "heating curve to be legible")
    p.add_argument("--dry-run", action="store_true",
                   help="run the simulation, publish nothing")
    p.add_argument("--verbose", action="store_true",
                   help="print every MQTT message")
    args = p.parse_args(argv)
    if args.run_id is None:
        args.run_id = f"{args.mode}-{args.seed}"
    return args


def main():
    args = parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    BakerySim(args).run()


if __name__ == "__main__":
    main()
