# Feature Specification: Anomaly Detection

**Feature Branch**: `003-anomaly-detection`

**Created**: 2026-06-09

**Status**: Draft

**Input**: Build a scikit-learn IsolationForest anomaly detector that subscribes to the Redis
telemetry channel, scores each incoming reading against a trained baseline model, flags anomalies,
and writes alerts to the SQLite Alert table. Supports boiler, pasteurizer, and dryer devices.
Trains on data/telemetry_baseline.csv. Threshold configurable via ANOMALY_THRESHOLD env var
(default -0.1).

---

## User Scenarios & Testing

### User Story 1 — Live Telemetry Subscription (Priority: P1)

The anomaly detector runs as a long-lived background process. It subscribes to the Redis
`telemetry` pub/sub channel and receives every accepted sensor reading published by the
Telemetry Ingestion API. Each received message is decoded and passed to the scoring pipeline.
The subscriber tolerates transient Redis disconnections and reconnects automatically without
losing its subscription state.

**Why this priority**: Subscription is the entry point for the entire anomaly detection pipeline.
Without a working subscriber, no readings can be scored and no alerts generated. All downstream
functionality depends on this foundation.

**Independent Test**: Start the subscriber against a live Redis instance. Publish 5 test messages
to the `telemetry` channel. Verify all 5 are received and decoded without error. Simulate a
Redis disconnect; verify the subscriber reconnects and continues receiving messages.

**Acceptance Scenarios**:

1. **Given** the anomaly detector is running and Redis is available, **When** the Telemetry API
   publishes an accepted reading to the `telemetry` channel, **Then** the detector receives and
   decodes the message within 1 second of publication.

2. **Given** the anomaly detector is running, **When** Redis becomes temporarily unavailable and
   then recovers, **Then** the detector reconnects automatically and resumes consuming messages
   without manual restart.

3. **Given** a malformed message arrives on the channel (invalid JSON or missing required fields),
   **When** the detector attempts to decode it, **Then** the error is logged with the raw message
   content and processing continues — the subscriber does not crash.

4. **Given** the anomaly detector starts while Redis is unavailable, **When** Redis becomes
   available, **Then** the detector connects and begins consuming messages.

---

### User Story 2 — IsolationForest Anomaly Scoring (Priority: P2)

For each received telemetry reading, the detector extracts the numeric sensor features
applicable to the device type and feeds them into the trained IsolationForest model. The model
returns a decision score. If the score falls below the configured threshold (ANOMALY_THRESHOLD),
the reading is flagged as an anomaly. Normal readings are discarded after scoring. The model is
read-only at runtime — it was trained offline on clean batch baseline data and is loaded once
at startup.

**Why this priority**: Scoring is the core intelligence of the anomaly detection feature. It
distinguishes normal variation from genuine process deviations that warrant operator attention.

**Independent Test**: Load the trained model. Supply 10 readings drawn from the clean baseline
(expected: no anomalies) and 5 readings with deliberately out-of-distribution values (expected:
flagged as anomalies). Verify correct classification on all 15.

**Acceptance Scenarios**:

1. **Given** the model is loaded and a boiler reading arrives with temperature and pressure values
   consistent with the clean baseline, **When** the detector scores the reading, **Then** the
   decision score is above ANOMALY_THRESHOLD and the reading is not flagged.

2. **Given** a boiler reading arrives with temperature 210°C (well above normal operating range),
   **When** the detector scores the reading, **Then** the decision score falls below
   ANOMALY_THRESHOLD and the reading is flagged as an anomaly.

3. **Given** ANOMALY_THRESHOLD is set to -0.1 in the environment, **When** the detector starts,
   **Then** it loads and uses this threshold value without code changes.

4. **Given** a pasteurizer reading arrives, **When** scoring, **Then** only the features
   applicable to pasteurizer (temperature, ph, flow_rate) are extracted — boiler-only fields
   (pressure) are ignored so that missing fields do not cause scoring errors.

5. **Given** the model file is missing at startup, **When** the detector initialises, **Then** it
   logs a clear error and exits rather than starting with an uninitialised model.

---

### User Story 3 — Alert Persistence to Audit Log (Priority: P3)

When a reading is flagged as an anomaly, the detector writes an Alert record to the SQLite audit
database. The record captures the device identity, the anomaly score, the reading values that
triggered the alert, the batch context, and a UTC timestamp. Every alert is written exactly once;
the alert log is append-only and never updated or deleted.

**Why this priority**: Alerts are the output artifact of the anomaly detector. Without persistent
alerts the Streamlit dashboard cannot display them, the AI agent cannot retrieve them for analysis,
and the GMP audit trail is incomplete.

**Independent Test**: Trigger 3 anomalous readings (one per device type). Query the Alert table.
Verify 3 records exist with correct device_id, device_type, score, and timestamp. Confirm no
existing records were modified (append-only contract).

**Acceptance Scenarios**:

1. **Given** a reading is flagged as anomalous, **When** the detector writes the alert, **Then**
   an Alert record appears in the database within 500 ms containing device_id, device_type,
   anomaly_score, all sensor values, batch_id, and detected_at timestamp.

2. **Given** two anomalous readings arrive from the same device in quick succession, **When**
   both are flagged, **Then** two separate Alert records are written — no deduplication or
   suppression logic is applied in v1.

3. **Given** the SQLite database is temporarily unavailable when an anomaly is detected, **When**
   the write fails, **Then** the error is logged with full alert context (device_id, score, sensor
   values) and the subscriber continues processing subsequent messages.

4. **Given** the Alert table is queried, **When** inspecting the records, **Then** no UPDATE or
   DELETE operations have ever been issued against the table — the log is strictly append-only,
   satisfying Constitution Principle II.

---

### User Story 4 — Offline Model Training (Priority: P4)

An operator or developer runs the training script against the clean baseline CSV file to produce
a serialised IsolationForest model file. The training script loads the CSV, extracts numeric
sensor columns, fits one IsolationForest model per device type (boiler, pasteurizer, dryer),
and saves each model as a `.pkl` file in `src/detection/models/`. The baseline CSV must not be
modified. The training script is a one-shot offline tool — it is not invoked at runtime.

**Why this priority**: The scoring model must exist before the detector can start. Training is a
prerequisite for all other user stories. It is P4 because the baseline CSV and training script
can be prepared once and the resulting model files committed — subsequent runs of the detector do
not re-train.

**Independent Test**: Run the training script with the baseline CSV. Verify that three `.pkl`
files are created (one per device type), each loadable by scikit-learn. Score one sample from the
baseline CSV against each model; verify the score is above ANOMALY_THRESHOLD (clean data should
not be flagged).

**Acceptance Scenarios**:

1. **Given** `data/telemetry_baseline.csv` contains readings for boiler, pasteurizer, and dryer
   devices, **When** the training script runs, **Then** three model files are saved to
   `src/detection/models/` — one per device type.

2. **Given** the baseline CSV contains only clean (normal) readings, **When** each trained model
   scores a held-out sample from the same CSV, **Then** the proportion of samples flagged as
   anomalous is below 10% (IsolationForest contamination default).

3. **Given** the baseline CSV is missing or unreadable, **When** the training script runs, **Then**
   it exits with a clear error message — it does not produce partial model files.

4. **Given** model files already exist from a previous training run, **When** the training script
   runs again, **Then** the existing model files are overwritten with the freshly trained models.

---

### Edge Cases

- What happens when a telemetry message is received for an unknown device type? (Log a warning,
  skip scoring — the device has no trained model.)
- What happens when the baseline CSV contains no rows for a specific device type? (Training script
  logs a warning and skips that device type — no model file is produced for it.)
- What happens when ANOMALY_THRESHOLD is not set in the environment? (Default to -0.1.)
- What happens when the Redis channel receives a burst of 100+ messages per second? (Messages are
  processed sequentially; no message is dropped, but processing may lag behind — acceptable in v1.)
- What happens when the model pkl file is corrupt or was saved by a different scikit-learn version?
  (Detector logs the load error and exits — it does not start with an unusable model.)

---

## Requirements

### Functional Requirements

- **FR-001**: The detector MUST subscribe to the Redis `telemetry` pub/sub channel and consume
  all messages published to it while running.

- **FR-002**: The detector MUST automatically reconnect to Redis after a transient disconnection
  without requiring a manual restart.

- **FR-003**: Malformed or unparseable messages on the telemetry channel MUST be logged with the
  raw message content and skipped — they MUST NOT crash the subscriber.

- **FR-004**: For each received telemetry reading, the detector MUST extract the numeric sensor
  features applicable to that reading's device type and supply them to the corresponding trained
  IsolationForest model.

- **FR-005**: If the decision score returned by the model falls below ANOMALY_THRESHOLD, the
  reading MUST be flagged as an anomaly.

- **FR-006**: ANOMALY_THRESHOLD MUST be configurable via the `ANOMALY_THRESHOLD` environment
  variable and MUST default to -0.1 if not set.

- **FR-007**: The IsolationForest model MUST be read-only at runtime — it is loaded once at
  startup and never retrained from live data.

- **FR-008**: If the model file for a device type is missing at startup, the detector MUST log a
  clear error and exit — it MUST NOT start in a partially initialised state.

- **FR-009**: Every flagged anomaly MUST result in an Alert record written to the SQLite database
  containing: device_id, device_type, anomaly_score, all sensor values, batch_id, and detected_at
  timestamp.

- **FR-010**: The Alert table MUST be append-only. No UPDATE or DELETE operations MUST ever be
  issued against Alert records (Constitution Principle II).

- **FR-011**: If the database write fails for a flagged anomaly, the error MUST be logged with
  full alert context — the subscriber MUST continue processing subsequent messages.

- **FR-012**: The training script MUST load `data/telemetry_baseline.csv`, fit one IsolationForest
  model per device type, and save each model as a `.pkl` file in `src/detection/models/`.

- **FR-013**: The training script MUST be a standalone offline tool — it MUST NOT be invoked
  during normal detector operation.

- **FR-014**: Messages for device types with no trained model MUST be skipped with a logged
  warning — they MUST NOT cause a scoring error.

### Key Entities

- **TelemetryMessage**: The decoded payload received from the Redis channel — mirrors the
  TelemetryLog fields: device_id, device_type, sensor measurements, batch_id, reading_id,
  server_received_at.

- **AnomalyScore**: The intermediate result of model inference — contains the raw decision score
  from IsolationForest, the threshold applied, and a boolean `is_anomaly` flag.

- **Alert**: The persistent audit record written for each detected anomaly — captures device_id,
  device_type, anomaly_score, sensor_values (JSON), batch_id, reading_id, and detected_at (UTC).

- **BaselineDataset**: The training input — the `data/telemetry_baseline.csv` file containing
  labelled clean readings for all device types. Used offline only; never modified by any
  runtime component.

- **DeviceModel**: A per-device-type IsolationForest model serialised to a `.pkl` file. Loaded
  at detector startup. One model file per device type: `boiler.pkl`, `pasteurizer.pkl`,
  `dryer.pkl`.

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: The detector processes each incoming telemetry message and produces a scoring
  decision within 100 ms of receipt under normal load (single-threaded processing).

- **SC-002**: 100% of messages published to the Redis telemetry channel are received by the
  detector while it is running — zero messages are silently dropped.

- **SC-003**: Every anomaly flagged by the detector results in an Alert record in the database
  within 500 ms of the anomaly score falling below threshold.

- **SC-004**: The detector continues operating after a transient Redis disconnection, reconnecting
  without manual intervention.

- **SC-005**: The training script completes in under 60 seconds for a baseline CSV of up to
  10,000 rows per device type.

- **SC-006**: The unit test suite covers: message decoding, per-device feature extraction, above-
  and below-threshold scoring, alert DB writes, missing model at startup, malformed message
  handling, and training script output — all tests passing.

---

## Assumptions

- **One model per device type**: A single IsolationForest model covers all devices of the same
  type (e.g., one model for all boilers). Per-device-instance models are out of scope for v1.

- **Baseline CSV format**: The CSV has columns matching the sensor fields used in the API
  (device_type, temperature, pressure, humidity, ph, flow_rate). Rows with missing numeric values
  for applicable fields are dropped during training.

- **Redis channel name**: The detector subscribes to the channel named `telemetry` — the same
  channel the Telemetry Ingestion API publishes to.

- **Protocol**: Redis RESP2 (`protocol=2`) is used to avoid HELLO command compatibility issues
  with older Redis servers (same as the API's redis_client.py).

- **No cloud dependency**: All model files, the SQLite database, and the baseline CSV reside on
  local disk. No external ML platform or model registry is used.

- **No real-time retraining**: The baseline model is trained once on clean historical data. Live
  anomaly feedback does not retrigger training in v1.

- **Contamination parameter**: IsolationForest is initialised with `contamination='auto'` for
  training. The runtime threshold ANOMALY_THRESHOLD overrides the model's built-in cutoff.

- **Serial processing**: Messages are processed one at a time in a single async loop. Parallel
  scoring workers are out of scope for v1.
