# UI Contract: Streamlit Operator Dashboard

**Feature**: `002-operator-dashboard` | **Date**: 2026-06-09

---

## Page Layout

```
┌──────────────────────────────────────────────────────────┐
│  IFM Operator Dashboard  •  Auto-refreshes every 5s      │
├──────────────────────────────────────────────────────────┤
│  [Tab: Live Feed]  [Tab: CCP Alerts]  [Tab: Batch Audit] │
├──────────────────────────────────────────────────────────┤
│  <active tab content>                                     │
└──────────────────────────────────────────────────────────┘
```

---

## Tab 1: Live Feed

**Trigger**: Always visible (default tab on load).

**Content**:
- Metric row: `Total Readings` | `ACCEPTED` | `REJECTED` | `Stream Failures`
- Dataframe table — 50 most recent readings, sorted newest-first
- Row colour coding:
  - 🟢 Green background: `status == "ACCEPTED"` and `stream_published == True`
  - 🟠 Orange background: `status == "ACCEPTED"` and `stream_published == False`
  - 🔴 Red background: `status == "REJECTED"`

**Columns shown**:

| Column | Label | Notes |
|--------|-------|-------|
| `server_received_at` | Received At | ISO datetime |
| `device_id` | Device | |
| `device_type` | Type | |
| `batch_id` | Batch | |
| `temperature` | Temp (°C) | Blank if None |
| `pressure` | Pressure (bar) | Blank if None |
| `humidity` | Humidity (%) | Blank if None |
| `ph` | pH | Blank if None |
| `flow_rate` | Flow (L/min) | Blank if None |
| `status` | Status | |
| `stream_published` | Streamed | ✓ / ✗ |

**Empty state**: "No readings yet — waiting for sensor data."

**Error state**: "Could not connect to database. Is the API running?"

---

## Tab 2: CCP Alerts

**Trigger**: Operator clicks "CCP Alerts" tab.

**Content**:
- Summary metric: `Total CCP Violations: N` (all-time count)
- Dataframe table — 20 most recent REJECTED readings, sorted newest-first, all rows red

**Columns shown**:

| Column | Label | Notes |
|--------|-------|-------|
| `server_received_at` | Received At | |
| `device_id` | Device | |
| `device_type` | Type | |
| `rejection_reason` | Violation Detail | Truncated to 120 chars in cell |
| `batch_id` | Batch | |
| `reading_id` | Reading ID | |

**Empty state**: "No CCP violations detected — all readings within safe range."

---

## Tab 3: Batch Audit

**Trigger**: Operator clicks "Batch Audit" tab.

**Content**:
- Text input: `Search batch ID` (value persisted in `st.session_state["batch_search"]`)
- Submit button: `Search`
- Results table (shown after search): all readings for the batch, sorted by `device_timestamp` ASC

**Columns shown**:

| Column | Label | Notes |
|--------|-------|-------|
| `device_timestamp` | Device Time | |
| `device_id` | Device | |
| `device_type` | Type | |
| `temperature` | Temp (°C) | |
| `pressure` | Pressure (bar) | |
| `humidity` | Humidity (%) | |
| `ph` | pH | |
| `flow_rate` | Flow (L/min) | |
| `status` | Status | Colour coded |
| `rejection_reason` | Rejection Reason | |
| `stream_published` | Streamed | |

**Empty state (no search yet)**: "Enter a batch ID above to view its full audit trail."

**Empty state (no results)**: "No records found for batch `{batch_id}`."

---

## Graceful Degradation

| Condition | Behaviour |
|-----------|-----------|
| Database file missing | Show error banner at top of page; all tabs show error state |
| Empty database | Each tab shows its respective empty-state message |
| Anomaly detector not running | No impact — not displayed in this feature |
| AI agent not running | No impact — not displayed in this feature |
