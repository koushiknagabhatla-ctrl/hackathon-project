"""Live real-time telemetry streaming script.

Continuously generates and POSTs real-time SCADA telemetry, rainfall rates,
and pump status readings into the live Auralis ingestion gateway at http://localhost:8000/v1/events.

Usage:
    python scripts/stream_realtime_events.py [--interval 3.0]
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
from datetime import datetime, timezone

BASE_URL = "http://127.0.0.1:8000/v1/events"
HEADERS = {
    "Content-Type": "application/json",
    "X-Auralis-Principal": "p_operator",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def post_event(connector_id: str, kind: str, payload: dict, coords: list[float]) -> dict:
    body = {
        "connector_id": connector_id,
        "kind": kind,
        "event_time": _now(),
        "payload": payload,
        "geometry": {"type": "Point", "coordinates": coords},
    }
    req = urllib.request.Request(BASE_URL, data=json.dumps(body).encode(), headers=HEADERS)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def main():
    parser = argparse.ArgumentParser(description="Stream live telemetry to Auralis")
    parser.add_argument("--interval", type=float, default=4.0, help="Seconds between telemetry beats")
    args = parser.parse_args()

    print(f"[*] Starting live real-time telemetry streaming (cadence: {args.interval}s)...")
    print(f"[*] Ingestion Target: {BASE_URL}")

    base_stage = 4.82
    base_rain = 22.0

    beat = 1
    while True:
        try:
            # 1. Fluctuating Hydrology SCADA Gauge
            delta = random.uniform(-0.02, 0.05)
            base_stage = max(3.5, min(6.5, base_stage + delta))
            flow = 1400.0 + (base_stage - 4.0) * 200.0
            res_gauge = post_event(
                "conn_hydro_scada",
                "water_level",
                {"asset_id": "ast_gate_bd04", "level_m": round(base_stage, 3), "flow_m3s": round(flow, 1)},
                [80.6113, 16.5498],
            )
            print(f"[Beat {beat:04d}] Hydrology SCADA -> Stage: {base_stage:.2f}m | Evidence ID: {res_gauge.get('evidence_id')}")

            # 2. IMD Rainfall Telemetry
            rain_rate = max(5.0, base_rain + random.uniform(-2.0, 3.0))
            res_rain = post_event(
                "conn_imd",
                "rainfall",
                {"rate_mm_h": round(rain_rate, 1), "accum_mm": 72.5},
                [80.6200, 16.5300],
            )

            # 3. Pump House Status
            if beat % 3 == 0:
                res_pump = post_event(
                    "conn_scada_pumps",
                    "asset_state",
                    {"asset_id": "ast_pump_p12", "units_running": 3 if base_stage > 5.0 else 2, "units_total": 4},
                    [80.6338, 16.5261],
                )
                print(f"         Pump Station Telemetry -> Pump P-12 verified online.")

            beat += 1
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[!] Telemetry streaming stopped by user.")
            break
        except Exception as e:
            print(f"[!] Error pushing event: {e}")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
