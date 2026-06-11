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
    temperature = round(random.uniform(90.0, 150.0), 1)
    humidity = round(random.uniform(10.0, 55.0), 1)

    breach = False
    if random.random() < 0.25:
        breach = True
        if random.random() < 0.5:
            temperature = round(random.uniform(161.0, 180.0), 1)  # above max 160°C
        else:
            humidity = round(random.uniform(61.0, 85.0), 1)  # above max 60%

    return {
        "device_id": "dryer-01",
        "device_type": "dryer",
        "temperature": temperature,
        "humidity": humidity,
        "batch_id": BATCH_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, breach


def run():
    print(f"{GREEN}[DRYER] Simulator started — posting every {INTERVAL}s{RESET}")
    count = 0
    while True:
        payload, breach = make_reading(count)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        try:
            resp = requests.post(API_URL, json=payload, timeout=5)
            label = f"{RED}BREACH{RESET}" if breach else "OK"
            print(
                f"[{ts}] [DRYER] [{label}] "
                f"temp={payload['temperature']}°C  humidity={payload['humidity']}%  "
                f"→ HTTP {resp.status_code}"
            )
        except requests.exceptions.ConnectionError:
            print(f"[{ts}] [DRYER] Connection error — is the API running?")
        except Exception as exc:
            print(f"[{ts}] [DRYER] Error: {exc}")

        count += 1
        time.sleep(INTERVAL)


if __name__ == "__main__":
    run()
