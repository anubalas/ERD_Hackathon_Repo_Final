# Research: Anomaly Detection

**Feature**: 003-anomaly-detection
**Date**: 2026-06-09

---

## Decision 1: IsolationForest per-device-type vs. single global model

**Decision**: One IsolationForest model per device type (boiler, pasteurizer, dryer), stored as
separate `.pkl` files.

**Rationale**: Each device type has a distinct set of sensor features (boiler: temperature +
pressure; pasteurizer: temperature + pH + flow_rate; dryer: temperature + humidity). A single
global model would need to handle sparse feature vectors with many NaN columns, which degrades
IsolationForest performance and interpretability. Separate models are also independently
retrained when a device type's baseline changes without touching other device types.

**Alternatives considered**:
- Single model with NaN imputation (zero-fill): Rejected — zero-imputed values create artificial
  "normal" clusters that distort the anomaly boundary for unrelated features.
- Single model with one-hot device_type encoding: Rejected — adds categorical preprocessing
  complexity without benefit; device type is a partitioning key, not a feature.

---

## Decision 2: Feature extraction strategy

**Decision**: Maintain a `DEVICE_FEATURES` registry mapping device_type to the list of numeric
column names to extract from an incoming telemetry message. Missing keys default to `None` and
are not imputed — a message for an unknown device type is skipped.

```python
DEVICE_FEATURES = {
    "boiler":       ["temperature", "pressure"],
    "pasteurizer":  ["temperature", "ph", "flow_rate"],
    "dryer":        ["temperature", "humidity"],
}
```

**Rationale**: Explicit registry makes the feature→model mapping auditable and easy to extend
when new device types are added. No magic reflection or CSV-driven inference.

**Alternatives considered**:
- Auto-detect features from CSV columns at training time: Rejected — couples training data layout
  to runtime behaviour; fragile if CSV gains extra columns.

---

## Decision 3: Redis subscriber architecture (async vs. sync)

**Decision**: Use `redis.asyncio` (async pub/sub) inside an `asyncio.run()` event loop. The
subscriber runs as a standalone process (`python -m src.detection.subscriber`), separate from the
FastAPI process.

**Rationale**: Constitution Principle VII mandates async for all Redis operations. Running as a
separate process means the subscriber can be started/stopped independently of the API and avoids
event-loop contention. `asyncio.run()` is the simplest entry point for a long-running async loop.

**Alternatives considered**:
- Threading subscriber inside FastAPI lifespan: Rejected — event loop sharing between subscriber
  coroutines and FastAPI routes risks blocking; separation of concerns is cleaner.
- `redis` (sync) with `pubsub.listen()`: Rejected — blocks calling thread; incompatible with
  Constitution Principle VII (async-first).

---

## Decision 4: Redis reconnection strategy

**Decision**: Wrap the `pubsub.listen()` loop in a `while True` with exponential backoff retry
(1 s → 2 s → 4 s, capped at 30 s). On `ConnectionError`, recreate the `redis.asyncio.Redis`
client and re-subscribe before resuming.

**Rationale**: Redis pub/sub connections drop silently on network hiccups. A durable subscriber
MUST reconnect automatically (FR-002). Exponential backoff avoids hammering a recovering Redis
server. Capping at 30 s ensures the reconnect window stays within operator observability.

**Alternatives considered**:
- `redis-py` built-in auto-reconnect: Not available for pub/sub — only applies to command
  sockets, not subscribed connections.
- Immediate reconnect on every error: Rejected — floods logs and Redis server during outages.

---

## Decision 5: Model persistence format

**Decision**: `joblib.dump` / `joblib.load` for `.pkl` files. Store one file per device type:
`src/detection/models/{device_type}.pkl`. Each file contains a dict:
`{"model": IsolationForest, "trained_at": ISO8601 string, "version": semver string, "features": list}`.

**Rationale**: `joblib` is the scikit-learn recommended serialiser for NumPy-heavy objects.
Wrapping the model in a dict enables future addition of metadata fields without breaking the
load interface. Constitution Principle IV requires model version and training timestamp to be
captured in the artifact.

**Alternatives considered**:
- `pickle` directly: Rejected — `joblib` is faster for large arrays and is the sklearn default.
- `onnx` export: Rejected — over-engineered for this use case; IsolationForest → ONNX is not
  a standard path and adds a heavy dependency.

---

## Decision 6: Anomaly threshold application

**Decision**: Use `model.score_samples(X)` (returns a numpy array of scores; lower = more
anomalous). Compare each score to `ANOMALY_THRESHOLD` (default -0.1). If
`score < ANOMALY_THRESHOLD`, flag as anomaly.

**Rationale**: `score_samples` returns the raw anomaly score without applying the model's
built-in contamination cutoff, giving full control to the env-var threshold. This matches the
spec (FR-005, FR-006) and avoids the binary `predict()` API which hard-codes the contamination
parameter set at training time.

**Alternatives considered**:
- `model.predict()` (returns +1/-1): Rejected — threshold is baked into the model at training
  time and cannot be adjusted without retraining.

---

## Decision 7: Baseline CSV format and training pipeline

**Decision**: CSV columns: `device_type, temperature, pressure, humidity, ph, flow_rate,
batch_id, timestamp`. Rows with `NaN` in any feature column applicable to the device type are
dropped during training. `pandas.read_csv` is used for loading; `scikit-learn`'s
`IsolationForest(contamination='auto', random_state=42)` for fitting.

**Rationale**: `contamination='auto'` fits the model without assuming a specific anomaly rate in
the baseline — appropriate because the baseline is supposed to contain only clean data (so the
auto estimate of ~1% contamination is a safe default). `random_state=42` ensures reproducible
training runs. Dropping NaN rows (rather than imputing) is safe because the baseline is clean
data — NaN in the baseline most likely indicates a logging gap, not a sensor reading.

**Alternatives considered**:
- `contamination=0.05`: Rejected — arbitrary; `auto` is more principled for a clean baseline.
- Mean imputation of NaN: Rejected — misleads the model about normal operating range.

---

## Decision 8: Alert ORM and append-only enforcement

**Decision**: Add `Alert` ORM model to `src/db/models.py`. Implement `create_alert()` in
`src/db/crud.py` as an INSERT-only function. No `update_alert()` or `delete_alert()` functions
are defined. Constitution Principle II compliance verified by the absence of these methods.

**Rationale**: Constitution Principle II (Immutable Audit Log) is absolute. The simplest
enforcement is to never write the update/delete code paths — they cannot be called if they do
not exist.

**Alternatives considered**:
- Database-level trigger to block UPDATE/DELETE: Could be added as defence-in-depth in future,
  but SQLite trigger support is limited and out of scope for v1.

---

## Decision 9: PIPELINE_ERROR alert for scoring failures

**Decision**: If `score_samples()` raises any exception (model not loaded, feature extraction
fails, numpy error), catch the exception, log it with full context, and write a
`PIPELINE_ERROR` Alert record to the database (with `anomaly_score=None`, `error_detail` field
containing the exception message). Continue processing the next message.

**Rationale**: Constitution Principle I forbids silent failures on any sensor data processing
path. A scoring exception must be surfaced as an auditable event. Using an Alert record
(rather than a separate error table) keeps the audit trail in one queryable place.

**Alternatives considered**:
- Re-raise and crash the subscriber: Rejected — a single malformed message would stop all
  anomaly detection; Constitution Principle VII prefers degraded-but-operational.
- Log-only without DB write: Rejected — violates Principle I (alert must reach the audit log).
