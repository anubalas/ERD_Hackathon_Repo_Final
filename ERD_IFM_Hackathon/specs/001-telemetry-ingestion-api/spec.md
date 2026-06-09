# Feature Specification: Telemetry Ingestion API

**Feature Branch**: `001-telemetry-ingestion-api`

**Created**: 2026-06-09

**Status**: Draft

**Input**: Factory devices (boiler, pasteurizer, dryer) need a secure, auditable endpoint to
submit real-time CCP sensor readings. Every reading must be validated against device-specific
safety thresholds, permanently recorded in the audit log, and forwarded to the anomaly
detection pipeline — with zero silent failures at any stage.

---

## User Scenarios & Testing

### User Story 1 — Factory Device Submits Valid CCP Reading (Priority: P1)

A factory device submits a sensor reading where all provided values fall within the
CCP-defined safe operating range for its device type. The system accepts the reading,
permanently records it in the audit database, publishes it to the anomaly detection pipeline,
and returns a unique reading identifier confirming successful receipt.

**Why this priority**: This is the primary happy-path that all other pipeline stages depend on.
Without working ingestion of valid readings, anomaly detection, AI remediation, and audit
reporting cannot function.

**Independent Test**: Send a well-formed reading for each device type (boiler, pasteurizer,
dryer) with all applicable sensor values within threshold. Verify HTTP 200 response with
reading_id, a matching TelemetryLog row with status ACCEPTED, and the reading on the telemetry
stream.

**Acceptance Scenarios**:

1. **Given** a boiler device sends a reading with temperature 160°C and pressure 5 bar (both
   within boiler thresholds), **When** the endpoint receives the reading, **Then** the system
   returns HTTP 200 with a unique reading_id, and the reading appears in the audit database
   with status ACCEPTED within 500 ms.

2. **Given** a pasteurizer device sends a reading with temperature exactly at the lower
   threshold boundary (72°C), **When** the endpoint receives the reading, **Then** the reading
   is accepted (boundary values are inclusive) and status ACCEPTED is recorded.

3. **Given** a dryer device omits pH (not applicable to dryers), **When** the endpoint receives
   the reading, **Then** the system accepts the reading without requiring a pH value and returns
   HTTP 200.

4. **Given** any device sends a reading, **When** the endpoint accepts it, **Then** the
   server-assigned reading_id and server_received_at timestamp appear in the response body.

---

### User Story 2 — Factory Device Submits Out-of-Range CCP Reading (Priority: P2)

A factory device submits a sensor reading where one or more CCP parameters fall outside the
safe operating range defined for that device type. The system rejects the reading, returns a
structured error that names every failing field and its acceptable range, and records the
rejection in the audit database.

**Why this priority**: CCP violations are safety-critical events. The system must detect them
reliably and ensure they are captured in the audit trail even when rejected.

**Independent Test**: Send readings with individual and combined CCP violations. Verify HTTP
422 responses listing all failing fields, and confirm that TelemetryLog records the rejection
with a reason even though no reading_id is issued.

**Acceptance Scenarios**:

1. **Given** a pasteurizer reading with temperature 60°C (below minimum 72°C), **When** the
   endpoint receives the reading, **Then** the system returns HTTP 422 with an error body
   identifying the temperature field, stating it is below the minimum threshold.

2. **Given** a boiler reading with pressure 15 bar (above maximum 12 bar), **When** the
   endpoint receives the reading, **Then** the rejection is recorded in the audit database with
   status REJECTED and the rejection reason, and the device receives HTTP 422.

3. **Given** a pasteurizer reading with both temperature (60°C) and pH (8.5) violating
   thresholds simultaneously, **When** the endpoint receives the reading, **Then** the HTTP
   422 response body lists both field violations — not just the first one encountered.

---

### User Story 3 — Unknown or Unregistered Device Type (Priority: P3)

A reading arrives with a device_type that is not in the system's known set. The system rejects
the reading immediately without attempting CCP threshold validation, returns a clear error, and
records the rejection.

**Why this priority**: Unknown device types cannot be validated against CCP thresholds and
likely indicate a misconfigured or unauthorised device — an operator must be made aware.

**Independent Test**: Submit readings with unknown, misspelled, and absent device_type values.
Verify HTTP 422 in every case with an error message identifying the unrecognised device_type.

**Acceptance Scenarios**:

1. **Given** a reading with device_type "mixer" (not in the known set), **When** the endpoint
   receives the reading, **Then** the system returns HTTP 422 stating the device_type is
   unrecognised.

2. **Given** a reading with device_type omitted entirely, **When** the endpoint receives the
   reading, **Then** the system returns HTTP 422 indicating device_type is a required field.

3. **Given** a reading with device_type "Boiler" (incorrect casing), **When** the endpoint
   receives the reading, **Then** the system either accepts the normalised form or returns
   HTTP 422 — the behaviour is consistent and documented in the Assumptions section.

---

### User Story 4 — Downstream Infrastructure Fault (Priority: P4)

A reading passes all validation but the anomaly detection stream is temporarily unavailable.
The system still persists the reading to the audit database and signals the partial failure
explicitly in the response — it does not silently return a success response when downstream
delivery failed.

**Why this priority**: Constitution Principle I (Zero Silent Failures) forbids silent stream
publish failures. Infrastructure degradation must be observable by operators.

**Independent Test**: Submit a valid reading while the stream is simulated as unavailable.
Verify the reading appears in the audit database with status ACCEPTED but
`stream_published: false`, and the response clearly indicates the stream failure.

**Acceptance Scenarios**:

1. **Given** a valid reading and the anomaly detection stream is offline, **When** the endpoint
   receives the reading, **Then** the reading is persisted with status ACCEPTED, the stream
   failure is recorded as an infrastructure error in the audit database, and the HTTP response
   body includes `stream_published: false`.

2. **Given** a valid reading and the audit database is offline, **When** the endpoint receives
   the reading, **Then** the system returns HTTP 503 — it MUST NOT return HTTP 200 without
   confirmed persistence.

---

### Edge Cases

- What happens when a reading's timestamp is more than 5 minutes in the past or future?
  (Assumption: accepted with a `STALE_TIMESTAMP` warning flag in the audit record — not
  rejected, as clock skew is common in factory networks.)
- What happens when device_id is an empty string? (Rejected with HTTP 422 — device_id must be
  a non-empty string.)
- What happens when two readings arrive simultaneously for the same device? (Both processed
  independently; no deduplication in v1.)
- What happens when batch_id references a batch that is not currently active? (Accepted — batch
  state validation is out of scope for v1; batch_id is recorded as-is.)
- What happens when a numeric field (e.g., temperature) is provided as a string? (Rejected with
  HTTP 422 — the field type must be numeric.)
- What happens when flow_rate is provided as negative? (Rejected with HTTP 422 — physical
  measurements cannot be negative.)

---

## Requirements

### Functional Requirements

- **FR-001**: The system MUST expose a single submission endpoint that factory devices use to
  report CCP sensor readings.

- **FR-002**: The endpoint MUST validate that every reading contains non-null, non-empty values
  for: device_id, device_type, batch_id, and timestamp.

- **FR-003**: The endpoint MUST validate that the device_type in every reading matches one of
  the known device types. Readings with unrecognised device types MUST be rejected immediately.

- **FR-004**: The endpoint MUST validate each provided numeric sensor measurement (temperature,
  pressure, humidity, ph, flow_rate) against the CCP safe operating range defined for the
  reading's device type.

- **FR-005**: CCP operating ranges MUST be independently configured per device type; the ranges
  for boiler, pasteurizer, and dryer are distinct and separately maintained.

- **FR-006**: Sensor parameters that are not applicable to a given device type MUST be treated
  as optional — a reading that omits them is not invalid on that basis alone.

- **FR-007**: The endpoint MUST return HTTP 422 with a structured error body identifying every
  failing field and its violation detail when any validation check fails. Single-field and
  multi-field violations must both be fully reported.

- **FR-008**: The endpoint MUST persist every received reading to the audit database —
  including rejected readings — recording status ACCEPTED or REJECTED plus rejection reason
  where applicable.

- **FR-009**: The endpoint MUST publish every accepted reading to the anomaly detection
  pipeline stream immediately after the audit database write is confirmed.

- **FR-010**: If the anomaly detection stream is unavailable, the system MUST record the
  stream failure as an infrastructure error, MUST NOT silently return success, and MUST
  indicate in its response that the reading was stored but not streamed.

- **FR-011**: If the audit database is unavailable, the system MUST return HTTP 503 and MUST
  NOT return a success response.

- **FR-012**: The endpoint MUST return a system-assigned unique reading identifier and a
  server-received timestamp in every successful response.

- **FR-013**: All I/O operations (database writes, stream publishing) MUST be performed
  non-blocking so that concurrent submissions from multiple devices do not queue behind
  each other.

- **FR-014**: Numeric sensor measurements MUST be non-negative. A reading containing a
  negative measurement MUST be rejected with HTTP 422.

### Key Entities

- **SensorReading**: The inbound payload from a factory device — captures device identity
  (device_id, device_type), batch context (batch_id), observation time (timestamp), and all
  sensor measurements (temperature, pressure, humidity, ph, flow_rate). All measurement fields
  are optional at the transport layer; applicability rules are enforced by CCP validation.

- **TelemetryLog**: The immutable audit record stored for every received reading — contains all
  SensorReading fields plus system-assigned reading_id, server_received_at timestamp, status
  (ACCEPTED / REJECTED), rejection_reason (if REJECTED), stream_published flag, and a
  stale_timestamp flag.

- **DeviceCCPThreshold**: The per-device-type definition of valid operating ranges — specifies
  minimum and maximum for each applicable measurement type. Loaded at startup; not modifiable
  at runtime via the API.

- **TelemetryEvent**: The message published to the anomaly detection stream for accepted
  readings — contains reading_id, all sensor values, device_id, device_type, batch_id, and
  server_received_at.

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: Every sensor submission receives a terminal response (HTTP 200, 422, or 503)
  within 300 ms under concurrent load from up to 50 simultaneous factory devices.

- **SC-002**: 100% of CCP range violations, unrecognised device types, and missing required
  fields are caught and returned as HTTP 422 responses — zero false-accepts on invalid
  readings.

- **SC-003**: Every accepted reading appears in the audit database and on the anomaly detection
  stream within 500 ms of server receipt under normal operating conditions.

- **SC-004**: Every rejected reading appears in the audit database with status REJECTED and a
  populated rejection_reason within 500 ms of receipt.

- **SC-005**: Zero sensor readings — valid or invalid — are silently discarded. Every
  submission results in either an audit database entry or a non-2xx HTTP response. There is no
  code path that returns HTTP 200 without a confirmed audit database write.

- **SC-006**: The unit test suite covers: valid submissions for each device type, each
  individual CCP parameter violation, multi-field simultaneous violations, unknown device_type,
  missing required fields, negative measurement values, audit database unavailability, and
  stream unavailability — with all tests passing.

---

## Assumptions

- **CCP thresholds**: Defaults assumed — Boiler (temp 120–200°C, pressure 1–12 bar),
  Pasteurizer (temp 72–90°C, pH 3.5–7.5, flow_rate 5–200 L/min), Dryer (temp 80–160°C,
  humidity 5–60%). These are configurable at system startup and not hardcoded in business
  logic.

- **Device type casing**: device_type matching is case-insensitive; "Boiler", "BOILER", and
  "boiler" all resolve to the boiler threshold set.

- **Device authentication**: Out of scope for v1 — any caller that knows the endpoint can
  submit readings. device_id is recorded for audit purposes but not authenticated against a
  device registry.

- **Stale timestamp**: Readings whose device timestamp differs from server_received_at by more
  than 5 minutes are accepted with a stale_timestamp flag set to true in TelemetryLog. They
  are not rejected, as clock drift is common in factory hardware.

- **Batch state**: Batch ID validity (whether the batch is active or exists in a registry) is
  not validated in v1. batch_id is captured as-is.

- **Measurement units**: All values use SI units — temperature in °C, pressure in bar,
  humidity in %, pH as a dimensionless value on the 0–14 scale, flow_rate in L/min.

- **Stream semantics**: The anomaly detection stream is a single fan-out channel; all
  downstream consumers subscribe independently. The ingestion endpoint is responsible only for
  publishing to the channel, not for consumer acknowledgement.

- **Deduplication**: No deduplication of readings in v1. Two readings with identical payloads
  receive separate reading_ids and are both stored.
