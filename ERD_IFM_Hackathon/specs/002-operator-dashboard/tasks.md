---
description: "Task list for Streamlit Operator Dashboard"
---

# Tasks: Streamlit Operator Dashboard

**Input**: Design documents from `specs/002-operator-dashboard/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | data-model.md ✅ | contracts/ ✅ | research.md ✅

**Tests**: Query-layer unit tests included (plan.md specifies `tests/unit/test_dashboard_queries.py`).

**Organization**: Tasks grouped by user story. Each story adds one query function + one UI tab — independently testable.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no upstream dependencies incomplete)
- **[Story]**: Which user story this task belongs to (US1–US3)
- Exact file paths in every description

---

## Phase 1: Setup

**Purpose**: Add new dependencies and create the dashboard package stub.

- [X] T001 Add `streamlit>=1.35.0`, `streamlit-autorefresh>=0.0.1`, `pandas>=2.0.0` to requirements.txt
- [X] T002 [P] Create empty `src/dashboard/__init__.py` for package discovery

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: App skeleton — DB engine, auto-refresh wiring, and tab layout. ALL user story phases depend on this.

**⚠️ CRITICAL**: No user story work begins until T003 is complete.

- [X] T003 Create `src/dashboard/app.py` skeleton: `st.set_page_config(page_title="IFM Operator Dashboard", layout="wide")`; import and call `st_autorefresh(interval=5000, key="dashboard_refresh")` at top of script; `SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "telemetry.db")`; module-level `engine = create_engine(f"sqlite:///{SQLITE_DB_PATH}", connect_args={"check_same_thread": False})` and `SessionLocal = sessionmaker(bind=engine)`; `st.title("IFM Operator Dashboard")`; `tab1, tab2, tab3 = st.tabs(["Live Feed", "CCP Alerts", "Batch Audit"])`; leave each tab body as `pass` for now (filled in US phases)

**Checkpoint**: Foundation complete — all user story phases may now begin.

---

## Phase 3: User Story 1 — Live Sensor Feed (Priority: P1) 🎯 MVP

**Goal**: Operators see the 50 most recent telemetry readings in a colour-coded table that auto-refreshes every 5 seconds.

**Independent Test**: Run `streamlit run src/dashboard/app.py` with a populated DB. The Live Feed tab shows rows with green/orange/red backgrounds based on status and stream_published. Wait 5 seconds — the table refreshes automatically. With an empty DB, a friendly empty-state message is shown.

- [X] T004 [US1] Implement `get_live_feed(session: Session) -> pd.DataFrame` in `src/dashboard/app.py`: query `SELECT * FROM telemetry_log ORDER BY server_received_at DESC LIMIT 50`; return result as `pd.DataFrame` with columns `server_received_at`, `device_id`, `device_type`, `batch_id`, `temperature`, `pressure`, `humidity`, `ph`, `flow_rate`, `status`, `stream_published`; return empty DataFrame with same columns if no records found

- [X] T005 [US1] Implement Live Feed tab body in `src/dashboard/app.py` (inside `with tab1:`): open `SessionLocal()` in `try/except sqlalchemy.exc.OperationalError`; on error show `st.error("Could not connect to database...")` and `st.stop()`; call `get_live_feed(session)`; show 4 `st.metric` columns: Total Readings, ACCEPTED, REJECTED, Stream Failures (`stream_published==False` and `status=="ACCEPTED"`); define `_colour_row(row)` returning `["background-color: #ffcccc"] * len(row)` if REJECTED, `["background-color: #ffe5b4"] * len(row)` if ACCEPTED + not stream_published, else `["background-color: #ccffcc"] * len(row)`; call `st.dataframe(df.style.apply(_colour_row, axis=1), use_container_width=True)` if df non-empty, else `st.info("No readings yet — waiting for sensor data.")`

- [X] T006 [P] [US1] Write unit tests for `get_live_feed()` in `tests/unit/test_dashboard_queries.py`: mock `Session` that returns 3 `TelemetryLog` ORM instances (one ACCEPTED+stream_published=True, one ACCEPTED+stream_published=False, one REJECTED) → assert returned DataFrame has 3 rows and correct `status` values; mock `Session` returning empty list → assert returned DataFrame is empty but has expected columns

**Checkpoint**: Live Feed tab functional. Auto-refresh working. Colour coding correct.

---

## Phase 4: User Story 2 — CCP Alerts Panel (Priority: P2)

**Goal**: Dedicated panel shows all REJECTED readings with device, violation detail, and timestamp — updated on the same 5-second cycle.

**Independent Test**: Insert a REJECTED record. Open CCP Alerts tab — record appears with non-empty rejection_reason. "Total CCP Violations: 1" metric shown. With no REJECTED records, friendly empty state is shown.

- [X] T007 [US2] Implement `get_alerts(session: Session) -> tuple[pd.DataFrame, int]` in `src/dashboard/app.py`: query `SELECT * FROM telemetry_log WHERE status='REJECTED' ORDER BY server_received_at DESC LIMIT 20`; also query `SELECT COUNT(*) FROM telemetry_log WHERE status='REJECTED'` for total; return `(DataFrame, total_count)`; return `(empty DataFrame, 0)` if no records

- [X] T008 [US2] Implement CCP Alerts tab body in `src/dashboard/app.py` (inside `with tab2:`): open `SessionLocal()` with same error handling as tab1; call `get_alerts(session)`; show `st.metric("Total CCP Violations", total_count)`; if df non-empty: truncate `rejection_reason` to 120 chars, display `st.dataframe` with all rows styled red (`["background-color: #ffcccc"] * len(row)`); else `st.success("No CCP violations detected — all readings within safe range.")`

**Checkpoint**: CCP Alerts panel shows REJECTED readings. Total count metric correct.

---

## Phase 5: User Story 3 — Batch Audit Trail (Priority: P3)

**Goal**: Operator enters a `batch_id` and sees the full chronological reading history for that batch — both ACCEPTED and REJECTED — persisted across auto-refresh.

**Independent Test**: Enter a known `batch_id` — results show all readings for that batch ordered by `device_timestamp`. Enter an unknown `batch_id` — friendly empty-state message. Clear the field — empty-state "Enter a batch ID" prompt shown. Trigger an auto-refresh while text is in the box — the search input is preserved.

- [X] T009 [US3] Implement `get_batch_audit(session: Session, batch_id: str) -> pd.DataFrame` in `src/dashboard/app.py`: query `SELECT * FROM telemetry_log WHERE batch_id = :batch_id ORDER BY device_timestamp ASC`; return result as DataFrame with columns `device_timestamp`, `device_id`, `device_type`, `temperature`, `pressure`, `humidity`, `ph`, `flow_rate`, `status`, `rejection_reason`, `stream_published`; return empty DataFrame if no records

- [X] T010 [US3] Implement Batch Audit tab body in `src/dashboard/app.py` (inside `with tab3:`): initialise `st.session_state["batch_search"] = ""` if key absent; `st.text_input("Search batch ID", key="batch_search")`; `st.button("Search")`; if session_state batch_search is non-empty: open `SessionLocal()`, call `get_batch_audit(session, st.session_state["batch_search"])`; display colour-coded dataframe if non-empty, else `st.warning(f"No records found for batch '{batch_id}'")`; if search box empty: `st.info("Enter a batch ID above to view its full audit trail.")`

**Checkpoint**: All 3 tabs functional. Search preserved across auto-refresh cycles.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T011 [P] Write unit tests for `get_alerts()` and `get_batch_audit()` in `tests/unit/test_dashboard_queries.py`: `get_alerts` with 2 REJECTED rows → (DataFrame with 2 rows, count=2); `get_batch_audit` with matching `batch_id` → DataFrame with correct rows ordered by `device_timestamp`; `get_batch_audit` with unknown `batch_id` → empty DataFrame

- [X] T012 [P] Run `pytest tests/unit/test_dashboard_queries.py -v` and verify all query tests pass; fix any failures before marking done

- [X] T013 Run quickstart.md smoke test: install `streamlit streamlit-autorefresh`; run `streamlit run src/dashboard/app.py`; verify Live Feed shows colour-coded rows; verify CCP Alerts tab shows violations; enter `BATCH-001` in Batch Audit search and verify all batch readings returned

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)
    └── Phase 2 (Foundational — T003) ← BLOCKS all user stories
            ├── Phase 3 (US1 — Live Feed)  🎯 MVP
            │       └── Phase 4 (US2 — CCP Alerts)   ← same file, after T005
            │               └── Phase 5 (US3 — Batch Audit) ← same file, after T008
            └── Phase 6 (Polish) ← after all user stories
```

### Within-Phase Dependencies

```
T001 → T003
T002 → T003
T003 → T004 → T005
T003 → T007 → T008
T003 → T009 → T010
T005, T008, T010 → T011 → T012 → T013
```

T006 [P] is parallel to T004/T005 — different file (`test_dashboard_queries.py` vs `app.py`).

### User Story Dependencies

- **US1 (P1)**: Depends only on T003 foundation
- **US2 (P2)**: Depends on US1 code being in `app.py` (same file — sequential)
- **US3 (P3)**: Depends on US2 code being in `app.py` (same file — sequential)

---

## Parallel Execution Examples

### Phase 1

```
Parallel:
  Task: "Add streamlit/pandas/streamlit-autorefresh to requirements.txt"   [T001]
  Task: "Create src/dashboard/__init__.py"                                  [T002]
```

### Phase 3 — US1

```
After T003:
  Sequential: T004 (get_live_feed) → T005 (Live Feed tab UI)
  Parallel:   T006 (test_dashboard_queries.py) ← different file, can run alongside T004
```

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. Complete Phase 1: T001, T002
2. Complete Phase 2: T003 (app skeleton)
3. Complete Phase 3: T004, T005 (Live Feed tab)
4. **STOP AND VALIDATE**: `streamlit run src/dashboard/app.py` — live feed with colour coding works
5. MVP is demoable: operators can see real-time sensor status

### Incremental Delivery

1. T001–T003 → Skeleton up (auto-refresh wired)
2. T004–T005 → US1 done → **MVP demo**
3. T007–T008 → US2 done → CCP alerts visible
4. T009–T010 → US3 done → Batch audit functional
5. T011–T013 → Tests passing + smoke validated → **Feature complete**

---

## Notes

- All 3 user stories modify the same file (`src/dashboard/app.py`) — they MUST be sequential
- T006 and T011 write to `tests/unit/test_dashboard_queries.py` — T006 first (US1 tests), T011 appends (US2+US3 tests)
- Constitution Principle I: every `SessionLocal()` call is wrapped in `try/except OperationalError` — no silent DB failures
- Constitution Principle II: no write operations anywhere in `app.py` — read-only throughout
- `_colour_row` function defined once before tab1 and reused across all three tabs
