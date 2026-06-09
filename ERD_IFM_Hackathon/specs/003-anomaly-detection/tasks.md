# Tasks: Anomaly Detection

**Input**: Design documents from `specs/003-anomaly-detection/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/CLI_CONTRACT.md ✅

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story mapping (US1=Subscription, US2=Scoring, US3=Alert Persistence, US4=Training)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Detection package skeleton, Alert ORM model, and alert CRUD function — required by all user stories.

- [X] T001 Create `src/detection/__init__.py` (empty package marker)
- [X] T002 Create `src/detection/models/` directory with `.gitkeep` placeholder
- [X] T003 [P] Add `Alert` SQLAlchemy ORM model to `src/db/models.py` with fields: id, device_id, device_type, reading_id, batch_id, anomaly_score, alert_type, sensor_values, error_detail, detected_at
- [X] T004 [P] Add `create_alert()` INSERT-only function to `src/db/crud.py` — no update/delete (Constitution Principle II)
- [X] T005 Verify `init_db()` in `src/db/database.py` will create the `alerts` table (confirm Alert model is imported into Base metadata)

**Checkpoint**: Package skeleton exists, Alert ORM and CRUD are ready. Run `pytest tests/unit/` — existing tests must still pass.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Baseline CSV and `DEVICE_FEATURES` registry — prerequisite for training (US4) and scorer (US2).

**⚠️ CRITICAL**: Training must produce `.pkl` files before end-to-end integration testing of US1–US3 is possible.

- [X] T006 Create `data/telemetry_baseline.csv` with 50+ clean synthetic rows per device type (columns: device_type, temperature, pressure, humidity, ph, flow_rate, batch_id, timestamp) — values within normal CCP operating ranges
- [X] T007 Add `DEVICE_FEATURES` registry constant and empty `AnomalyScorer` class skeleton (with `load_models()` and `score()` stubs) to `src/detection/anomaly.py`

**Checkpoint**: `python -c "from src.detection.anomaly import AnomalyScorer, DEVICE_FEATURES; print(DEVICE_FEATURES)"` prints the registry without error.

---

## Phase 3: User Story 1 — Live Telemetry Subscription (Priority: P1) 🎯 MVP

**Goal**: Async Redis subscriber process that connects, subscribes to `telemetry` channel, decodes messages, and handles reconnects.

**Independent Test**: Start subscriber, publish 3 JSON messages to `telemetry` channel manually, confirm all are received and logged. Stop Redis; confirm reconnect loop activates.

### Implementation for User Story 1

- [X] T008 [US1] Create `src/detection/subscriber.py` — define `async def process_message(raw, scorer, session)` stub that decodes JSON and logs device_type
- [X] T009 [US1] Implement async Redis subscribe loop in `src/detection/subscriber.py` using `redis.asyncio.from_url(REDIS_URL, protocol=2)` — connect, subscribe to channel `telemetry`, call `process_message` for each message
- [X] T010 [US1] Implement exponential backoff reconnect loop in `src/detection/subscriber.py` — on `ConnectionError` sleep 1s → 2s → 4s (cap 30s) then recreate Redis client and re-subscribe
- [X] T011 [US1] Add graceful shutdown via `asyncio.Event` in `src/detection/subscriber.py` — handle SIGINT/SIGTERM, unsubscribe and close Redis connection cleanly
- [X] T012 [US1] Add `__main__` entry point in `src/detection/subscriber.py` — `asyncio.run(main())` loading env vars and creating DB session

**Checkpoint**: `python -m src.detection.subscriber` starts without error, connects to Redis, prints subscription confirmation. SIGINT exits cleanly.

---

## Phase 4: User Story 2 — IsolationForest Anomaly Scoring (Priority: P2)

**Goal**: `AnomalyScorer` class with working `load_models()` and `score()` methods; integrated into `process_message`.

**Independent Test**: Load a mock `.pkl` dict, call `scorer.score("boiler", {"temperature": 210.0, "pressure": 13.0})` — verify it returns `is_anomaly=True` when mock score is below threshold.

### Implementation for User Story 2

- [X] T013 [US2] Implement `load_models(models_dir)` in `src/detection/anomaly.py` — iterate `DEVICE_FEATURES` keys, call `joblib.load()` for each `.pkl`, store in `self._models` dict; raise `FileNotFoundError` with clear message if any model missing
- [X] T014 [US2] Implement `score(device_type, payload_dict)` in `src/detection/anomaly.py` — extract feature list from `DEVICE_FEATURES`, build numpy array, call `model.score_samples()`, compare to `ANOMALY_THRESHOLD`, return `(score: float, is_anomaly: bool)`; return `(None, False)` for unknown device types with WARNING log
- [X] T015 [US2] Integrate `scorer.score()` call into `process_message()` in `src/detection/subscriber.py` — replace stub with actual score call; log score and `OK`/`ANOMALY` result per CLI_CONTRACT.md stdout format
- [X] T016 [US2] Add `PIPELINE_ERROR` path in `process_message()` in `src/detection/subscriber.py` — wrap scorer call in `try/except Exception as exc`; on exception call `create_alert(session, alert_type="PIPELINE_ERROR", error_detail=str(exc), ...)` then `continue`

**Checkpoint**: With mock `.pkl` file in place, subscriber correctly logs `OK` for normal readings and `ANOMALY` for out-of-range readings.

---

## Phase 5: User Story 3 — Alert Persistence to Audit Log (Priority: P3)

**Goal**: Anomalous readings write `Alert(alert_type="ANOMALY")` records; scoring exceptions write `Alert(alert_type="PIPELINE_ERROR")` records. Both are verified in unit tests.

**Independent Test**: Trigger 3 anomalous readings (one per device type via mock). Query alerts table — confirm 3 ANOMALY records with correct device_id, score, and detected_at.

### Implementation for User Story 3

- [X] T017 [US3] Wire `create_alert(session, alert_type="ANOMALY", ...)` call in `process_message()` in `src/detection/subscriber.py` when `is_anomaly=True` — pass device_id, device_type, reading_id, batch_id, anomaly_score, sensor_values as JSON string, detected_at=UTC now
- [X] T018 [US3] Confirm `create_alert(session, alert_type="PIPELINE_ERROR", ...)` call in `process_message()` in `src/detection/subscriber.py` passes error_detail, device_id, batch_id, detected_at; anomaly_score=None
- [X] T019 [US3] Write unit tests for `create_alert()` in `tests/unit/test_alert_crud.py` using in-memory SQLite — verify all fields written correctly for ANOMALY type and PIPELINE_ERROR type
- [X] T020 [US3] Assert append-only contract in `tests/unit/test_alert_crud.py` — assert `update_alert` and `delete_alert` do not exist in `src/db/crud.py`

**Checkpoint**: `pytest tests/unit/test_alert_crud.py -v` passes all 4 tests. Query `ifm_audit.db` after running subscriber with anomalous readings — Alert records present.

---

## Phase 6: User Story 4 — Offline Model Training (Priority: P4)

**Goal**: `python -m src.detection.anomaly --fit` trains IsolationForest per device type from `data/telemetry_baseline.csv` and saves `.pkl` files to `src/detection/models/`.

**Independent Test**: Run training script; verify 3 `.pkl` files created; load each with `joblib.load()`; call `model["model"].score_samples([[...]])` — confirm no errors and score > -0.1 for baseline data.

### Implementation for User Story 4

- [X] T021 [US4] Implement `train(data_path, output_dir, version)` function in `src/detection/anomaly.py` — load CSV with pandas, group by device_type, drop NaN feature rows, fit `IsolationForest(contamination='auto', random_state=42)`, save dict `{"model": ..., "trained_at": ISO8601, "version": ..., "features": [...]}` via `joblib.dump()`
- [X] T022 [US4] Implement `argparse` `__main__` block in `src/detection/anomaly.py` — `--fit` flag required, `--data-path` (default `data/telemetry_baseline.csv`), `--output-dir` (default `src/detection/models/`), `--version` (default `1.0.0`)
- [X] T023 [US4] Run `python -m src.detection.anomaly --fit` and verify `src/detection/models/boiler.pkl`, `pasteurizer.pkl`, `dryer.pkl` are created; load each with joblib and confirm structure matches contract

**Checkpoint**: All 3 model files exist. `python -m src.detection.subscriber` loads them at startup without error. End-to-end path is now fully operational.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Unit tests, requirements verification, and quickstart validation.

- [X] T024 [P] Write unit tests for `AnomalyScorer` in `tests/unit/test_anomaly_scorer.py` — cover: feature extraction per device type, above-threshold (OK) scoring, below-threshold (ANOMALY) scoring, unknown device type skip, missing model file raises on load
- [X] T025 [P] Write unit tests for `process_message()` in `tests/unit/test_subscriber.py` — cover: normal reading (no alert), anomalous reading (ANOMALY alert), malformed JSON (PIPELINE_ERROR alert), scoring exception (PIPELINE_ERROR alert)
- [X] T026 Verify `scikit-learn` and `pandas` are in `requirements.txt`; add if missing
- [X] T027 Run `pytest tests/unit/ -v` — all tests pass; fix any failures

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion
- **US1 — Subscription (Phase 3)**: Depends on Phase 2 (needs `AnomalyScorer` stub)
- **US2 — Scoring (Phase 4)**: Depends on Phase 3 (integrates into subscriber)
- **US3 — Alert Persistence (Phase 5)**: Depends on Phase 4 (alert write triggered by score result)
- **US4 — Training (Phase 6)**: Depends on Phase 2 (baseline CSV must exist); independent of Phase 3–5
- **Polish (Phase 7)**: Depends on all prior phases

### Training vs. Runtime Dependency Note

US4 (training) is P4 in business value but produces the model artifacts needed for end-to-end
testing of US1–US3. Phases 3–5 can be fully unit-tested with mock models. Run Phase 6 (T021–T023)
before integration-testing the full subscriber pipeline.

### Within Each Phase

- Tasks marked `[P]` in the same phase have no file conflicts and can run in parallel
- T003 and T004 can run in parallel (different sections of different files)
- T024 and T025 can run in parallel (different test files)

---

## Parallel Opportunities

```
Phase 1: T003 and T004 in parallel (src/db/models.py vs src/db/crud.py)

Phase 7: T024 and T025 in parallel (separate test files)
```

---

## Implementation Strategy

### MVP (US1 + US2 + DB Schema)

1. Complete Phase 1 (Setup)
2. Complete Phase 2 (Foundational — DEVICE_FEATURES + baseline CSV)
3. Complete Phase 6 (T021–T023: train models)
4. Complete Phase 3 (US1: subscriber)
5. Complete Phase 4 (US2: scoring integration)
6. **VALIDATE**: Subscriber receives Redis messages and logs ANOMALY for out-of-range values

### Full Delivery

7. Complete Phase 5 (US3: alert writes)
8. Complete Phase 7 (polish + tests)
9. Run `pytest tests/unit/ -v` — all green

---

## Notes

- `[P]` = parallelisable — different files with no dependency on incomplete tasks
- US story labels trace each task back to the originating spec user story
- Constitution Principle I enforced: no scoring exception is silently swallowed
- Constitution Principle II enforced: `create_alert()` is INSERT-only; assert in T020
- Constitution Principle IV enforced: no `fit()` call reachable from subscriber process
- After T023, commit `.pkl` files or add to `.gitignore` depending on project policy
