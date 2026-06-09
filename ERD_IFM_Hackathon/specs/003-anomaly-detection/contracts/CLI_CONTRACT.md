# CLI Contracts: Anomaly Detection

**Feature**: 003-anomaly-detection
**Date**: 2026-06-09

---

## Contract 1: Training Script

**Entry point**: `python -m src.detection.anomaly`

### Invocation

```bash
# Fit models from default baseline path
python -m src.detection.anomaly --fit

# Fit models from a custom baseline CSV
python -m src.detection.anomaly --fit --data-path path/to/baseline.csv

# Show help
python -m src.detection.anomaly --help
```

### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--fit` | Yes | — | Triggers training mode. Required flag. |
| `--data-path` | No | `data/telemetry_baseline.csv` | Path to the baseline CSV file |
| `--output-dir` | No | `src/detection/models/` | Directory to write `.pkl` files |
| `--version` | No | `1.0.0` | Version string embedded in model artifact |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All device models trained and saved successfully |
| 1 | Baseline CSV not found or unreadable |
| 2 | No rows found for one or more device types (warning only — continues for other types) |
| 3 | Model serialisation failed |

### Stdout (success)

```
[TRAIN] Loading baseline: data/telemetry_baseline.csv
[TRAIN] boiler       — 1024 rows → fitting IsolationForest ... saved src/detection/models/boiler.pkl
[TRAIN] pasteurizer  — 890 rows  → fitting IsolationForest ... saved src/detection/models/pasteurizer.pkl
[TRAIN] dryer        — 756 rows  → fitting IsolationForest ... saved src/detection/models/dryer.pkl
[TRAIN] Training complete. 3 models saved.
```

### Stdout (error)

```
[ERROR] Baseline CSV not found: data/telemetry_baseline.csv
```

---

## Contract 2: Subscriber Process

**Entry point**: `python -m src.detection.subscriber`

### Invocation

```bash
# Start subscriber (reads REDIS_URL and ANOMALY_THRESHOLD from .env / environment)
python -m src.detection.subscriber
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDIS_URL` | No | `redis://localhost:6379` | Redis connection URL |
| `ANOMALY_THRESHOLD` | No | `-0.1` | IsolationForest score cutoff |
| `SQLITE_DB_PATH` | No | `./ifm_audit.db` | Path to SQLite audit database |

### Lifecycle

```
startup:
  1. Load model files from src/detection/models/ — exit(1) if any model missing
  2. Connect to Redis — retry with backoff if unavailable
  3. Subscribe to channel "telemetry"
  4. Begin consume loop

per message:
  5. Decode JSON payload → TelemetryMessage
  6. Extract device-type features
  7. Score with device model
  8. If score < ANOMALY_THRESHOLD → write Alert(ANOMALY) to SQLite
  9. If scoring exception → write Alert(PIPELINE_ERROR) to SQLite, continue

shutdown (SIGINT / SIGTERM):
  10. Unsubscribe and close Redis connection
  11. Close SQLAlchemy session
  12. Exit 0
```

### Stdout pattern

```
[SUBSCRIBER] Models loaded: boiler, pasteurizer, dryer
[SUBSCRIBER] Connected to Redis redis://localhost:6379
[SUBSCRIBER] Subscribed to channel: telemetry
[14:32:01] [boiler     ] score= -0.05 (OK)       reading_id=abc123
[14:32:06] [pasteurizer] score= -0.18 (ANOMALY)  reading_id=def456 → alert written
[14:32:11] [dryer      ] score= -0.03 (OK)       reading_id=ghi789
```

---

## Contract 3: Alert DB Schema (consumed by Dashboard and AI Agent)

The `alerts` table in SQLite is queried by the Streamlit dashboard and the LangChain AI agent.
Both consumers rely on these columns being present and stable.

```sql
CREATE TABLE alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT    NOT NULL,
    device_type   TEXT    NOT NULL,
    reading_id    TEXT,
    batch_id      TEXT    NOT NULL,
    anomaly_score REAL,
    alert_type    TEXT    NOT NULL,   -- 'ANOMALY' or 'PIPELINE_ERROR'
    sensor_values TEXT,               -- JSON string
    error_detail  TEXT,
    detected_at   TEXT    NOT NULL    -- ISO 8601 UTC
);
```
