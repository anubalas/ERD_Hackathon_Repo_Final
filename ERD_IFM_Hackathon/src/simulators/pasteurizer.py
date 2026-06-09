import random
import time
from datetime import datetime, timezone

import requests

API_URL = "http://localhost:8000/telemetry"
BATCH_ID = "BATCH-20260609-001"
INTERVAL = 5  # seconds

RED = "\033[91m"
GREEN = "\033[92m"
RESET = "\033[0m"


def make_reading(count: int) -> tuple[dict, bool]:
    temperature = round(random.uniform(75.0, 88.0), 1)
    ph = round(random.uniform(4.5, 7.0), 2)
    flow_rate = round(random.uniform(20.0, 180.0), 1)

    breach = False
    if count % 20 == 0 and count > 0:
        temperature = 60.0  # below min 72°C
        breach = True
    elif count % 25 == 0 and count > 0:
        ph = 2.8  # below min 3.5
        breach = True

    return {
        "device_id": "past-01",
        "device_type": "pasteurizer",
        "temperature": temperature,
        "ph": ph,
        "flow_rate": flow_rate,
        "batch_id": BATCH_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, breach


def run():
    print(f"{GREEN}[PASTEURIZER] Simulator started — posting every {INTERVAL}s{RESET}")
    count = 0
    while True:
        payload, breach = make_reading(count)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        try:
            resp = requests.post(API_URL, json=payload, timeout=5)
            label = f"{RED}BREACH{RESET}" if breach else "OK"
            print(
                f"[{ts}] [PASTEURIZER] [{label}] "
                f"temp={payload['temperature']}°C  ph={payload['ph']}  "
                f"flow={payload['flow_rate']}L/min  → HTTP {resp.status_code}"
            )
        except requests.exceptions.ConnectionError:
            print(f"[{ts}] [PASTEURIZER] Connection error — is the API running?")
        except Exception as exc:
            print(f"[{ts}] [PASTEURIZER] Error: {exc}")

        count += 1
        time.sleep(INTERVAL)


if __name__ == "__main__":
    run()
