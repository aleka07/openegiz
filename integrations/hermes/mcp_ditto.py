#!/usr/bin/env python3
"""MCP server exposing the Eclipse Ditto digital twin of the OpenEgiz stack.

Transport: stdio (spawned by Hermes as a subprocess).

Two different write paths are exposed on purpose, and the difference matters:

  * ``set_feature_property`` writes STRAIGHT INTO THE TWIN over the Ditto REST
    API. Nothing is simulated, no device is involved, and the value does not
    travel through MQTT/Telegraf, so it does NOT land in InfluxDB.
  * ``publish_telemetry`` PRETENDS TO BE A DEVICE: it publishes a Ditto
    Protocol envelope to MQTT, Ditto's source connection applies it to the
    twin, and the resulting change is forwarded to Telegraf -> InfluxDB. This
    is the realistic path and the one that produces history.

Configuration (env vars, all optional, defaults match the gx10-11 host):
    DITTO_URL       default http://localhost:30525/api/2
    DITTO_USER      default ditto
    DITTO_PASSWORD  default ditto
    MQTT_HOST       default localhost
    MQTT_PORT       default 30511
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests  # noqa: E402
from fastmcp import FastMCP  # noqa: E402

from _env import load_env_file  # noqa: E402

load_env_file()

DITTO_URL = os.environ.get("DITTO_URL", "http://localhost:30525/api/2").rstrip("/")
DITTO_AUTH = (
    os.environ.get("DITTO_USER", "ditto"),
    os.environ.get("DITTO_PASSWORD", "ditto"),
)
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "30511"))
HTTP_TIMEOUT = float(os.environ.get("DITTO_TIMEOUT", "15"))

mcp = FastMCP("openegiz-ditto")


def _get(path: str) -> Any:
    r = requests.get(f"{DITTO_URL}{path}", auth=DITTO_AUTH, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _parse_value(value: str) -> Any:
    """Interpret a value the model passed as a string.

    '50.5' -> 50.5, 'true' -> True, '{"a":1}' -> dict, 'idle' -> 'idle'.
    """
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


@mcp.tool
def list_things() -> str:
    """List every digital twin (Thing) registered in Eclipse Ditto.

    Use this first when the user does not name a specific thing, or to check
    that a thing ID they mentioned actually exists.

    Returns one line per thing: the thing ID, then its feature names.
    """
    try:
        data = _get("/search/things?option=size(200)")
    except Exception as exc:  # noqa: BLE001
        return f"ERROR querying Ditto: {exc}"

    items = data.get("items", [])
    if not items:
        return "No things found in Ditto."

    lines = [f"{len(items)} thing(s):"]
    for item in items:
        features = ", ".join((item.get("features") or {}).keys()) or "(no features)"
        lines.append(f"  {item.get('thingId')}  features: {features}")
    return "\n".join(lines)


@mcp.tool
def get_thing(thing_id: str) -> str:
    """Get the complete current state of one digital twin from Ditto.

    Returns the full JSON document: policyId, attributes and every feature
    with all of its properties. Use get_feature instead when you only need
    one feature — the output is much shorter.

    Args:
        thing_id: Ditto thing ID, namespace and name separated by a colon,
            e.g. "test:winterschool-1".
    """
    try:
        return json.dumps(_get(f"/things/{thing_id}"), indent=2)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return f"ERROR: thing '{thing_id}' does not exist in Ditto."
        return f"ERROR reading thing '{thing_id}': {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR reading thing '{thing_id}': {exc}"


@mcp.tool
def get_feature(thing_id: str, feature: str) -> str:
    """Read the CURRENT value of one feature of a digital twin.

    This is the tool to use for questions like "what is the current
    temperature of thing X" — it returns the live twin state, not history.
    For history over time use the InfluxDB telemetry tools instead.

    Args:
        thing_id: Ditto thing ID, e.g. "test:winterschool-1".
        feature: Feature name, e.g. "temperature".

    Returns the feature's properties as JSON, typically
    {"properties": {"value": 46.1, "timestamp": "..."}}.
    """
    try:
        return json.dumps(_get(f"/things/{thing_id}/features/{feature}"), indent=2)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return (
                f"ERROR: thing '{thing_id}' has no feature '{feature}' "
                f"(or the thing does not exist). Call list_things or get_thing to check."
            )
        return f"ERROR reading feature: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR reading feature: {exc}"


@mcp.tool
def set_feature_property(thing_id: str, feature: str, prop_path: str, value: str) -> str:
    """Write a value DIRECTLY into the digital twin via the Ditto REST API.

    This is an administrative twin edit: it changes the twin state immediately
    but does NOT go through MQTT, so it is NOT stored as telemetry history in
    InfluxDB. To simulate a real device reading, use publish_telemetry instead.

    Args:
        thing_id: Ditto thing ID, e.g. "test:winterschool-1".
        feature: Feature name, e.g. "temperature".
        prop_path: Property path inside the feature, e.g. "value" or
            "status/mode" for a nested property.
        value: The value as a JSON literal. "50.5" writes the number 50.5,
            "true" writes a boolean, "\\"idle\\"" writes the string idle.
            A bare word that is not valid JSON is written as a string.
    """
    parsed = _parse_value(value)
    url = f"{DITTO_URL}/things/{thing_id}/features/{feature}/properties/{prop_path.strip('/')}"
    try:
        r = requests.put(
            url,
            auth=DITTO_AUTH,
            headers={"Content-Type": "application/json"},
            data=json.dumps(parsed),
            timeout=HTTP_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return f"ERROR writing to Ditto: {exc}"

    if r.status_code in (200, 201, 204):
        return (
            f"OK: {thing_id}/features/{feature}/properties/{prop_path} = "
            f"{json.dumps(parsed)} (HTTP {r.status_code}). "
            "Twin updated directly; this write is not in the telemetry history."
        )
    return f"ERROR: Ditto returned HTTP {r.status_code}: {r.text[:400]}"


@mcp.tool
def publish_telemetry(thing_id: str, feature: str, value: float) -> str:
    """Simulate a device sending a telemetry reading, over MQTT.

    Publishes a Ditto Protocol envelope to MQTT topic telemetry/<thing_id>.
    Ditto's source connection applies it to the twin, and the change is then
    forwarded to Telegraf and stored in InfluxDB. Use this whenever the user
    asks to "publish", "send", "simulate" or "report" a measurement — it is
    the realistic device path and the only one that creates history.

    The twin is updated asynchronously (typically well under a second). If you
    then need to confirm the new value, call get_feature afterwards.

    Args:
        thing_id: Ditto thing ID, e.g. "test:winterschool-1". The thing must
            already exist — this path does not create new things.
        feature: Feature name, e.g. "temperature".
        value: Numeric measurement, e.g. 50.5.
    """
    try:
        import paho.mqtt.publish as mqtt_publish
    except ImportError as exc:  # noqa: BLE001
        return f"ERROR: paho-mqtt is not installed in the MCP server venv: {exc}"

    if ":" not in thing_id:
        return (
            f"ERROR: '{thing_id}' is not a valid Ditto thing ID — "
            "it must be '<namespace>:<name>', e.g. 'test:winterschool-1'."
        )
    namespace, name = thing_id.split(":", 1)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    envelope = {
        # NOTE: the envelope topic uses '/' between namespace and name,
        # while the thing ID uses ':'. Getting this wrong silently drops the message.
        "topic": f"{namespace}/{name}/things/twin/commands/modify",
        "path": "/features",
        "value": {feature: {"properties": {"value": value, "timestamp": timestamp}}},
    }
    try:
        mqtt_publish.single(
            topic=f"telemetry/{thing_id}",
            payload=json.dumps(envelope),
            hostname=MQTT_HOST,
            port=MQTT_PORT,
            qos=1,
        )
    except Exception as exc:  # noqa: BLE001
        return f"ERROR publishing to MQTT {MQTT_HOST}:{MQTT_PORT}: {exc}"

    return (
        f"OK: published {feature}={value} for {thing_id} to MQTT topic "
        f"telemetry/{thing_id} at {timestamp}. The twin and InfluxDB update "
        "asynchronously; call get_feature to confirm."
    )


if __name__ == "__main__":
    mcp.run(show_banner=False)
