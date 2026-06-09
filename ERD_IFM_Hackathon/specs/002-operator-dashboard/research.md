# Research: Streamlit Operator Dashboard

**Feature**: `002-operator-dashboard` | **Date**: 2026-06-09

---

## Decision 1: Auto-Refresh Mechanism

**Decision**: Use the `streamlit-autorefresh` package (`st_autorefresh(interval=5000)`).

**Rationale**: Streamlit's execution model reruns the entire script on each interaction. The cleanest way to trigger a timed rerun without blocking is `st_autorefresh`, which injects a JavaScript timer that triggers `st.rerun()` every N milliseconds without blocking the main thread or requiring a sleep loop. The alternative (`time.sleep(5); st.rerun()`) works but blocks the server thread for 5 seconds per session.

**Alternatives considered**:
- `time.sleep(5); st.rerun()` — simpler but blocks the thread; unacceptable with multiple concurrent operators.
- WebSocket / Redis subscribe — correct but over-engineered for v1; adds a second long-lived connection per session.

---

## Decision 2: Database Access — Sync SQLAlchemy (not async)

**Decision**: Use synchronous SQLAlchemy `create_engine` + `sessionmaker` with aiosqlite not required.

**Rationale**: Streamlit runs each page render as a synchronous Python function. Using `asyncio.run()` inside Streamlit leads to event loop conflicts with Streamlit's own internals. Synchronous SQLAlchemy with the standard `sqlite3` driver is the correct choice. The same `TelemetryLog` ORM model from `src/db/models.py` is reused read-only — no schema duplication.

**Alternatives considered**:
- Async SQLAlchemy + `asyncio.run()` — causes "event loop already running" errors inside Streamlit.
- Raw `sqlite3` module — avoids SQLAlchemy but duplicates column/type mapping already in `models.py`.

---

## Decision 3: Session State for Search Persistence Across Reruns

**Decision**: Store the `batch_id` search input in `st.session_state` so auto-refresh does not clear it.

**Rationale**: Streamlit reruns the full script on refresh. Without `st.session_state`, the search box reverts to empty on every rerun, breaking FR-010. Storing the search string in session state preserves it across auto-refresh cycles.

**Alternatives considered**:
- URL query params (`st.experimental_get_query_params`) — works but adds URL complexity; session state is simpler.

---

## Decision 4: Colour Coding via `st.dataframe` with pandas Styler

**Decision**: Use `pandas.DataFrame.style.apply()` to colour-code rows in the live feed table.

**Rationale**: `st.dataframe` accepts a pandas Styler object and renders row-level background colours in the browser. This is the idiomatic Streamlit approach for conditional formatting.

**Alternatives considered**:
- `st.table` — static, no styling API.
- Custom HTML with `st.markdown(unsafe_allow_html=True)` — works but fragile and harder to maintain.

---

## Decision 5: Single-File Dashboard

**Decision**: Implement the entire dashboard in `src/dashboard/app.py`.

**Rationale**: The spec constrains scope to read-only display logic across three panels. A single file keeps the implementation simple and avoids premature modularisation. Helper functions for DB queries are defined at module level in the same file.

**Alternatives considered**:
- Split into `src/dashboard/queries.py` + `src/dashboard/app.py` — justified if the query layer grows beyond 3 functions; deferred to a future iteration.

---

## Decision 6: DB Engine Scoping — Module-Level Singleton

**Decision**: Create the SQLAlchemy engine once at module level (`engine = create_engine(DATABASE_URL)`), not inside each query function.

**Rationale**: Streamlit reruns the script on every refresh. Creating a new engine per rerun would open a new connection pool every 5 seconds. A module-level singleton is created once per worker process and reused across reruns.

**Alternatives considered**:
- `@st.cache_resource` on an engine factory — equivalent but adds boilerplate; module-level is simpler for a single engine.
