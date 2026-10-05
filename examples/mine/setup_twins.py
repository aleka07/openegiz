#!/usr/bin/env python3
"""Create or update the Example Mine twins in Ditto (idempotent PUTs)."""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

DITTO_URL = os.environ.get("DITTO_URL", "http://localhost:8080").rstrip("/")
DITTO_USER = os.environ.get("DITTO_USER", "ditto")
DITTO_PASSWORD = os.environ["DITTO_PASSWORD"]
TWINS_FILE = os.environ.get("TWINS_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "twins.json"))

AUTH = "Basic " + base64.b64encode(f"{DITTO_USER}:{DITTO_PASSWORD}".encode()).decode()


def put(thing_id, body):
    request = urllib.request.Request(
        f"{DITTO_URL}/api/2/things/{thing_id}",
        data=json.dumps(body).encode(),
        method="PUT",
        headers={"Authorization": AUTH, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status


def main():
    twins = json.load(open(TWINS_FILE))
    # The parent must exist before children reference it, so create in file order.
    for thing_id, body in twins.items():
        for attempt in range(20):
            try:
                status = put(thing_id, body)
                print(f"{'created' if status == 201 else 'updated'}  {thing_id}")
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 19:
                    print(f"FAILED   {thing_id}: {exc}", file=sys.stderr)
                    return 1
                time.sleep(3)
    print(f"{len(twins)} twins ready in {DITTO_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
