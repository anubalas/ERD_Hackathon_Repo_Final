# Quickstart: Anomaly Detection

**Feature**: 003-anomaly-detection
**Date**: 2026-06-09

---

## Prerequisites

- FastAPI telemetry API running on `http://localhost:8000`
- Redis running on `localhost:6379`
- SQLite database initialised at `./ifm_audit.db`
- Virtual environment activated (`source ERD_Hack_env/Scripts/activate`)
- Dependencies installed (`pip install -r requirements.txt`)

---

## Step 1: Generate Baseline CSV (first time only)

If `data/telemetry_baseline.csv` does not yet exist, run the simulators for a few minutes to
accumulate clean data, or create the file manually. The CSV must contain normal (non-breach)
readings for boiler, pasteurizer, and dryer:

```csv
device_type,temperature,pressure,humidity,ph,flow_rate,batch_id,timestamp
boiler,155.2,5.3,,,,"BATCH-BASELINE-001",2026-06-01T08:00:00Z
pasteurizer,82.0,,,,95.0,"BATCH-BASELINE-001",2026-06-01T08:00:05Z
dryer,110.5,,30.0,,,"BATCH-BASELINE-001",2026-06-01T08:00:10Z
```

---

## Step 2: Train the Models

```bash
python -m src.detection.anomaly --fit
```

Expected output:
```
[TRAIN] Loading baseline: data/telemetry_baseline.csv
[TRAIN] boiler       — N rows → fitting IsolationForest ... saved src/detection/models/boiler.pkl
[TRAIN] pasteurizer  — N rows → fitting IsolationForest ... saved src/detection/models/pasteurizer.pkl
[TRAIN] dryer        — N rows → fitting IsolationForest ... saved src/detection/models/dryer.pkl
[TRAIN] Training complete. 3 models saved.
```

---

## Step 3: Start the Subscriber

In a separate terminal:

```bash
python -m src.detection.subscriber
```

Expected startup output:
```
[SUBSCRIBER] Models loaded: boiler, pasteurizer, dryer
[SUBSCRIBER] Connected to Redis redis://localhost:6379
[SUBSCRIBER] Subscribed to channel: telemetry
```

---

## Step 4: Send Telemetry Readings

In another terminal, send a normal reading (should NOT trigger anomaly):

```bash
curl -s -X POST http://localhost:8000/telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "boiler-line-1",
    "device_type": "boiler",
    "temperature": 160.0,
    "pressure": 5.5,
    "batch_id": "BATCH-TEST-001",
    "timestamp": "2026-06-09T10:00:00Z"
  }' | python -m json.tool
```

Send an anomalous reading (temperature far outside baseline range):

```bash
curl -s -X POST http://localhost:8000/telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "boiler-line-1",
    "device_type": "boiler",
    "temperature": 210.0,
    "pressure": 13.5,
    "batch_id": "BATCH-TEST-001",
    "timestamp": "2026-06-09T10:00:05Z"
  }' | python -m json.tool
```

---

## Step 5: Verify Alert Was Written

```bash
python -c "
import sqlite3, json
conn = sqlite3.connect('./ifm_audit.db')
rows = conn.execute('SELECT id, device_id, anomaly_score, alert_type, detected_at FROM alerts ORDER BY id DESC LIMIT 5').fetchall()
for r in rows:
    print(r)
conn.close()
"
```

Expected: one row with `alert_type='ANOMALY'` and `anomaly_score < -0.1`.

---

## Integration Test Scenario: Redis Disconnection Recovery

1. Start the subscriber (Step 3)
2. Send a normal reading — confirm `(OK)` in subscriber output
3. Stop Redis: `docker stop <redis-container-id>`
4. Wait 5 seconds — subscriber logs reconnect attempts
5. Restart Redis: `docker start <redis-container-id>`
6. Send another reading — confirm subscriber processes it without restart

---

## Running Unit Tests

```bash
# Unit tests only (no Redis or SQLite required)
pytest tests/unit/test_anomaly_scorer.py tests/unit/test_subscriber.py tests/unit/test_alert_crud.py -v
```
