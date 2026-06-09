# Data Model: Telemetry Ingestion API

**Feature**: `001-telemetry-ingestion-api` | **Date**: 2026-06-09

---

## Entity 1: SensorReading (Inbound Payload)

Pydantic model — validated at the API boundary. Structural validation only (types,
required fields, non-negative values). CCP range validation is separate.

| Field | Type | Required | Constraints | Notes |
|-------|------|----------|-------------|-------|
| `device_id` | `str` | Yes | Non-empty string | Identifies the submitting device; not authenticated in v1 |
| `device_type` | `str` | Yes | One of: `boiler`, `pasteurizer`, `dryer` (case-insensitive) | Normalised to lowercase on input |
| `temperature` | `float \| None` | No | ≥ 0 if provided | °C; None means device did not report |
| `pressure` | `float \| None` | No | ≥ 0 if provided | bar |
| `humidity` | `float \| None` | No | ≥ 0 if provided | % |
| `ph` | `float \| None` | No | ≥ 0 if provided | Dimensionless 0–14 scale |
| `flow_rate` | `float \| None` | No | ≥ 0 if provided | L/min |
| `batch_id` | `str` | Yes | Non-empty string | Batch being processed; not validated against a batch registry in v1 |
| `timestamp` | `datetime` | Yes | ISO 8601 with timezone | Device-generated event time |

**Validation rules**:
- `device_id` and `batch_id`: `len(value.strip()) > 0`
- `device_type`: case-insensitive membership in `{"boiler", "pasteurizer", "dryer"}`; reject
  with 422 if not in set
- All numeric fields: `value >= 0` if not None; reject with 422 otherwise
- Missing optional numeric fields (`None`) pass structural validation; CCP threshold
  validation only applies to fields that are not None and are applicable to the device_type

---

## Entity 2: TelemetryLog (Audit Record — Append-Only)

SQLAlchemy ORM model. Maps to the `telemetry_log` table in SQLite.
**No UPDATE or DELETE is ever issued on this table.**

| Column | SQLAlchemy Type | Nullable | Default | Notes |
|--------|----------------|----------|---------|-------|
| `id` | `Integer` | No | autoincrement PK | Internal surrogate key |
| `reading_id` | `String(36)` | No | UUID4 (set by route handler) | Externally visible unique ID returned in response |
| `device_id` | `String` | No | — | From SensorReading |
| `device_type` | `String` | No | — | Normalised lowercase |
| `temperature` | `Float` | Yes | None | °C; null if not in reading |
| `pressure` | `Float` | Yes | None | bar |
| `humidity` | `Float` | Yes | None | % |
| `ph` | `Float` | Yes | None | 0–14 |
| `flow_rate` | `Float` | Yes | None | L/min |
| `batch_id` | `String` | No | — | From SensorReading |
| `device_timestamp` | `DateTime` | No | — | `reading.timestamp` converted to UTC |
| `server_received_at` | `DateTime` | No | set by route handler | UTC timestamp at ingestion |
| `status` | `String(10)` | No | — | `ACCEPTED` or `REJECTED` |
| `rejection_reason` | `Text` | Yes | None | Serialised violation list; null if ACCEPTED |
| `stream_published` | `Boolean` | No | `False` | True if Redis publish confirmed before INSERT |
| `stale_timestamp` | `Boolean` | No | `False` | True if `abs(server_received_at - device_timestamp) > 300s` |
| `created_at` | `DateTime` | No | `func.now()` server-side | Set at INSERT; never writable by application code |

**Indexes**:
- Unique index on `reading_id`
- Index on `batch_id` (supports batch audit trail queries)
- Index on `status` (supports rejected-readings dashboards)
- Index on `server_received_at` (supports time-range audit exports)

**Append-only enforcement**:
- `crud.py` exposes only `create_telemetry_log()` — no update or delete function
- ORM model class has no `.update()` or `.delete()` methods
- Integration test (future) must assert that calling `session.execute(update(...))` on
  the table raises or is blocked at the ORM layer

---

## Entity 3: DeviceCCPThreshold (Configuration — Module-Level Constant)

Not persisted to DB. Defined in `src/api/schemas.py` as a module-level constant.
Overridable via environment variables at startup.

```
CCP_THRESHOLDS = {
    "boiler": {
        temperature: [120.0, 200.0]   # °C
        pressure:    [1.0,   12.0]    # bar
    },
    "pasteurizer": {
        temperature: [72.0,  90.0]    # °C
        ph:          [3.5,   7.5]
        flow_rate:   [5.0,   200.0]   # L/min
    },
    "dryer": {
        temperature: [80.0,  160.0]   # °C
        humidity:    [5.0,   60.0]    # %
    }
}
```

Fields not listed in a device's threshold entry are not subject to CCP validation for that
device type (e.g., `pressure` is not in `pasteurizer` → a non-None pressure value passes
without a range check).

---

## Entity 4: TelemetryEvent (Redis Pub/Sub Message Payload)

JSON-serialised dict published to the `telemetry` Redis channel for each accepted reading.
Consumed by downstream anomaly detection workers.

| Field | Type | Notes |
|-------|------|-------|
| `reading_id` | `str` (UUID4) | Links event back to TelemetryLog record |
| `device_id` | `str` | |
| `device_type` | `str` | normalised lowercase |
| `temperature` | `float \| null` | |
| `pressure` | `float \| null` | |
| `humidity` | `float \| null` | |
| `ph` | `float \| null` | |
| `flow_rate` | `float \| null` | |
| `batch_id` | `str` | |
| `device_timestamp` | `str` (ISO 8601 UTC) | |
| `server_received_at` | `str` (ISO 8601 UTC) | |

---

## Entity 5: CCPViolation (422 Error Detail Item)

Pydantic response model for individual field violations in the 422 response body.

| Field | Type | Example |
|-------|------|---------|
| `field` | `str` | `"temperature"` |
| `message` | `str` | `"Value 60.0 is below minimum 72.0 for pasteurizer"` |
| `received` | `float` | `60.0` |
| `allowed_range` | `{"min": float, "max": float}` | `{"min": 72.0, "max": 90.0}` |

---

## Entity 6: TelemetryResponse (Success Response Body)

Pydantic response model returned on HTTP 200.

| Field | Type | Notes |
|-------|------|-------|
| `reading_id` | `str` (UUID4) | System-assigned; matches TelemetryLog.reading_id |
| `status` | `Literal["ACCEPTED"]` | Always ACCEPTED on 200 |
| `server_received_at` | `datetime` | UTC ISO 8601 |
| `stream_published` | `bool` | True if Redis publish succeeded before DB write |
| `warnings` | `list[str]` | Non-empty only when `stream_published=False`; e.g. `["anomaly detection stream unavailable — reading stored but not streamed"]` |

---

## State Transitions: TelemetryLog.status

```
Inbound SensorReading
        │
        ▼
  Structural validation (Pydantic)
        │
   ┌────┴────────────────────────────┐
   │ structural failure              │ passes
   │ (wrong type, missing field,     │
   │  negative value)                ▼
   │                         CCP range validation
   │                                 │
   │                    ┌────────────┴─────────────┐
   │                    │ violation(s) found        │ passes
   │                    ▼                           ▼
   │             INSERT status=REJECTED      try Redis publish
   │             return HTTP 422             │
   │                                  ┌─────┴──────┐
   │                                  │ fails      │ succeeds
   │                                  ▼            ▼
   │                           stream_ok=False  stream_ok=True
   │                                  └─────┬──────┘
   │                                        ▼
   │                               INSERT status=ACCEPTED
   │                               stream_published=stream_ok
   │                                        │
   │                               ┌────────┴────────┐
   │                               │ DB fails        │ succeeds
   │                               ▼                 ▼
   │                           HTTP 503          HTTP 200
   │
   ▼
(no DB write possible — malformed JSON)
HTTP 422 (FastAPI auto-response)
```
