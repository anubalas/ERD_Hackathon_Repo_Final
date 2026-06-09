# Data Model: Streamlit Operator Dashboard

**Feature**: `002-operator-dashboard` | **Date**: 2026-06-09

> This feature is **read-only**. It does not define new database tables. All data is read from
> the `telemetry_log` table defined in `src/db/models.py` (feature `001-telemetry-ingestion-api`).

---

## Source Table: `telemetry_log`

Defined in `src/db/models.py`. Columns consumed by the dashboard:

| Column | Type | Used by |
|--------|------|---------|
| `id` | Integer PK | Row identity |
| `reading_id` | String(36) | Display in all panels |
| `device_id` | String | Live feed, alerts, batch audit |
| `device_type` | String | Live feed, alerts, batch audit |
| `temperature` | Float nullable | Live feed |
| `pressure` | Float nullable | Live feed |
| `humidity` | Float nullable | Live feed |
| `ph` | Float nullable | Live feed |
| `flow_rate` | Float nullable | Live feed |
| `batch_id` | String | Batch audit search key |
| `device_timestamp` | DateTime | All panels |
| `server_received_at` | DateTime | All panels (sort key) |
| `status` | String(10) | Colour coding, alerts filter |
| `rejection_reason` | Text nullable | Alerts panel, batch audit |
| `stream_published` | Boolean | Orange colour indicator |
| `created_at` | DateTime | Secondary sort |

---

## Query Views (logical, not physical tables)

These are the three read-only query shapes the dashboard executes:

### LiveFeedView

```
SELECT * FROM telemetry_log
ORDER BY server_received_at DESC
LIMIT 50
```

Fields displayed: `reading_id`, `device_id`, `device_type`, `temperature`, `pressure`,
`humidity`, `ph`, `flow_rate`, `batch_id`, `device_timestamp`, `status`, `stream_published`

Colour rule:
- `status == "REJECTED"` → red row
- `status == "ACCEPTED"` and `stream_published == False` → orange row
- `status == "ACCEPTED"` and `stream_published == True` → green row

---

### AlertsView

```
SELECT * FROM telemetry_log
WHERE status = 'REJECTED'
ORDER BY server_received_at DESC
LIMIT 20
```

Fields displayed: `reading_id`, `device_id`, `device_type`, `rejection_reason`,
`device_timestamp`, `server_received_at`

Also query: `SELECT COUNT(*) FROM telemetry_log WHERE status = 'REJECTED'` for total count.

---

### BatchAuditView

```
SELECT * FROM telemetry_log
WHERE batch_id = :batch_id
ORDER BY device_timestamp ASC
```

Fields displayed: `reading_id`, `device_id`, `device_type`, `temperature`, `pressure`,
`humidity`, `ph`, `flow_rate`, `status`, `rejection_reason`, `device_timestamp`, `stream_published`

---

## State: `st.session_state` Keys

| Key | Type | Purpose |
|-----|------|---------|
| `batch_search` | str | Preserves batch ID search input across auto-refresh reruns |
