# Feature Specification: Streamlit Operator Dashboard

**Feature Branch**: `002-operator-dashboard`

**Created**: 2026-06-09

**Status**: Draft

**Input**: User description: "Build a Streamlit dashboard for factory operators to monitor IFM telemetry in real time."

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Live Sensor Feed (Priority: P1)

A factory operator opens the dashboard and sees the most recent telemetry readings from all devices in a scrollable table. The table refreshes every 5 seconds automatically so the operator does not need to manually reload the page. Each row is colour-coded: green for accepted readings, red for rejected (CCP violation), and orange for accepted readings that were not streamed.

**Why this priority**: The core purpose of the dashboard is real-time situational awareness. Without a live feed, operators cannot detect deviations as they occur.

**Independent Test**: Open the dashboard against a populated `telemetry_log` database. The table shows the 50 most recent readings with correct colour coding. Wait 5 seconds — the table refreshes and reflects any new rows added to the database.

**Acceptance Scenarios**:

1. **Given** the database has 30+ telemetry records, **When** the operator opens the dashboard, **Then** the live feed table shows the most recent records ordered by most-recent-first with correct status colours.
2. **Given** a new ACCEPTED reading is written to the database, **When** 5 seconds pass, **Then** the table refreshes and the new row appears at the top.
3. **Given** the database is empty, **When** the operator opens the dashboard, **Then** the table shows a friendly empty-state message ("No readings yet").
4. **Given** a reading has `stream_published = false`, **When** displayed in the table, **Then** the row is highlighted in orange and a tooltip or label indicates "Stream unavailable".

---

### User Story 2 — CCP Alerts Panel (Priority: P2)

A factory operator sees a dedicated alerts panel listing all REJECTED readings caused by CCP violations. Each alert shows the device ID, device type, which CCP field failed (e.g. temperature), the value received, the allowed range, and the timestamp. The panel updates on the same 5-second refresh cycle.

**Why this priority**: CCP violations are the most safety-critical events. Operators need to spot them at a glance, separate from the general feed.

**Independent Test**: Insert a REJECTED record into `telemetry_log` with a non-null `rejection_reason`. Open the dashboard — the alerts panel shows the record with the device, violation field, and reason visible. Insert a second REJECTED record and wait 5 seconds — it appears in the panel.

**Acceptance Scenarios**:

1. **Given** REJECTED records exist in the database, **When** the operator views the alerts panel, **Then** all REJECTED records are listed with device, field, received value, allowed range, and timestamp.
2. **Given** no REJECTED records exist, **When** the operator views the alerts panel, **Then** a friendly message is shown ("No CCP violations detected").
3. **Given** a new CCP violation is recorded, **When** 5 seconds pass, **Then** the alert appears at the top of the alerts panel.

---

### User Story 3 — Batch Audit Trail (Priority: P3)

A factory operator can search for a specific batch by entering a `batch_id` in a search box. The dashboard shows all telemetry readings for that batch in chronological order, including both ACCEPTED and REJECTED records. This provides a complete audit trail for any given production batch.

**Why this priority**: GMP compliance requires operators and auditors to inspect the full history of any batch on demand. This story enables that capability.

**Independent Test**: Enter a known `batch_id` in the search box. The results table shows only records matching that batch, ordered by timestamp, with status and rejection reason visible.

**Acceptance Scenarios**:

1. **Given** a `batch_id` with both ACCEPTED and REJECTED records, **When** the operator enters the batch ID and submits, **Then** all records for that batch are shown in chronological order.
2. **Given** an unknown `batch_id`, **When** the operator searches, **Then** a friendly empty-state message is shown ("No records found for batch [ID]").
3. **Given** the operator clears the search box, **When** the dashboard updates, **Then** the live sensor feed returns to showing the latest readings across all batches.

---

### Edge Cases

- What happens when the database file does not exist yet (API not started)? Dashboard shows a clear "Database not available" message — does not crash.
- What happens when a `rejection_reason` is very long? The cell truncates with a tooltip showing the full text.
- What happens when hundreds of REJECTED alerts exist? The alerts panel shows the 20 most recent by default with a note indicating total count.
- What happens when the anomaly detector or AI agent are not running? Dashboard operates normally — those panels show "Not available" gracefully.
- What happens if auto-refresh fires while the operator is typing in the search box? The search input is preserved across refreshes.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The dashboard MUST display a live feed of the most recent 50 telemetry readings, ordered most-recent-first, refreshing every 5 seconds.
- **FR-002**: Each reading in the live feed MUST be visually distinguished by status: green (ACCEPTED, stream published), orange (ACCEPTED, stream not published), red (REJECTED).
- **FR-003**: The dashboard MUST display a dedicated CCP alerts panel showing all REJECTED readings with device ID, device type, violation field, received value, allowed range, and timestamp.
- **FR-004**: The alerts panel MUST show the 20 most recent REJECTED records by default and display the total count of all violations.
- **FR-005**: The dashboard MUST provide a batch search input. Submitting a `batch_id` MUST show all readings for that batch in chronological order.
- **FR-006**: The batch audit view MUST display both ACCEPTED and REJECTED records for the searched batch, including rejection reason.
- **FR-007**: All panels MUST display a friendly empty-state message when no data is available — no blank tables or unhandled errors shown to the operator.
- **FR-008**: The dashboard MUST gracefully handle a missing or inaccessible database by displaying a clear error message without crashing.
- **FR-009**: The dashboard MUST operate fully when the anomaly detection service and AI agent are not running.
- **FR-010**: The auto-refresh MUST NOT reset or clear the operator's active search input.

### Key Entities

- **TelemetryReading**: A single sensor reading from a factory device — includes device ID, device type, measurement values, batch ID, timestamp, status (ACCEPTED/REJECTED), rejection reason, and stream published flag.
- **CCPAlert**: A REJECTED reading with a structured violation — the field that failed, the value received, and the allowed range. Derived from `TelemetryReading`.
- **BatchRecord**: The full set of readings associated with a single `batch_id`, used for audit trail display.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can identify the current status of all active devices within 5 seconds of opening the dashboard.
- **SC-002**: A CCP violation is visible in the alerts panel within 10 seconds of being recorded (one refresh cycle).
- **SC-003**: An operator can retrieve the complete audit trail for any batch within 10 seconds of entering the batch ID.
- **SC-004**: The dashboard remains usable (no crash, no blank screen) when the database is empty or unavailable.
- **SC-005**: 100% of REJECTED readings recorded in the audit log are surfaced in the alerts panel — no silent omissions.

---

## Assumptions

- The dashboard reads directly from the same SQLite `telemetry_log` table written by the Telemetry Ingestion API — no separate data service.
- Synchronous database access is acceptable for Streamlit (no async required).
- No authentication is required in v1 — the dashboard is assumed to run on an internal factory network.
- The `rejection_reason` field in REJECTED records contains human-readable text describing which CCP field failed and why.
- Mobile/tablet support is out of scope for v1 — the dashboard targets desktop browsers used at operator workstations.
- The anomaly detection and AI agent panels are out of scope for this feature — placeholder UI with "Coming soon" or "Not available" is acceptable.
- Page-level auto-refresh (Streamlit `st.rerun` with a timer) is the refresh mechanism; WebSocket streaming is out of scope for v1.
