# Data Model: AI Agent — GMP Remediation with RAG

**Feature**: 004-ai-agent-rag
**Date**: 2026-06-09

---

## Entity: AgentRun

The immutable audit record written for every AI agent response. Append-only per Constitution
Principle II — no UPDATE or DELETE operations are permitted.

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| id | Integer (PK, autoincrement) | No | System-assigned unique run identifier |
| alert_id | Integer (FK → alerts.id) | No | The Alert record that triggered this agent run |
| recommendation | Text | No | Full free-text remediation guidance from Claude |
| citation | String(512) | No | Extracted SOP citation in format `[Source: <doc>, §<section>.<clause>]`. Empty string if extraction failed |
| confidence_score | Float | No | Confidence level from Claude response, clamped to 0.0–1.0 |
| requires_human_review | Boolean | No | True if confidence < threshold or citation extraction failed |
| model_name | String(64) | No | Claude model identifier used (always `claude-sonnet-4-6`) |
| raw_response | Text | No | Full unmodified Claude API response for audit purposes |
| created_at | DateTime (UTC) | No | Server UTC timestamp at the time the AgentRun was persisted |

**Constraints:**
- `alert_id` MUST reference an existing `alerts.id` — no orphaned AgentRun records
- `created_at` is set at INSERT time; never overwritten
- `confidence_score` is clamped to [0.0, 1.0] before storage; values outside this range are
  logged as model output anomalies
- `citation` MUST be non-empty OR `requires_human_review` MUST be True — SC-002 enforces this
- No UPDATE or DELETE functions defined in `crud.py` (Constitution Principle II)

**Relationships:**
- `alert_id` references `alerts.id` (soft FK — SQLite FK enforcement optional)
- Queried by the Streamlit dashboard AI Recommendations tab
- Used to detect already-processed alerts via JOIN (`WHERE alert_id NOT IN (SELECT alert_id FROM agent_runs)`)

---

## Entity: GmpChunk (Runtime, not persisted)

The in-memory object representing a single retrieved document chunk from ChromaDB. Never
written to SQLite — used only within the agent processing pipeline.

| Field | Type | Source |
|-------|------|--------|
| text | String | ChromaDB query result document content |
| source | String | Metadata field — originating `.txt` filename (e.g., `boiler_sop.txt`) |
| distance | Float | Cosine distance from ChromaDB (lower = more relevant) |

---

## Entity: GmpQuery (Runtime, not persisted)

The constructed semantic query string derived from alert fields. Used as the input to
ChromaDB semantic search.

| Field | Type | Description |
|-------|------|-------------|
| query_string | String | Concatenation of device_type, anomaly context, and sensor values. Example: `"boiler temperature deviation 210C pressure 13.5 bar CCP procedure"` |
| alert_id | Integer | Source alert ID for traceability in logs |
| device_type | String | Device type extracted from the Alert record |

---

## Entity: GmpDocument (File-based, read-only)

A sample SOP text file in `docs/gmp/`. These are the source documents ingested into ChromaDB.
Never modified at runtime.

| Field | Type | Description |
|-------|------|-------------|
| filename | String | e.g., `boiler_sop.txt`, `pasteurizer_sop.txt`, `dryer_sop.txt`, `haccp_general.txt` |
| content | String | Full text content of the SOP document |
| chunk_count | Integer (derived) | Number of 500-char chunks produced on ingestion |

**File locations:**
```
docs/gmp/boiler_sop.txt
docs/gmp/pasteurizer_sop.txt
docs/gmp/dryer_sop.txt
docs/gmp/haccp_general.txt
```

---

## ChromaDB Collection

| Property | Value |
|----------|-------|
| Collection name | `gmp_docs` |
| Embedding function | `DefaultEmbeddingFunction` (all-MiniLM-L6-v2, local) |
| Chunk size | 500 characters |
| Chunk overlap | 50 characters |
| Metadata per chunk | `{"source": "<filename>"}` |
| Persistence directory | `./chroma_db` (from `CHROMA_PERSIST_DIR` env var) |

**Idempotency**: On each ingestion run, the `gmp_docs` collection is deleted and recreated from
scratch. This guarantees no stale chunks from deleted or updated documents.

---

## Relationships Diagram

```
docs/gmp/*.txt
      │
      │  (offline ingestion only)
      ▼
ChromaDB gmp_docs collection (./chroma_db)
      │
      │  semantic query at runtime (read-only)
      ▼
GmpChunk[] (top 3 results)
      │
      ├── formatted as SOP context block
      ▼
Claude claude-sonnet-4-6 API call
      │
      ├── structured JSON block extracted
      ▼
AgentRun ──────────────────────────► SQLite agent_runs table
      │
      │  JOIN with alerts table
      ▼
Streamlit AI Recommendations tab


SQLite alerts table
      │
      │  polling query (unprocessed alerts)
      ▼
AI Agent polling loop
      │
      └── generates GmpQuery → ChromaDB → Claude → AgentRun
```
