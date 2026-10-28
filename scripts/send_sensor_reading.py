"""Push a test reading through the authenticated ingestion API, as a field gateway would.

Usage: FIELD_GATEWAY_INGEST_KEY=... python scripts/send_sensor_reading.py AGM-03-SOIL 31.2 [--url http://localhost:8000]
Readings are stored with origin OBSERVED because they arrive through the gateway path; use only test values.
"""
import argparse
import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

parser = argparse.ArgumentParser()
parser.add_argument("sensor_id")
parser.add_argument("value", type=float)
parser.add_argument("--url", default="http://localhost:8000")
parser.add_argument("--source", default="FIELD-GATEWAY-01")
args = parser.parse_args()
key = os.environ.get("FIELD_GATEWAY_INGEST_KEY")
if not key:
    raise SystemExit("Set FIELD_GATEWAY_INGEST_KEY (printed by the seed script, or set in .env before seeding).")
body = {"readings": [{"sensor_id": args.sensor_id, "value": args.value,
                      "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "idempotency_key": f"cli-{uuid.uuid4().hex}"}]}
req = urllib.request.Request(f"{args.url}/api/ingestion/{args.source}", data=json.dumps(body).encode(), method="POST",
                             headers={"Content-Type": "application/json", "X-HDEWS-Ingest-Key": key})
try:
    with urllib.request.urlopen(req) as resp:
        print(resp.status, resp.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
