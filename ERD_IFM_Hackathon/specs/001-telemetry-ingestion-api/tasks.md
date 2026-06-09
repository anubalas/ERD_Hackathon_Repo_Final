---
description: "Task list for Telemetry Ingestion API"
---

# Tasks: Telemetry Ingestion API

**Input**: Design documents from `specs/001-telemetry-ingestion-api/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | data-model.md ✅ | contracts/ ✅ | research.md ✅

**Tests**: Unit tests included — requested in feature specification (tests/unit/).

**Organization**: Tasks grouped by user story. Each story is independently testable.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no upstream dependencies incomplete)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Exact file paths in every description

---

## Phase 1: Setup

**Purpose**: Project initialization — dependencies and test discovery scaffolding.

- [X] T001 Add required packages to requirements.txt: `fastapi>=0.111.0`, `uvicorn[standard]>=0.30.0`, `pydantic>=2.0.0`, `sqlalchemy[asyncio]>=2.0.0`, `aiosqlite>=0.20.0`, `redis[asyncio]>=4.2.0`, `httpx>=0.27.0`, `pytest>=8.0.0`, `pytest-asyncio>=0.23.0`
- [X] T002 [P] Create empty `tests/__init__.py` and `tests/unit/__init__.py` for pytest package discovery

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that ALL user stories depend on. No user story work begins
until this phase is fully complete.

**⚠️ CRITICAL**: Every item here blocks all user story phases.

- [X] T003 [P] Define `TelemetryLog` SQLAlchemy ORM model in `src/db/models.py`: columns `id` (PK autoincrement), `reading_id` (String 36, unique index), `device_id`, `device_type`, `temperature` (Float nullable), `pressure` (Float nullable), `humidity` (Float nullable), `ph` (Float nullable), `flow_rate` (Float nullable), `batch_id`, `device_timestamp` (DateTime), `server_received_at` (DateTime), `status` (String 10), `rejection_reason` (Text nullable), `stream_published` (Boolean default False), `stale_timestamp` (Boolean default False), `created_at` (DateTime server-default `func.now()`); add indexes on `batch_id`, `status`, `server_received_at`; no `update()`/`delete()` methods on the class

- [X] T004 [P] Create `SensorReading` Pydantic v2 model in `src/api/schemas.py`: `device_id: str` (non-empty), `device_type: str` (normalised to lowercase via `@field_validator`), `temperature/pressure/humidity/ph/flow_rate: Optional[float] = None` (each with `@field_validator` asserting `>= 0` if not None), `batch_id: str` (non-empty), `timestamp: datetime` (ISO 8601 with timezone); `device_type` must be one of `{"boiler", "pasteurizer", "dryer"}` after normalisation — raise `ValueError` with message `"Unknown device_type"` otherwise

- [X] T005 [P] Implement `RedisClient` class and `get_redis_client()` FastAPI dependency in `src/streaming/redis_client.py`: `RedisClient` wraps `redis.asyncio.Redis.from_url(settings.REDIS_URL)`; `async publish_telemetry(reading_id, reading, server_received_at)` serialises a `TelemetryEvent` dict to JSON and calls `await self.client.publish(channel, payload)`; raises `RedisPublishError(message, cause)` on any exception — never suppresses; `get_redis_client()` is an `AsyncGenerator` yielding a shared `RedisClient` instance; expose `RedisPublishError` as a module-level exception class

- [X] T006 Create async SQLAlchemy engine and session factory in `src/db/database.py`: `engine = create_async_engine(f"sqlite+aiosqlite:///{SQLITE_DB_PATH}", echo=False)`; `AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)`; `async def init_db()` calls `async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)`; `async def get_db_session()` yields an `AsyncSession`; imports `Base` and all models from `src/db/models.py` (depends T003)

- [X] T007 Add CCP configuration and response types to `src/api/schemas.py` (same file as T004 — complete after T004): add `CCPRange` dataclass (`min: float`, `max: float`); add `CCP_THRESHOLDS: dict[str, dict[str, CCPRange]]` with exact values from data-model.md — boiler `{temperature: [120,200], pressure: [1,12]}`, pasteurizer `{temperature: [72,90], ph: [3.5,7.5], flow_rate: [5,200]}`, dryer `{temperature: [80,160], humidity: [5,60]}`; add `CCPViolation` Pydantic model (`field: str`, `message: str`, `received: float`, `allowed_range: dict`); add `validate_ccp_ranges(reading: SensorReading) -> list[CCPViolation]` pure function that checks every non-None measurement field against the threshold for `reading.device_type` — boundary values inclusive; add `TelemetryResponse` Pydantic model (`reading_id: str`, `status: Literal["ACCEPTED"]`, `server_received_at: datetime`, `stream_published: bool`, `warnings: list[str] = []`) (depends T004 — same file, sequential)

- [X] T008 Implement `create_telemetry_log()` in `src/db/crud.py`: `async def create_telemetry_log(session: AsyncSession, *, reading: SensorReading, reading_id: str, server_received_at: datetime, status: str, rejection_reason: str | None, stream_published: bool, stale_timestamp: bool) -> TelemetryLog`; constructs `TelemetryLog` ORM instance, calls `session.add(log)` then `await session.commit()`, returns the committed instance; propagates any `SQLAlchemyError` to caller — no try/except; DO NOT add any `update_*` or `delete_*` functions to this module (depends T006)

- [X] T009 Create FastAPI app factory in `src/api/main.py`: `@asynccontextmanager async def lifespan(app)` calls `await init_db()` on startup and closes Redis client on shutdown; `app = FastAPI(title="IFM Telemetry Ingestion API", lifespan=lifespan)`; add `@app.exception_handler(Exception)` that logs full traceback with `logging.exception` and returns `JSONResponse({"detail": "Internal server error"}, status_code=500)` — never silent; imports and includes `telemetry_router` placeholder (add `pass` if router not yet written — it will be added in T015) (depends T006, T005)

- [X] T010 Create `tests/unit/conftest.py` with shared async test fixtures: `@pytest_asyncio.fixture async def mock_db_session()` returning `AsyncMock` with `add`, `commit`, `rollback`, `close`; `@pytest_asyncio.fixture async def mock_redis_client()` returning `AsyncMock(spec=RedisClient)` where `publish_telemetry` is an `AsyncMock`; `@pytest_asyncio.fixture async def async_test_client()` yielding `httpx.AsyncClient(app=app, base_url="http://test")` with DB and Redis dependencies overridden via `app.dependency_overrides`; add `asyncio_mode = "auto"` to `pytest.ini` or `pyproject.toml` (depends T009)

**Checkpoint**: Foundation complete — all user story phases may now begin in parallel.

---

## Phase 3: User Story 1 — Valid CCP Reading (Priority: P1) 🎯 MVP

**Goal**: Factory devices can submit valid sensor readings; readings are stored in the audit
database and published to the anomaly detection stream; HTTP 200 with reading_id is returned.

**Independent Test**: Submit valid readings for boiler, pasteurizer, and dryer via `AsyncClient`.
Verify HTTP 200, `reading_id` present in response body, `stream_published: true`, mock DB
`add()` called once, mock `publish_telemetry()` called once.

### Tests for User Story 1

- [X] T011 [P] [US1] Write `SensorReading` structural validation unit tests in `tests/unit/test_schemas.py`: valid reading for each of boiler/pasteurizer/dryer succeeds; missing `device_id` raises `ValidationError`; missing `batch_id` raises `ValidationError`; missing `timestamp` raises `ValidationError`; `temperature=-5.0` raises `ValidationError`; `device_type="BOILER"` normalises to `"boiler"` without error

- [X] T012 [P] [US1] Write `create_telemetry_log()` unit tests in `tests/unit/test_crud.py`: successful call with `AsyncMock` session returns `TelemetryLog` with correct `status="ACCEPTED"` and `stream_published=True`; when `session.commit` raises `SQLAlchemyError`, it propagates uncaught; assert `crud` module has no attribute `update_telemetry_log` or `delete_telemetry_log`

- [X] T013 [P] [US1] Write HTTP 200 happy-path route tests in `tests/unit/test_telemetry_route.py` using `async_test_client` fixture: POST valid boiler reading → 200, body contains `reading_id` (UUID format), `status=="ACCEPTED"`, `stream_published==true`, `warnings==[]`; repeat for pasteurizer and dryer; verify mock `create_telemetry_log` called with `status="ACCEPTED"`; verify mock `publish_telemetry` called once

### Implementation for User Story 1

- [X] T014 [US1] Implement `POST /telemetry` happy-path handler in `src/api/routes/telemetry.py`: `router = APIRouter()`; `@router.post("/telemetry", response_model=TelemetryResponse)`; `async def ingest_telemetry(reading: SensorReading, db=Depends(get_db_session), redis=Depends(get_redis_client))`; generate `reading_id = str(uuid4())`; compute `server_received_at = datetime.utcnow()`; set `stale_timestamp = abs((server_received_at - reading.timestamp.replace(tzinfo=None)).total_seconds()) > 300`; try `await redis.publish_telemetry(reading_id, reading, server_received_at)` and capture `stream_ok=True`; call `await crud.create_telemetry_log(db, reading=reading, reading_id=reading_id, server_received_at=server_received_at, status="ACCEPTED", rejection_reason=None, stream_published=stream_ok, stale_timestamp=stale_timestamp)`; return `TelemetryResponse(...)` (depends T007, T008, T005)

- [X] T015 [US1] Register telemetry router in `src/api/main.py`: replace placeholder with `from src.api.routes.telemetry import router as telemetry_router` and `app.include_router(telemetry_router)` inside the lifespan/app setup block (depends T014, T009)

**Checkpoint**: All 3 device types accepted end-to-end. Unit tests T011–T013 pass.

---

## Phase 4: User Story 2 — CCP Range Violation (Priority: P2)

**Goal**: Readings with out-of-range CCP measurements return HTTP 422 with per-field violation
detail; every rejected reading is persisted with `status=REJECTED` in the audit database.

**Independent Test**: POST pasteurizer reading with `temperature=60.0` (below 72°C minimum).
Expect HTTP 422, `detail` list contains one entry with `field=="temperature"`,
`allowed_range=={"min":72.0,"max":90.0}`; mock DB `add()` called with a `TelemetryLog`
where `status=="REJECTED"` and `rejection_reason` is non-empty.

### Tests for User Story 2

- [X] T016 [P] [US2] Write `validate_ccp_ranges()` unit tests in `tests/unit/test_schemas.py`: each CCP field (temperature/pressure/ph/flow_rate/humidity) for each device type returns one `CCPViolation` when below min or above max; boundary values (min and max exact) return empty list; multi-field violation (pasteurizer `temperature=60.0` AND `ph=9.0`) returns two violations simultaneously; valid reading returns `[]`

- [X] T017 [P] [US2] Write HTTP 422 CCP rejection route tests in `tests/unit/test_telemetry_route.py`: pasteurizer `temperature=60.0` → 422 with `detail[0].field=="temperature"`; boiler `pressure=15.0` → 422 with `detail[0].field=="pressure"`; multi-field pasteurizer violation → 422 with `len(detail)==2`; verify mock `create_telemetry_log` called with `status="REJECTED"` and `rejection_reason` non-empty; verify mock `publish_telemetry` NOT called for rejected readings

### Implementation for User Story 2

- [X] T018 [US2] Add CCP rejection branch to `src/api/routes/telemetry.py` (insert before the Redis publish step in T014's handler): call `violations = validate_ccp_ranges(reading)`; if `violations`: try `await crud.create_telemetry_log(db, ..., status="REJECTED", rejection_reason=str([v.model_dump() for v in violations]), stream_published=False, stale_timestamp=stale_timestamp)` — catch `Exception` here, log error with `logging.error`, do NOT reraise (DB failure on rejection must not mask the 422); `raise HTTPException(status_code=422, detail=[v.model_dump() for v in violations])` (depends T014)

**Checkpoint**: CCP violations → 422 with per-field detail. REJECTED records in audit DB.
Unit tests T016–T017 pass.

---

## Phase 5: User Story 3 — Unknown Device Type (Priority: P3)

**Goal**: Readings with an unrecognised `device_type` are rejected at the Pydantic validation
layer before CCP checking; the response clearly identifies the invalid field.

**Independent Test**: POST a reading with `device_type="mixer"`. Expect HTTP 422 from FastAPI
automatic validation; `detail[0].loc` includes `"device_type"`; mock DB is never called.

### Tests for User Story 3

- [X] T019 [P] [US3] Write device_type edge-case tests in `tests/unit/test_schemas.py`: `device_type="mixer"` raises `ValidationError` with message containing `"Unknown device_type"`; `device_type="PASTEURIZER"` normalises to `"pasteurizer"` without error; `device_type=None` raises `ValidationError`; POST `device_type="mixer"` via `async_test_client` returns HTTP 422 in `tests/unit/test_telemetry_route.py`

### Implementation for User Story 3

- [X] T020 [US3] Verify `device_type` `@field_validator` in `src/api/schemas.py` (from T004): confirm it (a) lowercases the value, (b) checks membership in `{"boiler","pasteurizer","dryer"}`, (c) raises `ValueError("Unknown device_type: {value}")` for anything else; update the validator in-place if the check from T004 is incomplete — no new file needed (depends T004)

**Checkpoint**: Unknown device types fail at Pydantic layer (HTTP 422). DB never called.
Unit tests T019 pass.

---

## Phase 6: User Story 4 — Downstream Infrastructure Fault (Priority: P4)

**Goal**: Valid readings are still persisted when Redis is unavailable (`stream_published=false`
in response with a warning); valid readings that cannot be persisted due to DB failure return
HTTP 503 — never HTTP 200. No exception is silently swallowed.

**Independent Test (Redis down)**: Mock `publish_telemetry` to raise `RedisPublishError`.
POST valid boiler reading → HTTP 200, `stream_published==false`, `warnings` list non-empty,
mock `create_telemetry_log` called with `stream_published=False`.

**Independent Test (DB down)**: Mock `create_telemetry_log` to raise `SQLAlchemyError`.
POST valid boiler reading → HTTP 503, `detail` contains "Audit database unavailable".

### Tests for User Story 4

- [X] T021 [P] [US4] Write Redis-failure route tests in `tests/unit/test_telemetry_route.py`: mock `publish_telemetry` raises `RedisPublishError`; POST valid reading → HTTP 200; assert `body["stream_published"] == false`; assert `body["warnings"]` is non-empty list; assert `body["reading_id"]` is present; assert mock `create_telemetry_log` called with `stream_published=False`

- [X] T022 [P] [US4] Write DB-failure route tests in `tests/unit/test_telemetry_route.py`: mock `create_telemetry_log` raises `SQLAlchemyError`; POST valid reading (with Redis mock succeeding) → HTTP 503; assert `body["detail"]` contains "Audit database unavailable"; assert response is NOT 200

### Implementation for User Story 4

- [X] T023 [US4] Add Redis failure branch to `POST /telemetry` handler in `src/api/routes/telemetry.py`: wrap the `await redis.publish_telemetry(...)` call in `try/except RedisPublishError as e`; on except: `stream_ok = False`; `warnings = ["anomaly detection stream unavailable — reading stored but not streamed"]`; `logging.error(f"Redis publish failed: {e}")` — do NOT reraise; proceed to DB write with `stream_published=False` (depends T014, T018 — update the handler added in T014)

- [X] T024 [US4] Add DB failure branch to ACCEPTED INSERT in `src/api/routes/telemetry.py`: wrap the `await crud.create_telemetry_log(... status="ACCEPTED" ...)` call in `try/except Exception as e`; on except: `logging.error(f"Audit DB write failed: {e}")`; `raise HTTPException(status_code=503, detail="Audit database unavailable — reading not persisted")`; this must be AFTER the Redis attempt (so `stream_published` is correct before the DB write) (depends T023)

**Checkpoint**: Redis down → HTTP 200 + `stream_published=false` + warning. DB down → HTTP 503.
Unit tests T021–T022 pass.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verification, coverage gate, and end-to-end quickstart validation.

- [X] T025 [P] Assert append-only contract in `tests/unit/test_crud.py`: add test that `hasattr(crud, "update_telemetry_log")` is False and `hasattr(crud, "delete_telemetry_log")` is False; add test that `TelemetryLog` class in `src/db/models.py` has no `update` or `delete` method

- [X] T026 [P] Run `pytest tests/unit/ -v --cov=src/api --cov=src/db --cov=src/streaming --cov-report=term-missing` and verify: all tests pass; coverage ≥ 95% for `src/api/schemas.py`, `src/api/routes/telemetry.py`, `src/db/crud.py`, `src/streaming/redis_client.py`; fix any failing tests before marking done

- [X] T027 Run quickstart.md end-to-end validation: (1) activate `ERD_Hack_env`; (2) confirm Redis running via `redis-cli ping`; (3) start `uvicorn src.api.main:app --port 8000`; (4) POST the valid boiler curl from quickstart.md; (5) verify HTTP 200 response with `reading_id`; (6) confirm `telemetry_log` row in `ifm_audit.db` via `sqlite3` query; (7) POST the CCP-violation curl; (8) verify HTTP 422 with temperature violation detail; (9) confirm REJECTED row in `ifm_audit.db`

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)
    └── Phase 2 (Foundational) ← BLOCKS EVERYTHING
            ├── Phase 3 (US1 — P1) 🎯 MVP
            │       └── Phase 4 (US2 — P2)  ← US1 handler must exist first (T014)
            │               └── Phase 5 (US3 — P3)  ← schema already in T004; lightweight
            │                       └── Phase 6 (US4 — P4)  ← handler must exist (T014)
            └── Phase 7 (Polish) ← after all user stories
```

### Within-Phase Dependencies

**Phase 2 — Parallel start group**: T003, T004, T005 (different files, no deps)
```
T003 ─► T006 ─► T008
T004 ─► T007
T005 ─► T009 ─► T010
T006 ─► T009
```

**Phase 3 — US1**: T011, T012, T013 are [P] (different files); T014 after foundation; T015 after T014

**Phase 4 — US2**: T016, T017 are [P] (different files); T018 after T014

**Phase 5 — US3**: T019 [P]; T020 lightweight verify after T004

**Phase 6 — US4**: T021, T022 are [P] (both in test_telemetry_route.py — wait, same file — T021 then T022 sequential); T023 after T014; T024 after T023

*Note*: T021 and T022 are both in `tests/unit/test_telemetry_route.py` — they must be sequential (same file). Remove [P] from T022.

**Phase 7**: T025, T026 [P]; T027 after T026

### User Story Dependencies

- **US1 (P1)**: Depends only on Phase 2 completion — no dependency on other stories
- **US2 (P2)**: Depends on US1 handler (T014) — adds a code branch to the same route
- **US3 (P3)**: Depends only on Phase 2 (T004) — Pydantic handles this; effectively parallel with US2
- **US4 (P4)**: Depends on US1 handler (T014) — adds error branches to the same route

---

## Parallel Execution Examples

### Phase 2 — Parallel Start

```
Parallel batch A (start immediately):
  Task: "Define TelemetryLog ORM model in src/db/models.py"          [T003]
  Task: "Create SensorReading Pydantic model in src/api/schemas.py"  [T004]
  Task: "Implement RedisClient in src/streaming/redis_client.py"     [T005]

After T003 completes:
  Task: "Create DB engine + init_db() in src/db/database.py"         [T006]

After T004 completes:
  Task: "Add CCP config + response types to src/api/schemas.py"      [T007]

After T006 completes:
  Task: "Implement create_telemetry_log() in src/db/crud.py"         [T008]

After T006 AND T005 complete:
  Task: "Create FastAPI app factory in src/api/main.py"              [T009]

After T009 completes:
  Task: "Create tests/unit/conftest.py with shared fixtures"         [T010]
```

### Phase 3 — US1 Tests (Parallel)

```
After T010 completes — all 3 test files are different → parallel:
  Task: "Write SensorReading tests in tests/unit/test_schemas.py"         [T011]
  Task: "Write create_telemetry_log tests in tests/unit/test_crud.py"     [T012]
  Task: "Write HTTP 200 route tests in tests/unit/test_telemetry_route.py" [T013]
```

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T002)
2. Complete Phase 2: Foundational (T003–T010) — CRITICAL gate
3. Complete Phase 3: User Story 1 (T011–T015)
4. **STOP AND VALIDATE**: Run `pytest tests/unit/ -v`; submit a valid reading via curl
5. MVP is shippable: valid readings ingested, stored, streamed

### Incremental Delivery

1. Phase 1–2 → Foundation ready (T001–T010)
2. Phase 3 → US1 done → test independently → **MVP demo**
3. Phase 4 → US2 done → test independently → CCP rejection working
4. Phase 5 → US3 done → test independently → all device validations locked
5. Phase 6 → US4 done → test independently → fault tolerance complete
6. Phase 7 → Polish → coverage gate → quickstart validated → **feature complete**

---

## Notes

- `[P]` = different files, no dependency on an incomplete upstream task
- `[USx]` label maps every implementation and test task to its user story for traceability
- Constitution Principle II: T012 and T025 explicitly assert the append-only contract
- Constitution Principle I: T021 (Redis-down) and T022 (DB-down) test the zero-silent-failure paths
- T018 is the only task where a DB exception is deliberately caught without re-raising — this is intentional: a DB failure on a REJECTED write must not replace the 422 response with a 500
- T014 (US1 happy path) and T018 (US2 CCP branch) and T023/T024 (US4 fault branches) all modify `src/api/routes/telemetry.py` — they must execute in that order to avoid merge conflicts on the same file
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& "c:\Users\ANUBALAS\Downloads\WORKING_JOBS_DOCS\ER&D_IFM_Hackathon\ERD_Hack_env\Scripts\Activate.ps1"