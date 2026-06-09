# CLI Contracts: AI Agent — GMP Remediation with RAG

**Feature**: 004-ai-agent-rag
**Date**: 2026-06-09

---

## Contract 1: RAG Ingestion Script

**Entry point**: `python -m src.rag.ingest`

### Invocation

```bash
# Ingest all .txt files from default docs directory
python -m src.rag.ingest

# Ingest from a custom docs directory
python -m src.rag.ingest --docs-dir path/to/sop/docs/

# Show help
python -m src.rag.ingest --help
```

### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--docs-dir` | No | `docs/gmp/` | Directory containing `.txt` SOP files to ingest |
| `--chroma-dir` | No | `./chroma_db` | ChromaDB persistence directory |
| `--collection` | No | `gmp_docs` | ChromaDB collection name |
| `--chunk-size` | No | `500` | Character size per chunk |
| `--chunk-overlap` | No | `50` | Character overlap between adjacent chunks |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All documents ingested successfully |
| 1 | `--docs-dir` not found or not a directory |
| 2 | No `.txt` files found in docs directory |
| 3 | ChromaDB write failure |

### Stdout (success)

```
[INGEST] Deleting existing collection: gmp_docs
[INGEST] Creating collection: gmp_docs
[INGEST] Processing boiler_sop.txt        — 4 chunks
[INGEST] Processing pasteurizer_sop.txt   — 3 chunks
[INGEST] Processing dryer_sop.txt         — 3 chunks
[INGEST] Processing haccp_general.txt     — 5 chunks
[INGEST] Complete. 4 documents, 15 chunks stored in gmp_docs.
```

### Stdout (error)

```
[ERROR] No .txt files found in docs/gmp/ — ingestion aborted
```

---

## Contract 2: AI Agent Process

**Entry point**: `python -m src.agent.agent`

### Invocation

```bash
# Start agent (reads ANTHROPIC_API_KEY, SQLITE_DB_PATH, CHROMA_PERSIST_DIR from .env)
python -m src.agent.agent

# Override poll interval (seconds)
python -m src.agent.agent --poll-interval 30
```

### Arguments / Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | **Yes** | — | Anthropic API key — never hardcoded |
| `SQLITE_DB_PATH` | No | `./ifm_audit.db` | Path to SQLite audit database |
| `CHROMA_PERSIST_DIR` | No | `./chroma_db` | ChromaDB persistence directory |
| `AGENT_POLL_INTERVAL` | No | `10` | Seconds between Alert table polls |
| `AGENT_HUMAN_REVIEW_THRESHOLD` | No | `0.7` | Confidence below this → requires_human_review=True |

### Lifecycle

```
startup:
  1. Verify ChromaDB gmp_docs collection exists — exit(1) if missing
  2. Verify ANTHROPIC_API_KEY is set — exit(1) if missing
  3. Connect to SQLite via SQLAlchemy
  4. Begin polling loop

per poll cycle (every AGENT_POLL_INTERVAL seconds):
  5. Query: SELECT * FROM alerts WHERE id NOT IN (SELECT alert_id FROM agent_runs)
             ORDER BY detected_at ASC
  6. For each unprocessed alert (serial):
     a. Build GmpQuery from device_type + sensor_values
     b. Query ChromaDB gmp_docs for top 3 chunks
     c. If no chunks: set requires_human_review=True, log CITATION_VIOLATION
     d. Call Claude claude-sonnet-4-6 with cached system prompt + SOP context + alert user message
     e. Extract JSON block from response: {"citation": "...", "confidence": 0.85, "requires_human_review": false}
     f. If JSON extraction fails: citation="", confidence=0.0, requires_human_review=True, log CITATION_VIOLATION
     g. Clamp confidence to [0.0, 1.0]
     h. Apply AGENT_HUMAN_REVIEW_THRESHOLD check
     i. INSERT AgentRun to SQLite
  7. If Claude API fails: log error with alert_id, skip alert (retry next poll cycle)

shutdown (SIGINT / SIGTERM):
  8. Close SQLAlchemy session
  9. Exit 0
```

### Stdout pattern

```
[AGENT] ChromaDB collection gmp_docs — 15 chunks loaded
[AGENT] Polling alerts every 10s ...
[14:32:15] Processing alert_id=7 device=boiler batch=BATCH-001
[14:32:16]   RAG: 3 chunks retrieved (boiler_sop.txt x2, haccp_general.txt x1)
[14:32:17]   Claude: confidence=0.87 citation=[Source: boiler_sop.txt, §3.2]
[14:32:17]   AgentRun saved: id=12
[14:32:27] No new alerts.
```

---

## Contract 3: AgentRun DB Schema (consumed by Dashboard)

The `agent_runs` table in SQLite is queried by the Streamlit AI Recommendations tab.

```sql
CREATE TABLE agent_runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id              INTEGER NOT NULL,           -- FK → alerts.id
    recommendation        TEXT    NOT NULL,           -- Full remediation text
    citation              TEXT    NOT NULL DEFAULT '', -- Extracted SOP reference
    confidence_score      REAL    NOT NULL,           -- 0.0–1.0
    requires_human_review INTEGER NOT NULL DEFAULT 0, -- Boolean (0/1)
    model_name            TEXT    NOT NULL,           -- 'claude-sonnet-4-6'
    raw_response          TEXT    NOT NULL,           -- Full LLM response for audit
    created_at            TEXT    NOT NULL            -- ISO 8601 UTC
);
```

### Dashboard Query (AI Recommendations tab)

```sql
SELECT
    ar.id,
    ar.alert_id,
    ar.recommendation,
    ar.citation,
    ar.confidence_score,
    ar.requires_human_review,
    ar.model_name,
    ar.created_at,
    a.device_id,
    a.device_type,
    a.anomaly_score,
    a.batch_id
FROM agent_runs ar
JOIN alerts a ON ar.alert_id = a.id
ORDER BY ar.created_at DESC
LIMIT 20
```

### Colour-coding Contract

| Condition | Dashboard colour |
|-----------|----------------|
| `confidence_score >= 0.7` | Green |
| `0.4 <= confidence_score < 0.7` OR `requires_human_review = True` | Amber |
| `confidence_score < 0.4` OR `citation = ""` | Red |

---

## Contract 4: Claude Response Format

Every Claude response MUST include a JSON block at the **end** of the free-text response
in this exact format:

```json
{"citation": "[Source: boiler_sop.txt, §3.2]", "confidence": 0.85, "requires_human_review": false}
```

### Extraction regex

```python
import re, json

JSON_PATTERN = re.compile(r'\{[^{}]*"citation"[^{}]*"confidence"[^{}]*\}', re.DOTALL)

def extract_json_block(response_text: str) -> dict | None:
    match = JSON_PATTERN.search(response_text)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None
```

### Failure fallback

If `extract_json_block()` returns `None`:
- `citation = ""`
- `confidence_score = 0.0`
- `requires_human_review = True`
- Log: `CITATION_VIOLATION alert_id=<id> — JSON block missing from Claude response`
