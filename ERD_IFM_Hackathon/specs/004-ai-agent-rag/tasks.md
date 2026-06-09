# Tasks: AI Agent — GMP Remediation with RAG

**Input**: Design documents from `specs/004-ai-agent-rag/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: Included — SC-006 explicitly defines required unit test coverage (RAG query, citation validation, threshold flagging, duplicate skip, API failure handling, append-only contract).

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to ([US1], [US2], [US3])
- File paths follow single-project layout from plan.md

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package scaffolding and dependency updates needed before any story begins.

- [X] T001 Add `anthropic`, `chromadb`, and `langchain` to `requirements.txt`
- [X] T002 [P] Create empty package marker `src/rag/__init__.py`
- [X] T003 [P] Create empty package marker `src/agent/__init__.py`
- [X] T004 [P] Create directory `docs/gmp/` (four SOP text files land here in Phase 3)

**Checkpoint**: Package structure ready — US1 and Foundational work can begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: `AgentRun` DB model and CRUD functions that US2 and US3 both depend on.

**⚠️ CRITICAL**: US2 (agent writes AgentRun) and US3 (dashboard reads AgentRun) cannot proceed until this phase is complete.

- [X] T005 Add `AgentRun` ORM model to `src/db/models.py` — fields: id, alert_id, recommendation, citation, confidence_score, requires_human_review, model_name, raw_response, created_at (append-only per Constitution Principle II)
- [X] T006 Add `create_agent_run(session, ...)` INSERT-only function to `src/db/crud.py` — no update/delete (append-only contract)
- [X] T007 Add `get_unprocessed_alerts(session)` to `src/db/crud.py` — returns `List[Alert]` with no corresponding AgentRun (uses NOT IN subquery on alert_id)
- [X] T008 Verify `init_db()` in `src/db/database.py` creates `agent_runs` table — add `AgentRun` to `Base.metadata` if missing

**Checkpoint**: Foundation ready — `agent_runs` table exists, CRUD functions available. US1 can start immediately (independent); US2 and US3 can follow.

---

## Phase 3: User Story 1 — GMP Document Knowledge Base (Priority: P1) 🎯 MVP

**Goal**: ChromaDB vector store pre-loaded with SOP documents for all three device types. Semantic query returns top-3 chunks with source metadata. Ingestion script is idempotent.

**Independent Test**: Run `python -m src.rag.ingest`. Query ChromaDB with `"boiler temperature deviation procedure"` — verify at least one result has `source = boiler_sop.txt`. Re-run ingestion — verify collection chunk count is unchanged (no duplication). Run `pytest tests/unit/test_rag_ingest.py -v` — all tests pass.

### SOP Documents (FR-013)

- [X] T009 [P] [US1] Create `docs/gmp/boiler_sop.txt` — steam boiler CCP SOP covering: temperature CCP (150–170°C), pressure CCP (4–7 bar), §1 Normal Operation, §2 Temperature Deviation Procedure, §3 Pressure Deviation Procedure, §4 Emergency Shutdown, numbered clauses (§2.1, §2.2, §3.1 etc.), at least 800 characters total
- [X] T010 [P] [US1] Create `docs/gmp/pasteurizer_sop.txt` — pasteuriser CCP SOP covering: temperature CCP (≥72°C for ≥15s), pH CCP (6.5–7.0), flow rate CCP (≥80 L/h), §1 Normal Operation, §2 Temperature Below Minimum, §3 pH Deviation, §4 Flow Rate Reduction, numbered clauses, at least 800 characters total
- [X] T011 [P] [US1] Create `docs/gmp/dryer_sop.txt` — spray dryer CCP SOP covering: outlet temperature CCP (100–130°C), humidity CCP (≤40% RH), §1 Normal Operation, §2 Temperature Deviation, §3 Humidity Exceedance, §4 Product Hold Procedure, numbered clauses, at least 800 characters total
- [X] T012 [P] [US1] Create `docs/gmp/haccp_general.txt` — general HACCP procedures covering: §1 CCP Deviation Response, §2 Corrective Action Steps, §3 Batch Hold and Segregation, §4 Root Cause Investigation, §5 Verification and Record Keeping; references 21 CFR Part 110 and Codex Alimentarius CAC/RCP 1-1969, numbered clauses, at least 1000 characters total

### RAG Infrastructure (FR-001, FR-002, FR-003)

- [X] T013 [US1] Implement `src/rag/chroma_store.py` with: `init_collection(client, name)` that deletes and recreates collection for idempotency; `query_collection(collection, query_string, n_results=3)` that returns `List[dict]` with `text` and `source` keys; use `DefaultEmbeddingFunction` (no external embedding API, Constitution Principle V)
- [X] T014 [US1] Implement `src/rag/ingest.py` with: `chunk_document(text, chunk_size=500, overlap=50) -> List[str]`; `ingest_docs(docs_dir, chroma_dir, collection_name)` that reads all `.txt` files, chunks each, stores with `{"source": filename}` metadata; `__main__` argparse block accepting `--docs-dir`, `--chroma-dir`, `--collection`; exit code 2 with clear error message if no `.txt` files found (AC-4, FR-001)

### Tests for User Story 1 (SC-006)

- [X] T015 [US1] Write `tests/unit/test_rag_ingest.py` covering: `chunk_document()` produces correct count with 50-char overlap; `query_collection()` returns exactly 3 results each with `source` key (mock ChromaDB); idempotent re-ingest calls `delete_collection` before `create_collection` (mock); empty docs directory raises `SystemExit` with non-zero code

**Checkpoint**: US1 fully functional — ChromaDB ingestion works, semantic queries return sourced chunks, idempotency confirmed.

---

## Phase 4: User Story 2 — Alert Processing and Remediation Generation (Priority: P2)

**Goal**: Agent polls for unprocessed alerts, executes RAG→Claude pipeline, saves AgentRun with citation and confidence score. Handles Claude API failure without losing the alert.

**Independent Test**: Insert one test Alert per device type into SQLite. Run `python -m src.agent.agent` for one poll cycle. Verify three AgentRun records written with non-empty `recommendation`, populated `citation`, numeric `confidence_score`, and `requires_human_review=True` where `confidence < 0.7`. Run `pytest tests/unit/test_citation_extraction.py tests/unit/test_agent_run_crud.py -v` — all tests pass.

### Agent Prompt (FR-006, FR-007, Constitution Principle III)

- [X] T016 [US2] Implement `src/agent/prompts.py` with `GMP_SYSTEM_PROMPT` string that: establishes role as GMP compliance agent for infant food manufacturing; mandates `[Source: <doc_name>, §<section>.<clause>]` citation for every regulatory claim; requires confidence level as float in [0.0, 1.0]; requires "REQUIRES HUMAN REVIEW" text when confidence < 0.7 or no SOP match; instructs output of JSON block at **end** of response in format `{"citation": "...", "confidence": 0.85, "requires_human_review": false}` (Decision 6)

### Agent Core Logic (FR-004, FR-005, FR-006, FR-007, FR-008, FR-009, FR-011)

- [X] T017 [US2] Implement core functions in `src/agent/agent.py`: `extract_json_block(text) -> dict | None` using regex `r'\{[^{}]*"citation"[^{}]*"confidence"[^{}]*\}'`; `build_query(alert) -> str` concatenating device_type + sensor_values for semantic search; `clamp_confidence(value) -> float` clamping to [0.0, 1.0] with anomaly log if out of range; `apply_human_review_flag(run_data, threshold) -> dict` setting `requires_human_review=True` if `confidence < AGENT_HUMAN_REVIEW_THRESHOLD`
- [X] T018 [US2] Implement `process_alert(alert, collection, client, session)` in `src/agent/agent.py`: RAG query via `query_collection(collection, build_query(alert), n_results=3)`; if no chunks returned set `requires_human_review=True`, `citation=""`, log `CITATION_VIOLATION`; else call `client.messages.create()` with three-block cached structure (GMP_SYSTEM_PROMPT + SOP context both with `cache_control: {"type": "ephemeral"}` + alert user message); extract JSON block from response; fallback to `citation=""`, `confidence=0.0`, `requires_human_review=True` + `CITATION_VIOLATION` log if extraction fails (FR-007); clamp confidence; apply threshold; call `create_agent_run(session, ...)`
- [X] T019 [US2] Implement `polling_loop(session, collection, client, interval)` and `__main__` block in `src/agent/agent.py`: startup validation (ChromaDB collection exists → exit 1 if not; ANTHROPIC_API_KEY set → exit 1 if not); `while True` poll every `AGENT_POLL_INTERVAL` seconds; `get_unprocessed_alerts()` → process each serially in `detected_at` ASC order; `except anthropic.APIError` → log with alert_id, skip alert (remains unprocessed for next cycle, FR-011); graceful SIGINT/SIGTERM shutdown via `signal` handlers

### Tests for User Story 2 (SC-006)

- [X] T020 [US2] Write `tests/unit/test_citation_extraction.py` covering: `extract_json_block()` returns dict on valid JSON block at end of text; `extract_json_block()` returns `None` on malformed block; `extract_json_block()` returns `None` when block absent; `clamp_confidence()` returns 0.0 for negative, 1.0 for >1.0; `apply_human_review_flag()` sets `requires_human_review=True` when confidence < threshold; `apply_human_review_flag()` leaves `requires_human_review=False` when confidence ≥ threshold
- [X] T021 [US2] Write `tests/unit/test_agent_run_crud.py` covering: `create_agent_run()` writes all fields to in-memory SQLite; `get_unprocessed_alerts()` returns alert with no AgentRun; `get_unprocessed_alerts()` skips alert that already has an AgentRun record (duplicate skip, SC-006); append-only contract — assert `crud` module has no `update_agent_run` or `delete_agent_run` function; `process_alert()` with mocked `anthropic.APIError` → no AgentRun written, alert remains unprocessed

**Checkpoint**: US2 fully functional — agent processes alerts, writes cited AgentRun records, handles API failures gracefully.

---

## Phase 5: User Story 3 — AI Recommendations Dashboard Tab (Priority: P3)

**Goal**: Third "AI Recommendations" tab in Streamlit dashboard. Colour-coded by confidence. Human review badge on flagged records. Empty state when no records exist.

**Independent Test**: Insert 3 AgentRun records with `confidence_score` 0.8, 0.5, 0.0. Run `streamlit run src/dashboard/app.py`. Navigate to AI Recommendations tab — verify three rows with green/amber/red colouring respectively, amber row shows "REQUIRES HUMAN REVIEW" badge. Navigate to tab with empty DB — no crash, empty state message shown (AC-4 from US3).

### Dashboard Extension (FR-012)

- [X] T022 [US3] Extend `src/dashboard/app.py` to add third tab `"🤖 AI Recommendations"` alongside existing tabs using `st.tabs()`; query `agent_runs JOIN alerts ORDER BY ar.created_at DESC LIMIT 20` via existing sync `SessionLocal` (no new session infrastructure); display each row with: device_id, device_type, batch_id, anomaly_score, citation, confidence_score, recommendation summary (first 200 chars), created_at; apply colour coding using `st.markdown` with HTML `<div>` background style: green (`confidence >= 0.7`), amber (`0.4 ≤ confidence < 0.7` or `requires_human_review=True`), red (`confidence < 0.4` or `citation=""`); display `⚠️ REQUIRES HUMAN REVIEW` badge on flagged rows; show `st.info("No AI recommendations yet.")` when result set is empty (AC-4); tab loads without crash when `agent_runs` table is empty or does not contain records

**Checkpoint**: All three user stories fully functional. End-to-end pipeline: telemetry → anomaly → AgentRun → dashboard.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Environment config, quickstart validation, and full test suite run.

- [X] T023 [P] Update `.env.example` to include `CHROMA_PERSIST_DIR=./chroma_db`, `AGENT_HUMAN_REVIEW_THRESHOLD=0.7`, and `AGENT_POLL_INTERVAL=10` with inline comments explaining each variable
- [X] T024 Run `python -m src.rag.ingest` against `docs/gmp/` and verify output matches quickstart.md expected output (4 docs, ≥12 chunks, no errors)
- [X] T025 Run full unit test suite: `pytest tests/unit/test_rag_ingest.py tests/unit/test_citation_extraction.py tests/unit/test_agent_run_crud.py -v` — confirm all tests pass

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately; T002, T003, T004 can run in parallel
- **Foundational (Phase 2)**: Depends on Phase 1 — T005 → T006 → T007 → T008 must run sequentially (CRUD depends on model)
- **US1 (Phase 3)**: Depends on Phase 1 only — independent of Foundational; T009–T012 [P] in parallel, then T013, T014, T015
- **US2 (Phase 4)**: Depends on Foundational (Phase 2) and US1 (ChromaDB collection) — T016 → T017 → T018 → T019 sequential within story; T020 and T021 depend on T017–T019
- **US3 (Phase 5)**: Depends on Foundational (Phase 2) — T022 only; can run after Phase 2 independently of US1/US2
- **Polish (Phase 6)**: Depends on all user stories — T023 [P] anytime; T024 after US1; T025 after all test files written

### User Story Dependencies

- **US1 (P1)**: Independent of Foundational — can start after Phase 1. No cross-story dependencies.
- **US2 (P2)**: Depends on Foundational (AgentRun CRUD) and US1 (ChromaDB collection for RAG queries).
- **US3 (P3)**: Depends on Foundational (AgentRun model for JOIN query). Can start after Phase 2, independent of US1 and US2.

### Within Each User Story

- SOP document creation tasks [P] can all run simultaneously (different files)
- `chroma_store.py` (T013) before `ingest.py` (T014) — ingest imports from chroma_store
- `prompts.py` (T016) before `agent.py` core (T017) — agent imports GMP_SYSTEM_PROMPT
- Core agent functions (T017) before `process_alert` (T018) — process_alert calls extract_json_block and build_query
- `process_alert` (T018) before `polling_loop` (T019) — polling_loop calls process_alert
- Implementation tasks before test tasks (test imports require implementation to exist)

### Parallel Opportunities

```bash
# Phase 1 — all three init tasks in parallel:
T002: src/rag/__init__.py
T003: src/agent/__init__.py
T004: docs/gmp/ directory

# Phase 3 — all four SOP documents in parallel:
T009: docs/gmp/boiler_sop.txt
T010: docs/gmp/pasteurizer_sop.txt
T011: docs/gmp/dryer_sop.txt
T012: docs/gmp/haccp_general.txt

# Phase 4 tests can be split:
T020: test_citation_extraction.py  (tests extract_json_block, clamp, threshold)
T021: test_agent_run_crud.py       (tests CRUD, duplicate skip, API failure)
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup (T001–T004)
2. Complete Phase 3: US1 — SOP docs + RAG ingest + tests (T009–T015)
3. **STOP and VALIDATE**: `python -m src.rag.ingest` + query verification
4. Demo: ChromaDB loaded and returning relevant SOP chunks

### Incremental Delivery

1. Phase 1 + Phase 2 → Foundation ready (AgentRun table exists)
2. Phase 3 (US1) → RAG knowledge base working — independently demo-able
3. Phase 4 (US2) → AI agent processing alerts → AgentRun records in DB
4. Phase 5 (US3) → Dashboard tab showing colour-coded recommendations
5. Phase 6 → Polish and full test suite passing

### Parallel Team Strategy

With multiple developers:
1. Team completes Phase 1 + Phase 2 together
2. Developer A: Phase 3 (US1 — RAG ingest)
3. Developer B: Phase 4 (US2 — Agent core) — after Phase 2 completes
4. Developer C: Phase 5 (US3 — Dashboard tab) — after Phase 2 completes

---

## Notes

- [P] tasks operate on different files with no blocking dependencies — safe to parallelise
- [US*] labels map tasks to specific user stories for traceability to spec requirements
- SOP `.txt` files (T009–T012) must contain realistic CCP procedure text with numbered §sections
  and §clauses so citation extraction tests can verify the `[Source: <doc>, §N.N]` pattern
- `DefaultEmbeddingFunction` requires no API key and runs locally — do not substitute with an
  external embedding service (Constitution Principle V)
- Agent `__main__` must call `sys.exit(1)` if ChromaDB collection is missing at startup —
  not a silent no-op (Constitution Principle I)
- All three test files must be independently runnable with no live Redis, ChromaDB, or
  Anthropic API calls — use `unittest.mock.patch` throughout
