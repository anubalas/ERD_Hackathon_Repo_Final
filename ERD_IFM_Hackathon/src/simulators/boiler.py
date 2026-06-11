import random
import time
from datetime import datetime, timezone

import requests

API_URL = "http://localhost:8000/telemetry"
BATCH_ID = "BATCH-20260609-001"
INTERVAL = 5  # seconds

# ANSI colours
RED = "\033[91m"
GREEN = "\033[92m"
RESET = "\033[0m"


def make_reading(count: int) -> dict:  # count kept for API compatibility
    temperature = round(random.uniform(140.0, 180.0), 1)
    pressure = round(random.uniform(4.0, 8.0), 2)

    breach = False
    if random.random() < 0.25:
        breach = True
        if random.random() < 0.5:
            temperature = round(random.uniform(201.0, 220.0), 1)  # above max 200°C
        else:
            pressure = round(random.uniform(12.1, 15.0), 2)  # above max 12 bar

    return {
        "device_id": "boiler-line-1",
        "device_type": "boiler",
        "temperature": temperature,
        "pressure": pressure,
        "batch_id": BATCH_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, breach


def run():
    print(f"{GREEN}[BOILER] Simulator started — posting every {INTERVAL}s{RESET}")
    count = 0
    while True:
        payload, breach = make_reading(count)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        try:
            resp = requests.post(API_URL, json=payload, timeout=5)
            label = f"{RED}BREACH{RESET}" if breach else "OK"
            status_code = resp.status_code
            print(
                f"[{ts}] [BOILER] [{label}] "
                f"temp={payload['temperature']}°C  pressure={payload['pressure']}bar  "
                f"→ HTTP {status_code}"
            )
        except requests.exceptions.ConnectionError:
            print(f"[{ts}] [BOILER] Connection error — is the API running?")
        except Exception as exc:
            print(f"[{ts}] [BOILER] Error: {exc}")

        count += 1
        time.sleep(INTERVAL)


if __name__ == "__main__":
    run()
