# API Contract: POST /telemetry

**Feature**: `001-telemetry-ingestion-api` | **Date**: 2026-06-09

---

## Endpoint

```
POST /telemetry
Content-Type: application/json
```

No authentication headers required (v1).

---

## Request Body

All fields listed. Required fields must be present and non-null. Optional sensor measurement
fields (`temperature`, `pressure`, `humidity`, `ph`, `flow_rate`) may be omitted or `null`.

```json
{
  "device_id":   "boiler-line-1",
  "device_type": "boiler",
  "temperature": 165.3,
  "pressure":    5.8,
  "humidity":    null,
  "ph":          null,
  "flow_rate":   null,
  "batch_id":    "BATCH-20260609-001",
  "timestamp":   "2026-06-09T08:00:00Z"
}
```

### Field rules

| Field | Type | Required | Valid Values |
|-------|------|----------|-------------|
| `device_id` | string | Yes | Non-empty string |
| `device_type` | string | Yes | `"boiler"`, `"pasteurizer"`, `"dryer"` (case-insensitive) |
| `temperature` | number \| null | No | ≥ 0 |
| `pressure` | number \| null | No | ≥ 0 |
| `humidity` | number \| null | No | ≥ 0 |
| `ph` | number \| null | No | ≥ 0 |
| `flow_rate` | number \| null | No | ≥ 0 |
| `batch_id` | string | Yes | Non-empty string |
| `timestamp` | string | Yes | ISO 8601 datetime with timezone offset |

---

## Response: HTTP 200 — Reading Accepted (stream published)

```json
{
  "reading_id":        "550e8400-e29b-41d4-a716-446655440000",
  "status":            "ACCEPTED",
  "server_received_at": "2026-06-09T08:00:00.412Z",
  "stream_published":  true,
  "warnings":          []
}
```

## Response: HTTP 200 — Reading Accepted (stream unavailable)

Returned when the reading was persisted to the audit log but could not be published to
the anomaly detection stream. The device should treat this as a successful submission;
operations staff are alerted separately via the structured error log.

```json
{
  "reading_id":        "550e8400-e29b-41d4-a716-446655440001",
  "status":            "ACCEPTED",
  "server_received_at": "2026-06-09T08:00:00.509Z",
  "stream_published":  false,
  "warnings": [
    "anomaly detection stream unavailable — reading stored but not streamed"
  ]
}
```

---

## Response: HTTP 422 — CCP Range Violation

Returned when one or more sensor measurements fall outside the safe CCP operating range
for the submitted `device_type`. The rejection is recorded in the audit database.

All failing fields are listed simultaneously — the response never reports only the first.

```json
{
  "detail": [
    {
      "field":         "temperature",
      "message":       "Value 60.0 is below minimum 72.0 for pasteurizer",
      "received":      60.0,
      "allowed_range": { "min": 72.0, "max": 90.0 }
    },
    {
      "field":         "ph",
      "message":       "Value 8.9 exceeds maximum 7.5 for pasteurizer",
      "received":      8.9,
      "allowed_range": { "min": 3.5, "max": 7.5 }
    }
  ]
}
```

## Response: HTTP 422 — Structural Validation Error

Returned by FastAPI automatically when the request body fails Pydantic structural
validation (missing required field, wrong type, negative value, unknown device_type).
Shape follows FastAPI default `RequestValidationError` format:

```json
{
  "detail": [
    {
      "type":  "missing",
      "loc":   ["body", "batch_id"],
      "msg":   "Field required",
      "input": { "device_id": "dryer-01", "device_type": "dryer" }
    }
  ]
}
```

Unknown device_type example:

```json
{
  "detail": [
    {
      "type":  "literal_error",
      "loc":   ["body", "device_type"],
      "msg":   "Input should be 'boiler', 'pasteurizer' or 'dryer'",
      "input": "mixer"
    }
  ]
}
```

---

## Response: HTTP 503 — Audit Database Unavailable

Returned when the SQLite audit database cannot be reached. The reading was NOT persisted.
The device MUST retry.

```json
{
  "detail": "Audit database unavailable — reading not persisted"
}
```

---

## Response: HTTP 500 — Unexpected Server Error

Returned for unhandled exceptions. Full error is logged server-side; the response body
intentionally omits internal details.

```json
{
  "detail": "Internal server error"
}
```

---

## CCP Operating Ranges (v1 defaults)

These are the threshold values used to generate 422 CCP violations. Boundary values
(min and max) are **inclusive**.

### Boiler

| Measurement | Min | Max | Unit |
|-------------|-----|-----|------|
| temperature | 120 | 200 | °C |
| pressure | 1 | 12 | bar |

### Pasteurizer

| Measurement | Min | Max | Unit |
|-------------|-----|-----|------|
| temperature | 72 | 90 | °C |
| ph | 3.5 | 7.5 | — |
| flow_rate | 5 | 200 | L/min |

### Dryer

| Measurement | Min | Max | Unit |
|-------------|-----|-----|------|
| temperature | 80 | 160 | °C |
| humidity | 5 | 60 | % |

---

## Redis Pub/Sub Channel

Accepted readings are published as JSON to channel: `telemetry` (configurable via
`REDIS_CHANNEL` environment variable).

Published message shape:

```json
{
  "reading_id":        "550e8400-e29b-41d4-a716-446655440000",
  "device_id":         "pasteurizer-02",
  "device_type":       "pasteurizer",
  "temperature":       78.5,
  "pressure":          null,
  "humidity":          null,
  "ph":                5.2,
  "flow_rate":         42.0,
  "batch_id":          "BATCH-20260609-001",
  "device_timestamp":  "2026-06-09T08:00:00Z",
  "server_received_at":"2026-06-09T08:00:00.412Z"
}
```
