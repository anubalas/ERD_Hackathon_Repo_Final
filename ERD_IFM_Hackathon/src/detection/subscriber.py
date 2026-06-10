"""
Async Redis pub/sub subscriber for IFM anomaly detection.

Subscribes to the 'telemetry' channel, scores each reading with the IsolationForest
model, and writes Alert records to SQLite for anomalies and pipeline errors.

Usage:
    python -m src.detection.subscriber
"""
import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

import redis.asyncio as aioredis

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.db.crud import create_alert
from src.db.database import AsyncSessionLocal, init_db, migrate_db
from src.detection.anomaly import AnomalyScorer

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CHANNEL = "telemetry"
MODELS_DIR = Path(__file__).parent / "models"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

# Rolling window per device type — plain Python, no extra libraries
_rolling_windows: dict[str, list[float]] = {
    "boiler": [],
    "pasteurizer": [],
    "dryer": [],
}


async def process_message(
    raw: str,
    scorer: AnomalyScorer,
    session,
) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("[%s] Malformed message: %s — raw: %.200s", ts, exc, raw)
        await _write_pipeline_error(session, ts, payload={}, error=str(exc), raw=raw)
        return

    device_id = payload.get("device_id", "unknown")
    device_type = payload.get("device_type", "unknown")
    batch_id = payload.get("batch_id", "UNKNOWN")
    reading_id = payload.get("reading_id")

    try:
        raw_score, is_anomaly = scorer.score(device_type, payload)
    except Exception as exc:
        logger.error("[%s] Scoring error for %s/%s: %s", ts, device_type, device_id, exc)
        await create_alert(
            session,
            device_id=device_id,
            device_type=device_type,
            batch_id=batch_id,
            alert_type="PIPELINE_ERROR",
            detected_at=datetime.now(timezone.utc),
            reading_id=reading_id,
            anomaly_score=None,
            sensor_values=json.dumps({k: payload.get(k) for k in
                                       ["temperature", "pressure", "humidity", "ph", "flow_rate"]}),
            error_detail=str(exc)[:512],
        )
        return

    if raw_score is None:
        return

    label = f"{RED}ANOMALY{RESET}" if is_anomaly else "OK     "
    score_str = f"{raw_score:+.4f}"
    print(f"[{ts}] [{device_type:<12}] score={score_str} ({label}) reading_id={reading_id or '-'}")

    if is_anomaly:
        await create_alert(
            session,
            device_id=device_id,
            device_type=device_type,
            batch_id=batch_id,
            alert_type="ANOMALY",
            detected_at=datetime.now(timezone.utc),
            reading_id=reading_id,
            anomaly_score=raw_score,
            sensor_values=json.dumps({k: payload.get(k) for k in
                                       ["temperature", "pressure", "humidity", "ph", "flow_rate"]}),
        )
        logger.info("[%s] Alert written — %s/%s score=%+.4f", ts, device_type, device_id, raw_score)

    # -----------------------------------------------------------------------
    # Rolling window trend detection (runs alongside IsolationForest)
    # -----------------------------------------------------------------------
    temperature = payload.get("temperature")
    if temperature is not None and device_type in _rolling_windows:
        window = _rolling_windows[device_type]
        window.append(float(temperature))
        # Keep only last 10 readings
        if len(window) > 10:
            _rolling_windows[device_type] = window[-10:]
            window = _rolling_windows[device_type]
        if len(window) == 10:
            first_avg = sum(window[:5]) / 5
            last_avg  = sum(window[5:]) / 5
            if last_avg > first_avg * 1.05:
                print(
                    f"[{ts}] [{device_type:<12}] {YELLOW}TREND_ANOMALY{RESET}"
                    f" temp rising: {first_avg:.1f} → {last_avg:.1f}"
                )
                await create_alert(
                    session,
                    device_id=device_id,
                    device_type=device_type,
                    batch_id=batch_id,
                    alert_type="TREND_ANOMALY",
                    severity="WARNING",
                    detected_at=datetime.now(timezone.utc),
                    reading_id=reading_id,
                    error_detail="Gradual temperature rise detected over last 10 readings",
                    sensor_values=json.dumps({"temperature": temperature}),
                )


async def _write_pipeline_error(session, ts: str, payload: dict, error: str, raw: str) -> None:
    device_id = payload.get("device_id", "unknown") if payload else "unknown"
    device_type = payload.get("device_type", "unknown") if payload else "unknown"
    batch_id = payload.get("batch_id", "UNKNOWN") if payload else "UNKNOWN"
    try:
        await create_alert(
            session,
            device_id=device_id,
            device_type=device_type,
            batch_id=batch_id,
            alert_type="PIPELINE_ERROR",
            detected_at=datetime.now(timezone.utc),
            error_detail=error[:512],
        )
    except Exception as db_exc:
        logger.error("[%s] Failed to write PIPELINE_ERROR alert: %s", ts, db_exc)


async def subscribe_loop(scorer: AnomalyScorer, stop_event: asyncio.Event) -> None:
    backoff = 1.0
    backoff_cap = 30.0

    while not stop_event.is_set():
        client = None
        pubsub = None
        try:
            client = aioredis.from_url(REDIS_URL, decode_responses=True, protocol=2)
            pubsub = client.pubsub()
            await pubsub.subscribe(CHANNEL)
            print(f"{GREEN}[SUBSCRIBER] Subscribed to channel: {CHANNEL}{RESET}")
            backoff = 1.0

            async with AsyncSessionLocal() as session:
                while not stop_event.is_set():
                    try:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0
                        )
                    except (TimeoutError, asyncio.TimeoutError):
                        continue
                    if message is None:
                        continue
                    if message.get("type") != "message":
                        continue
                    await process_message(message["data"], scorer, session)

        except (ConnectionError, OSError, aioredis.ConnectionError) as exc:
            if stop_event.is_set():
                break
            logger.warning("Redis connection lost: %s — reconnecting in %.0fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, backoff_cap)
        except Exception as exc:
            if stop_event.is_set():
                break
            logger.error("Unexpected error in subscriber loop: %s", exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, backoff_cap)
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe(CHANNEL)
                    await pubsub.aclose()
                except Exception:
                    pass
            if client:
                try:
                    await client.aclose()
                except Exception:
                    pass


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    scorer = AnomalyScorer()
    try:
        scorer.load_models(MODELS_DIR)
    except FileNotFoundError as exc:
        print(f"{RED}[SUBSCRIBER] {exc}{RESET}", file=sys.stderr)
        sys.exit(1)

    device_names = list(scorer._models.keys())
    print(f"{GREEN}[SUBSCRIBER] Models loaded: {', '.join(device_names)}{RESET}")

    await init_db()
    await migrate_db()

    stop_event = asyncio.Event()

    def _handle_shutdown(signum, frame):
        print(f"\n{YELLOW}[SUBSCRIBER] Shutting down...{RESET}")
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    print(f"{GREEN}[SUBSCRIBER] Connecting to Redis {REDIS_URL}{RESET}")
    await subscribe_loop(scorer, stop_event)
    print(f"{YELLOW}[SUBSCRIBER] Stopped.{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
