# Quickstart: AI Agent — GMP Remediation with RAG

**Feature**: 004-ai-agent-rag
**Date**: 2026-06-09

---

## Prerequisites

- Redis running on `localhost:6379`
- FastAPI telemetry API running on `http://localhost:8000`
- Anomaly detection subscriber running (feature 003)
- SQLite database initialised at `./ifm_audit.db` with `alerts` table populated
- Virtual environment activated (`source ERD_Hack_env/Scripts/activate`)
- Dependencies installed (`pip install -r requirements.txt`)
- `ANTHROPIC_API_KEY` set in `.env`

---

## Step 1: Create Sample GMP Documents

If `docs/gmp/` does not yet contain the four SOP text files, they will be created by the
implementation tasks. Each file covers one device type's CCP procedures:

```
docs/gmp/
├── boiler_sop.txt        # Steam boiler CCP: temperature 150–170°C, pressure 4–7 bar
├── pasteurizer_sop.txt   # Pasteuriser CCP: temperature 72°C+, pH 6.5–7.0, flow_rate ≥ 80 L/h
├── dryer_sop.txt         # Spray dryer CCP: temperature 100–130°C, humidity ≤ 40%
└── haccp_general.txt     # General HACCP deviation response procedures
```

---

## Step 2: Ingest Documents into ChromaDB

```bash
python -m src.rag.ingest
```

Expected output:
```
[INGEST] Deleting existing collection: gmp_docs
[INGEST] Creating collection: gmp_docs
[INGEST] Processing boiler_sop.txt        — 4 chunks
[INGEST] Processing pasteurizer_sop.txt   — 3 chunks
[INGEST] Processing dryer_sop.txt         — 3 chunks
[INGEST] Processing haccp_general.txt     — 5 chunks
[INGEST] Complete. 4 documents, 15 chunks stored in gmp_docs.
```

Verify idempotency by running again — should produce the same output with no duplicates.

---

## Step 3: Start the AI Agent

In a separate terminal:

```bash
python -m src.agent.agent
```

Expected startup output:
```
[AGENT] ChromaDB collection gmp_docs — 15 chunks loaded
[AGENT] Polling alerts every 10s ...
```

The agent now polls the `alerts` table every 10 seconds for unprocessed anomaly alerts.

---

## Step 4: Trigger an Anomaly Alert

Send an anomalous reading through the telemetry API (or insert directly into the DB for demo):

```bash
curl -s -X POST http://localhost:8000/telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "boiler-line-1",
    "device_type": "boiler",
    "temperature": 210.0,
    "pressure": 13.5,
    "batch_id": "BATCH-DEMO-001",
    "timestamp": "2026-06-09T10:00:00Z"
  }' | python -m json.tool
```

Within 10 seconds, the agent picks up the alert and logs:
```
[14:32:15] Processing alert_id=7 device=boiler batch=BATCH-DEMO-001
[14:32:16]   RAG: 3 chunks retrieved (boiler_sop.txt x2, haccp_general.txt x1)
[14:32:17]   Claude: confidence=0.87 citation=[Source: boiler_sop.txt, §3.2]
[14:32:17]   AgentRun saved: id=12
```

---

## Step 5: Verify AgentRun Was Written

```bash
python -c "
import sqlite3
conn = sqlite3.connect('./ifm_audit.db')
rows = conn.execute('''
    SELECT ar.id, a.device_id, ar.citation, ar.confidence_score, ar.requires_human_review
    FROM agent_runs ar
    JOIN alerts a ON ar.alert_id = a.id
    ORDER BY ar.id DESC LIMIT 5
''').fetchall()
for r in rows:
    print(r)
conn.close()
"
```

Expected: one row with a populated `citation` field and `requires_human_review = 0` (False).

---

## Step 6: View the Dashboard Tab

Open the Streamlit dashboard:

```bash
streamlit run src/dashboard/app.py
```

Navigate to the **AI Recommendations** tab. You should see:
- The AgentRun record for the boiler anomaly
- Green row background (confidence ≥ 0.7)
- Device ID, batch ID, anomaly score, SOP citation, and confidence score

---

## Test Scenarios

### Scenario: No SOP match (unknown device type)

Insert a test alert with `device_type = "unknown_device"`. The agent should:
1. Query ChromaDB — return no relevant chunks
2. Write AgentRun with `citation = ""`, `confidence_score = 0.0`, `requires_human_review = True`
3. Log `CITATION_VIOLATION`
4. Dashboard shows red row with "REQUIRES HUMAN REVIEW" badge

### Scenario: Low-confidence response

When Claude returns a confidence below 0.7, the AgentRun should have:
- `requires_human_review = True`
- Recommendation text containing "REQUIRES HUMAN REVIEW"
- Amber row in the dashboard

### Scenario: Agent restart idempotency

Stop and restart the agent. It should not reprocess already-handled alerts — the
`alert_id NOT IN (SELECT alert_id FROM agent_runs)` query filters them out.

---

## Running Unit Tests

```bash
# Unit tests only (no Redis, ChromaDB, or Anthropic API required)
pytest tests/unit/test_rag_ingest.py tests/unit/test_agent_run_crud.py tests/unit/test_citation_extraction.py -v
```
