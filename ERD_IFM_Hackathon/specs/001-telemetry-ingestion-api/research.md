# Research: Telemetry Ingestion API

**Feature**: `001-telemetry-ingestion-api` | **Date**: 2026-06-09

All technical questions from the Technical Context were resolved using the user-supplied
constraints and project CLAUDE.md. No external research was required — all decisions were
pre-specified or follow directly from project conventions.

---

## Decision 1: Async SQLAlchemy with aiosqlite

**Decision**: Use `SQLAlchemy 2.0` async API with `aiosqlite` as the SQLite driver.
Engine URL: `sqlite+aiosqlite:///{SQLITE_DB_PATH}`

**Rationale**: The project is async-throughout (Constitution Principle VII). SQLAlchemy 2.0
native async support (`create_async_engine`, `AsyncSession`) gives us full non-blocking DB
access without a separate thread pool. `aiosqlite` is the standard async SQLite adapter
compatible with SQLAlchemy's async extension.

**Alternatives considered**:
- `databases` library: lighter, but lacks the ORM model layer needed for audit log integrity
  enforcement (no update/delete by convention on the ORM class)
- Synchronous SQLAlchemy in a thread executor (`asyncio.to_thread`): works but is an
  anti-pattern that hides blocking I/O

---

## Decision 2: Pydantic v2 for Structural Validation; CCP Logic in Route Handler

**Decision**: `SensorReading` Pydantic model validates field types, required fields, and
non-negative values only. CCP operating range validation runs as a pure function
(`validate_ccp_ranges`) inside the route handler — **not** as a Pydantic `@model_validator`.

**Rationale**: If CCP validation ran inside the Pydantic model, a violation would raise a
`ValidationError` before the route handler executes — making it impossible to write the
`REJECTED` record to the audit database before returning the 422. Constitution Principle II
(Immutable Audit Log) and spec FR-008 require that rejected readings are also persisted.
Separating structural validation (Pydantic) from domain validation (route handler) gives
us full control over the write order.

**Alternatives considered**:
- Custom FastAPI exception handler for `RequestValidationError` that writes to DB: possible
  but couples exception handling to business logic; harder to test in isolation
- `@model_validator(mode="after")` with a side-effectful DB call: violates Pydantic's pure
  validation contract and is not async-compatible cleanly

---

## Decision 3: Write Order — Redis First, DB Second (for ACCEPTED records)

**Decision**: For accepted readings, attempt Redis publish first, then INSERT to DB with
the captured `stream_published` outcome as a field value.

```
validate → try Redis → INSERT TelemetryLog(stream_published={result}) → respond
```

**Rationale**: Constitution Principle II forbids UPDATE on `TelemetryLog`. If we INSERT
first with `stream_published=False` then update after Redis succeeds, that violates the
append-only rule. By attempting Redis before the INSERT, we know the outcome at write time
and can include the correct `stream_published` value in the single INSERT.

Edge case: Redis succeeds but DB INSERT fails → we return 503; Redis has the event but no
audit record. This is the correct behaviour — the audit log is the ground truth and the
caller must retry. The reading was not lost from the operator's perspective (device gets
503 and retries).

For **rejected** readings: order is reversed — INSERT REJECTED record first (before 422),
so the audit trail exists even if the device ignores the error response.

**Alternatives considered**:
- INSERT first with `stream_published=False`, then a separate `PipelineError` table entry
  for Redis failures: more tables, more complexity, `stream_published` on TelemetryLog is
  always False (inaccurate for successes)
- Two-phase commit pattern: overkill for a single Redis publish; no distributed transaction
  needed

---

## Decision 4: redis.asyncio from redis-py ≥ 4.2

**Decision**: Use `redis.asyncio.Redis` from the `redis` package (≥ 4.2). The `aioredis`
standalone library was merged into redis-py and is now the recommended path.

**Rationale**: `redis-py` asyncio support is built-in as of 4.0, stable as of 4.2, and
is the upstream-recommended async Redis client for Python. No additional dependency.
Connection pool managed automatically.

**Alternatives considered**:
- `aioredis` (standalone): deprecated; merged into redis-py
- `coredis`: alternative async client; less ecosystem adoption; no advantage here

---

## Decision 5: CCP_THRESHOLDS as a Module-Level Dict (Not DB/Config File)

**Decision**: Define `CCP_THRESHOLDS` as a module-level dict in `src/api/schemas.py`.
Values are the spec defaults; they are overridable via environment variables at startup
if needed.

**Rationale**: The user specified "single file per component where possible" and "base
application only". A config file or DB table for thresholds adds infrastructure for a
v1 that has three device types with six threshold values total. Module-level constants
are the simplest compliant approach. Constitution Principle VII ("complexity for its own
sake is forbidden").

**Alternatives considered**:
- YAML/JSON config file loaded at startup: appropriate for future v2 when thresholds
  change frequently; over-engineered for v1
- `DeviceCCPThreshold` ORM table: adds migration complexity; thresholds are not user data
  and don't belong in the audit DB

---

## Decision 6: Unit Tests Only (No Integration Tests in This Feature)

**Decision**: Ship `tests/unit/` only for this feature. No integration tests requiring
a live Redis or SQLite connection.

**Rationale**: The user explicitly requested "Unit tests in tests/unit/" with no mention
of integration tests. All dependencies (DB session, Redis client) are injected via FastAPI's
`Depends()` and are trivially mockable with `AsyncMock`. The route handler, CRUD, and Redis
client can each be tested in full isolation, covering all spec success criteria.

**Alternatives considered**:
- Integration tests with a live SQLite test DB: appropriate for a later `/speckit-tasks`
  extension; out of scope for this feature's v1 deliverable
