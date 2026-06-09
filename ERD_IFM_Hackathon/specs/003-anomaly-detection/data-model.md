# Data Model: Anomaly Detection

**Feature**: 003-anomaly-detection
**Date**: 2026-06-09

---

## Entity: Alert

The persistent audit record written for every anomaly detected by the IsolationForest scorer.
Append-only per Constitution Principle II — no UPDATE or DELETE operations are permitted.

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| id | Integer (PK, autoincrement) | No | System-assigned unique alert identifier |
| device_id | String(64) | No | Identifier of the device that generated the reading |
| device_type | String(32) | No | Normalised device type: `boiler`, `pasteurizer`, or `dryer` |
| reading_id | String(64) | Yes | reading_id from the TelemetryLog entry (if available) |
| batch_id | String(64) | No | Batch context carried from the telemetry message |
| anomaly_score | Float | Yes | Raw IsolationForest decision score (lower = more anomalous). NULL if alert_type is PIPELINE_ERROR |
| alert_type | String(32) | No | `ANOMALY` or `PIPELINE_ERROR` |
| sensor_values | JSON (String) | Yes | JSON dump of all sensor readings from the flagged message |
| error_detail | String(512) | Yes | Exception message if alert_type is PIPELINE_ERROR; NULL for ANOMALY |
| detected_at | DateTime (UTC) | No | Server UTC timestamp at detection time |

**Constraints:**
- `batch_id` MUST NOT be NULL — orphaned alerts (no batch context) are a data integrity violation (Constitution GMP §Deviation Handling)
- `detected_at` is set at INSERT time; never overwritten
- No foreign-key constraint to `TelemetryLog` in SQLite (avoids join dependency), but `reading_id` is populated when available

**Relationships:**
- References `TelemetryLog.reading_id` (soft reference — no FK constraint in SQLite v1)
- Referenced by the Streamlit dashboard Alerts panel query
- Referenced by the LangChain AI Agent alert-lookup tool

---

## Entity: TelemetryMessage (Runtime, not persisted)

The in-memory decoded payload received from the Redis `telemetry` pub/sub channel. This is not
a database table — it is the Python dataclass / dict used within the subscriber process.

| Field | Type | Source |
|-------|------|--------|
| reading_id | String | From TelemetryLog.reading_id in the API response |
| device_id | String | Published by Telemetry API |
| device_type | String | Published by Telemetry API |
| temperature | Float or None | Published by Telemetry API |
| pressure | Float or None | Published by Telemetry API |
| humidity | Float or None | Published by Telemetry API |
| ph | Float or None | Published by Telemetry API |
| flow_rate | Float or None | Published by Telemetry API |
| batch_id | String | Published by Telemetry API |
| server_received_at | String (ISO8601) | Published by Telemetry API |

---

## Entity: DeviceModel (File-based, not persisted in DB)

A per-device-type serialised IsolationForest artifact. Stored as a `.pkl` file on local disk.

| Field | Type | Description |
|-------|------|-------------|
| model | IsolationForest | Trained scikit-learn model object |
| trained_at | String (ISO8601) | UTC timestamp of training run |
| version | String (semver) | Model version (e.g., "1.0.0") |
| features | List[String] | Ordered feature column names used during training |

**File locations:**
```
src/detection/models/boiler.pkl
src/detection/models/pasteurizer.pkl
src/detection/models/dryer.pkl
```

---

## Entity: BaselineDataset (File-based, read-only)

The training input CSV. Never modified at runtime.

| Column | Type | Applicable Devices |
|--------|------|--------------------|
| device_type | String | All |
| temperature | Float | boiler, pasteurizer, dryer |
| pressure | Float | boiler |
| humidity | Float | dryer |
| ph | Float | pasteurizer |
| flow_rate | Float | pasteurizer |
| batch_id | String | All |
| timestamp | String | All |

**File location:** `data/telemetry_baseline.csv`

---

## Feature Registry (Runtime constant)

Defines the feature columns extracted per device type for model scoring and training.

```python
DEVICE_FEATURES = {
    "boiler":       ["temperature", "pressure"],
    "pasteurizer":  ["temperature", "ph", "flow_rate"],
    "dryer":        ["temperature", "humidity"],
}
```

---

## Relationships Diagram

```
data/telemetry_baseline.csv
        │
        │  (offline training only)
        ▼
src/detection/models/{device_type}.pkl
        │
        │  loaded at startup (read-only)
        ▼
Redis `telemetry` channel
        │
        │  subscribe
        ▼
AnomalySubscriber (runtime process)
        │
        ├── score < threshold ──► Alert (ANOMALY) ──► SQLite alerts table
        │
        └── scoring error ──────► Alert (PIPELINE_ERROR) ──► SQLite alerts table
```
