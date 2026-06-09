# Research: AI Agent — GMP Remediation with RAG

**Feature**: 004-ai-agent-rag
**Date**: 2026-06-09

---

## Decision 1: LangChain ReAct agent vs. direct Anthropic SDK polling loop

**Decision**: Use the Anthropic SDK directly (`anthropic.Anthropic().messages.create()`) in a
simple polling loop rather than a full LangChain ReAct agent.

**Rationale**: Constitution Principle VII mandates `cache_control: ephemeral` on the system
prompt and SOP context blocks. LangChain's Anthropic integration does not expose per-message-block
`cache_control` parameters reliably — the raw Anthropic SDK does. For a hackathon demo with a
single retrieval-then-generate pattern, a ReAct loop adds no value over a direct call: there are
no multi-step tool invocations, only one RAG query followed by one Claude call. Direct SDK keeps
the code auditable and avoids hidden LangChain abstraction failures. LangChain is still used for
prompt template management (PromptTemplate) to keep the system prompt structured.

**Alternatives considered**:
- Full LangChain ReAct with `AnthropicLLM`: Rejected — does not support `cache_control` blocks
  in message content; adds >500 lines of agent/tool scaffolding for a single-step flow.
- LangChain `LLMChain` with Anthropic wrapper: Rejected — same `cache_control` limitation.

---

## Decision 2: ChromaDB embedding function

**Decision**: Use ChromaDB's built-in default embedding function
(`chromadb.utils.embedding_functions.DefaultEmbeddingFunction`) which wraps
`all-MiniLM-L6-v2` via the `chromadb` package. No external embedding API.

**Rationale**: Constitution Principle V (On-Premise Data Sovereignty) forbids external data
egress except the Anthropic API. Using an external embedding service (OpenAI embeddings,
Cohere, etc.) would violate this principle. `all-MiniLM-L6-v2` is bundled with ChromaDB,
runs locally, and performs well for short SOP document chunks.

**Alternatives considered**:
- OpenAI `text-embedding-ada-002`: Rejected — external API, violates Principle V.
- `sentence-transformers` directly: Would work but adds dependency; ChromaDB's default
  wraps the same model with simpler setup.

---

## Decision 3: Alert polling strategy

**Decision**: Simple `while True` polling loop sleeping 10 seconds between cycles. On each
cycle: query `SELECT * FROM alerts WHERE id NOT IN (SELECT alert_id FROM agent_runs)` to find
unprocessed alerts, process each in ascending `detected_at` order.

**Rationale**: Polling is the simplest reliable mechanism for a hackathon demo. Event-driven
alternatives (Redis pub/sub trigger from subscriber, SQLite WAL hook) add complexity without
meaningfully improving latency at the demo scale of ~1 alert per minute.

**Alternatives considered**:
- Redis pub/sub trigger: Subscriber publishes to a separate `alerts` channel when it writes
  an Alert. Rejected — ties agent startup order to subscriber startup; adds coordination
  complexity for a demo.
- SQLAlchemy event listener: Rejected — SQLite doesn't support server-side events; polling
  is the correct approach for local SQLite.

---

## Decision 4: Document chunking strategy

**Decision**: Fixed-size character chunking — 500-character chunks, 50-character overlap,
applied per document. Source filename stored as metadata on each chunk.

**Rationale**: For short SOP text files (expected 500–2000 chars each), fixed-size chunking
produces 1–5 chunks per document — appropriate for the demo. Sentence-boundary or
paragraph-aware splitting adds implementation complexity for minimal benefit at this scale.

**Alternatives considered**:
- `langchain.text_splitter.RecursiveCharacterTextSplitter`: Would work but adds LangChain
  dependency for a single utility function. Implemented manually in 10 lines instead.
- Per-paragraph splitting: Rejected — SOP files may have irregular paragraph structure.

---

## Decision 5: ChromaDB collection management and idempotency

**Decision**: On each ingestion run, delete and recreate the `gmp_docs` collection
(`client.delete_collection("gmp_docs")` if exists, then `client.create_collection(...)`).
This guarantees idempotency without tracking document IDs.

**Rationale**: For a hackathon demo with a small fixed corpus (4 files), full collection
rebuild is fast (<2s) and simpler than diffing existing document IDs. No stale chunks from
deleted or updated files can persist.

**Alternatives considered**:
- Upsert by document ID: Requires stable ID scheme per chunk; adds complexity.
- Check-then-skip existing: Fragile — doesn't handle file content updates.

---

## Decision 6: Claude response structure — JSON extraction

**Decision**: Instruct Claude via the system prompt to output a JSON block at the end of
its response in the format:
```json
{"citation": "...", "confidence": 0.85, "requires_human_review": false}
```
Extract the JSON block with a regex. If extraction fails (malformed or absent), set
`citation = ""`, `confidence = 0.0`, `requires_human_review = True`, log CITATION_VIOLATION.

**Rationale**: Structured output (JSON at end of free-text response) is the most reliable
way to extract machine-readable fields from Claude without using tool_use/function_calling,
which requires a separate API call pattern. The free-text recommendation is preserved for
human readability; the JSON block provides machine-extractable fields.

**Alternatives considered**:
- Tool use / function calling: Would give typed output but requires `tools` parameter and
  a different message flow. Adds complexity; JSON extraction from text is sufficient.
- Pure regex on free text for citation: Fragile — citation format may vary across responses.

---

## Decision 7: System prompt caching architecture

**Decision**: Three-block message structure:
1. Block 1 (system, cached): GMP agent role, citation mandate, response format instructions
2. Block 2 (system, cached): Retrieved SOP context from ChromaDB (changes per alert type,
   but same device type within a session → cache hit for repeated boiler/pasteurizer/dryer alerts)
3. User message: Alert details (device_id, device_type, sensor_values, anomaly_score)

**Rationale**: Constitution Principle VII mandates `cache_control: ephemeral` on both system
prompt and SOP context. The GMP system prompt is identical for all alerts — persistent cache.
The SOP context block changes only when device_type changes — high cache hit rate in production
where alerts cluster by device type.

**Alternatives considered**:
- Single cached system prompt with SOP context inline: Would work but loses fine-grained
  cache control; any alert from a new device type would invalidate the whole cache.

---

## Decision 8: AgentRun DB write and append-only enforcement

**Decision**: Add `AgentRun` ORM model to `src/db/models.py`. Add `create_agent_run()` and
`get_unprocessed_alerts()` to `src/db/crud.py`. No update/delete functions defined. Same
pattern as `Alert` table (Constitution Principle II).

**Rationale**: Consistent with existing audit table pattern. Append-only enforced by absence
of update/delete methods.

**Alternatives considered**:
- Status column update on Alert: Would require UPDATE on Alert table — violates Principle II.
  The join-based "unprocessed = no AgentRun" pattern avoids any mutation.

---

## Decision 9: Streamlit dashboard integration approach

**Decision**: Add a third tab `"🤖 AI Recommendations"` to the existing `src/dashboard/app.py`
using the existing sync SQLAlchemy engine and `SessionLocal`. Query:
```sql
SELECT ar.*, a.device_id, a.device_type, a.anomaly_score
FROM agent_runs ar
JOIN alerts a ON ar.alert_id = a.id
ORDER BY ar.created_at DESC LIMIT 20
```
Colour-code rows: green (confidence ≥ 0.7), amber (0.4–0.69, requires_human_review), red (< 0.4
or citation failed).

**Rationale**: Reuses existing sync SQLAlchemy pattern from 002-operator-dashboard. No new
session infrastructure needed. 20-row limit keeps the tab responsive without pagination.

**Alternatives considered**:
- Separate Streamlit page: Rejected — spec says "new tab in dashboard", not new page.
- Async SQLAlchemy in Streamlit: Rejected — Streamlit is sync; async session in sync context
  causes event loop conflicts (same issue addressed in 002-operator-dashboard research).
