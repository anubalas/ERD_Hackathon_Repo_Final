# Feature Specification: AI Agent — GMP Remediation with RAG

**Feature Branch**: `004-ai-agent-rag`

**Created**: 2026-06-09

**Status**: Draft

**Input**: Build a LangChain ReAct agent backed by Claude claude-sonnet-4-6 that processes
anomaly alerts, retrieves relevant GMP/SOP guidance via ChromaDB semantic search, generates
cited remediation recommendations, and displays results in the Streamlit operator dashboard.

---

## User Scenarios & Testing

### User Story 1 — GMP Document Knowledge Base (Priority: P1)

An operator starts the system and the ChromaDB vector store is pre-loaded with GMP and SOP
documents for all three device types (boiler, pasteurizer, dryer). When the AI agent runs a
semantic query against the knowledge base, it receives the top 3 most relevant document
chunks along with their source document names. The knowledge base is populated once during
setup and queried at runtime without modification.

**Why this priority**: The knowledge base is the foundation for every AI recommendation.
Without a working RAG store, the agent has no SOP context to cite, violating Constitution
Principle III (AI Citation Mandate) on every response. All downstream user stories depend on
this being operational.

**Independent Test**: Run the ingestion script against the four sample GMP text files. Query
"boiler temperature deviation procedure" and verify the response includes at least one chunk
from `boiler_sop.txt` with a source document name in the result. Query a dryer topic and
verify `dryer_sop.txt` is returned.

**Acceptance Scenarios**:

1. **Given** the four sample SOP text files exist in `docs/gmp/`, **When** the ingestion
   script runs, **Then** all files are chunked, embedded, and stored in ChromaDB without
   error, and the collection reports non-zero document count.

2. **Given** the ChromaDB store is populated, **When** a semantic query "pasteurizer
   temperature below minimum" is issued, **Then** the query returns 3 results, each
   containing a `source` metadata field matching the originating filename.

3. **Given** the ChromaDB store is populated, **When** the ingestion script is re-run,
   **Then** documents are not duplicated — existing embeddings are replaced or the collection
   is rebuilt cleanly.

4. **Given** `docs/gmp/` contains no files, **When** the ingestion script runs, **Then** it
   exits with a clear error message — it does not create an empty collection silently.

---

### User Story 2 — Alert Processing and Remediation Generation (Priority: P2)

When new anomaly alerts exist in the SQLite database that have not yet been processed by the
agent, the agent retrieves them, queries ChromaDB for relevant SOP guidance, calls Claude
claude-sonnet-4-6 with the alert context and retrieved SOP chunks, and saves the structured
response as an AgentRun record. Each response must include a cited SOP document and clause, a
confidence score between 0.0 and 1.0, step-by-step operator actions, and a human review flag
if confidence is below 0.7.

**Why this priority**: This is the core value of the AI agent — translating raw anomaly
scores into actionable, regulation-backed operator instructions. Without this, alerts are
numbers with no remediation guidance.

**Independent Test**: Insert one test Alert record per device type. Run the agent. Verify
three AgentRun records are created, each with a non-empty `recommendation`, a populated
`citation` field, a numeric `confidence_score`, and `requires_human_review` set to True
when confidence is below 0.7.

**Acceptance Scenarios**:

1. **Given** a boiler anomaly alert exists with temperature 210°C, **When** the agent
   processes it, **Then** an AgentRun record is saved containing a recommendation that
   references the boiler SOP document name and a specific clause number.

2. **Given** the agent generates a response, **When** the confidence score is below 0.7,
   **Then** the AgentRun record has `requires_human_review = True` and the recommendation
   text includes a clear "REQUIRES HUMAN REVIEW" notice.

3. **Given** ChromaDB returns no relevant SOP chunks for an anomaly, **When** the agent
   processes the alert, **Then** the AgentRun record has `requires_human_review = True`,
   the recommendation body contains `NO_CITATION_AVAILABLE`, and a CITATION_VIOLATION alert
   is logged — the incomplete response is never presented as authoritative guidance.

4. **Given** the agent has already processed an alert (AgentRun record exists for that
   alert_id), **When** the agent polls again, **Then** the already-processed alert is
   skipped — no duplicate AgentRun records are created.

5. **Given** the Claude API is temporarily unavailable, **When** the agent attempts to
   process an alert, **Then** the error is logged with the alert_id, processing continues
   for remaining alerts, and the failed alert remains unprocessed for the next poll cycle.

---

### User Story 3 — AI Recommendations Dashboard Tab (Priority: P3)

The Streamlit operator dashboard gains a new "AI Recommendations" tab. The tab displays the
latest AgentRun response for each recent alert, colour-coded by confidence level: green for
high confidence (≥ 0.7), amber for low confidence (0.4–0.69), and red for failed or
no-citation responses. Alerts that require human review are visually distinguished. The tab
refreshes on the same 5-second auto-refresh cycle as the existing dashboard.

**Why this priority**: The dashboard is the operator's window into the system. Surfacing AI
recommendations alongside live sensor data and alerts closes the loop from anomaly detection
to operator action. P3 because it depends on P1 and P2 delivering AgentRun records to display.

**Independent Test**: Insert 3 AgentRun records with different confidence scores (0.8, 0.5,
0.0). Open the dashboard, navigate to the AI Recommendations tab, and verify three rows with
correct colour coding and the human review banner on the low-confidence record.

**Acceptance Scenarios**:

1. **Given** AgentRun records exist, **When** the operator navigates to the AI
   Recommendations tab, **Then** each record is shown with: device_id, alert type, anomaly
   score, SOP citation, confidence score, recommendation summary, and human review indicator.

2. **Given** an AgentRun has `confidence_score >= 0.7`, **When** displayed in the tab,
   **Then** its row background is green.

3. **Given** an AgentRun has `confidence_score < 0.7` and `requires_human_review = True`,
   **When** displayed in the tab, **Then** its row background is amber and a
   "REQUIRES HUMAN REVIEW" badge is shown.

4. **Given** no AgentRun records exist yet, **When** the tab loads, **Then** it displays an
   empty state message — it does not crash or show an error traceback.

5. **Given** the anomaly detector and AI agent are not running, **When** the dashboard
   loads, **Then** all three tabs (Live Feed, Alerts, AI Recommendations) still load
   correctly with appropriate empty states — the dashboard is resilient to missing services.

---

### Edge Cases

- What happens when an alert's device_type has no matching SOP document in ChromaDB?
  (Agent returns `NO_CITATION_AVAILABLE`, sets `requires_human_review = True`.)
- What happens when an Alert record has `batch_id = NULL`? (GMP constraint: batch_id is
  required; agent skips the alert and logs a data integrity warning.)
- What happens when the confidence score returned by Claude is outside 0.0–1.0?
  (Clamped to valid range before storage; logged as a model output anomaly.)
- What happens when ChromaDB collection does not exist at agent startup?
  (Agent logs an error and exits — it does not start with an uninitialised RAG store.)
- What happens when multiple alerts arrive simultaneously? (Processed sequentially in
  order of `detected_at` ascending — no parallel Claude calls in v1.)

---

## Requirements

### Functional Requirements

- **FR-001**: The ingestion script MUST process all `.txt` files in `docs/gmp/`, split them
  into chunks of approximately 500 characters with 50-character overlap, embed each chunk,
  and store the embedding and source filename metadata in ChromaDB.

- **FR-002**: The ChromaDB collection MUST be queryable with a semantic string, returning
  the top 3 most relevant chunks with their source document name in the metadata.

- **FR-003**: The ingestion script MUST be idempotent — re-running it MUST NOT create
  duplicate chunks in the collection.

- **FR-004**: The agent MUST poll the SQLite Alert table for records with no corresponding
  AgentRun entry and process each unprocessed alert.

- **FR-005**: For each alert, the agent MUST execute a RAG query against ChromaDB using the
  alert's device_type and anomaly context as the query string.

- **FR-006**: The agent MUST call Claude claude-sonnet-4-6 with prompt caching enabled
  (`cache_control: ephemeral`) on both the GMP system prompt block and the retrieved SOP
  context block.

- **FR-007**: Every Claude response MUST be validated for the presence of a citation in the
  format `[Source: <doc_name>, §<section>.<clause>]`. Responses failing citation validation
  MUST have `requires_human_review = True` and a CITATION_VIOLATION logged.

- **FR-008**: Every AgentRun MUST store: alert_id, recommendation text, citation string,
  confidence_score (0.0–1.0), requires_human_review flag, model name, and created_at timestamp.

- **FR-009**: If `confidence_score < AGENT_HUMAN_REVIEW_THRESHOLD` (default 0.7), the agent
  MUST set `requires_human_review = True` before persisting the AgentRun record.

- **FR-010**: The AgentRun table MUST be append-only. No UPDATE or DELETE is permitted on
  AgentRun records (Constitution Principle II).

- **FR-011**: If the Claude API call fails, the error MUST be logged with the alert_id and
  the alert MUST remain unprocessed for the next poll cycle — no silent discard.

- **FR-012**: The Streamlit dashboard MUST include an "AI Recommendations" tab displaying
  AgentRun records with colour-coding by confidence level.

- **FR-013**: Four sample SOP text files MUST be created in `docs/gmp/` covering boiler,
  pasteurizer, dryer CCPs and general HACCP deviation procedures.

- **FR-014**: The agent MUST NOT issue any online model update, retraining, or ChromaDB
  collection schema change during normal alert processing.

### Key Entities

- **AgentRun**: The immutable audit record for each AI agent response — stores alert_id
  (FK to Alert), recommendation (full text), citation (extracted SOP reference), confidence_score,
  requires_human_review, model_name, raw_response (full LLM output for audit), created_at.

- **GmpChunk**: The in-memory object representing a retrieved ChromaDB document chunk —
  contains text, source filename, and relevance distance. Not persisted to SQLite.

- **GmpQuery**: The constructed query string derived from alert device_type and sensor
  values — used as the semantic search input to ChromaDB.

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: Each alert is processed (RAG query + Claude call + AgentRun saved) within
  10 seconds of being picked up by the agent poll cycle.

- **SC-002**: 100% of AgentRun records contain a non-empty citation field or have
  `requires_human_review = True` — zero records with empty citation and no review flag.

- **SC-003**: The agent correctly flags `requires_human_review = True` on 100% of responses
  where confidence_score < AGENT_HUMAN_REVIEW_THRESHOLD.

- **SC-004**: The Streamlit AI Recommendations tab loads in under 2 seconds and displays
  correct colour coding for all confidence tiers.

- **SC-005**: The RAG ingestion script completes for all four sample SOP documents in under
  30 seconds.

- **SC-006**: The unit test suite covers: RAG query returns top-3 results, citation
  validation pass and fail, confidence threshold flagging, duplicate alert skip, Claude API
  failure handling, and AgentRun append-only contract — all tests passing.

---

## Assumptions

- **Polling interval**: The agent polls the Alert table every 10 seconds. Streaming/push is
  out of scope for v1.

- **Embedding model**: ChromaDB default embedding function (`all-MiniLM-L6-v2` via
  `chromadb.utils.embedding_functions.DefaultEmbeddingFunction`). No external embedding API.

- **Chunk size**: 500-character chunks with 50-character overlap. No sentence-boundary
  splitting in v1 — simple fixed-size character splitting.

- **Single collection**: All SOP documents live in one ChromaDB collection named `gmp_docs`.
  No per-device-type sub-collections in v1.

- **Claude model**: Always `claude-sonnet-4-6`. No fallback to a smaller model (Constitution
  Principle VII).

- **No authentication**: The agent reads SQLite and ChromaDB directly by file path. No
  network auth to external services beyond the Anthropic API.

- **Sample SOP docs**: The four `.txt` files in `docs/gmp/` are manually authored for
  hackathon demo purposes. They contain realistic CCP procedures but are not official
  regulatory documents.

- **AGENT_HUMAN_REVIEW_THRESHOLD**: Default 0.7. Configurable via env var. Confidence
  below this value requires human review before any recommended action is taken.

- **Serial processing**: Alerts processed one at a time in ascending `detected_at` order.
  No concurrent Claude calls in v1.
