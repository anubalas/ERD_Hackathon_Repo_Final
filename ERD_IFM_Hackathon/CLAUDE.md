# Infant Food Manufacturing — AI-Powered GMP-Compliant Operations
### *Powering safer beginnings with AI — where every batch protects a life.*

---

## Mission

Infant food manufacturing has **zero tolerance for errors**. Even small deviations in temperature, pH, humidity, or ingredient ratios can affect product quality and directly threaten consumer safety — a population with no ability to self-advocate.

Current industry systems are mostly **reactive and manual**, creating dangerous delays between deviation occurrence and detection. This system shifts operations to **predictive, AI-driven monitoring** that:

- Detects failures early, before they become safety incidents
- Prevents GMP deviations rather than reacting to them
- Produces **explainable AI outputs** for audit readiness and regulatory trust
- Reduces manual monitoring burden without removing human oversight
- Ensures every batch is traceable, compliant, and safe

> *We are not just optimizing operations. We are safeguarding public health and building trust in critical life sciences products.*

---

## System Overview

```
"From data to trust — AI ensuring every batch is safe"

Sensor Devices (CCP sensors: temp, pH, humidity, flow)
      │  HTTP POST  /telemetry
      ▼
┌──────────────────────┐      pub/sub          ┌────────────────────┐
│   FastAPI            │ ───────────────────►  │      Redis         │
│   Telemetry          │  channel: telemetry   │  (Streams/PubSub)  │
│   Ingestion API      │                       └────────┬───────────┘
└──────────────────────┘                                │ subscribe
                                                        ▼
                                            ┌───────────────────────┐
                                            │   Anomaly Detector    │
                                            │   scikit-learn        │
                                            │   IsolationForest     │
                                            │   (trained on normal  │
                                            │    batch baselines)   │
                                            └──────────┬────────────┘
                                                       │ anomaly event
                                         ┌─────────────┴──────────────┐
                                         ▼                             ▼
                               ┌──────────────────┐         ┌──────────────────┐
                               │   AI Agent       │         │     SQLite       │
                               │   LangChain +    │         │   Audit Log DB   │
                               │   Claude         │         │  (alerts, batch  │
                               │   claude-sonnet  │         │   runs, telemetry│
                               │   -4-6           │         │   agent outputs) │
                               └────────┬─────────┘         └────────┬─────────┘
                                        │ RAG lookup                  │
                                        ▼                             ▼
                               ┌──────────────────┐       ┌──────────────────────┐
                               │    ChromaDB       │       │      Streamlit        │
                               │  SOP / GMP /      │       │   Operator Dashboard │
                               │  Regulatory Docs  │       │                      │
                               │  Vector Store     │       │  • Live sensor feed  │
                               └───────────────────┘       │  • Anomaly alerts    │
                                                           │  • AI remediation    │
                                                           │  • Batch audit trail │
                                                           └──────────────────────┘
```

---

## Technology Stack

| Layer | Technology | Role |
|-------|-----------|------|
| Telemetry API | FastAPI 0.111+ | Async REST ingestion of CCP sensor readings |
| Streaming | Redis 7+ (pub/sub + Streams) | Real-time sensor data fan-out to all consumers |
| Anomaly Detection | scikit-learn `IsolationForest` | Unsupervised ML deviation scoring against batch baseline |
| AI Agent | LangChain + Claude `claude-sonnet-4-6` | Explainable root-cause analysis + GMP remediation guidance |
| Document Search | ChromaDB | Semantic RAG over SOP, GMP, and regulatory PDF corpus |
| Operator UI | Streamlit | Live dashboard — alerts, agent chat, batch audit trail |
| Audit Storage | SQLite + SQLAlchemy | Immutable log of all alerts, telemetry, and agent responses |
| Python Runtime | Python 3.11 | All backend services |
| Local venv | `ERD_Hack_env/` | Development virtual environment |

---

## Project Structure

```
ERD_IFM_Hackathon/
├── CLAUDE.md               # This file — project context for AI coding agent
├── CONSTITUTION.md         # Non-negotiable project principles (GMP, safety, explainability)
├── PLAN.md                 # Active implementation plan (managed by /speckit-plan)
├── SPEC.md                 # Feature specification (managed by /speckit-specify)
│
├── src/
│   ├── api/
│   │   ├── main.py             # FastAPI app entrypoint
│   │   ├── routes/
│   │   │   └── telemetry.py    # POST /telemetry — ingest sensor readings
│   │   └── schemas.py          # Pydantic models: SensorReading, BatchEvent
│   │
│   ├── streaming/
│   │   └── redis_client.py     # Redis pub/sub publisher & async subscriber
│   │
│   ├── detection/
│   │   ├── anomaly.py          # IsolationForest fit/score, threshold logic
│   │   └── models/             # Persisted .pkl baseline model files
│   │
│   ├── agent/
│   │   ├── agent.py            # LangChain ReAct agent backed by Claude
│   │   ├── tools.py            # Tools: SOP search, alert lookup, batch history
│   │   └── prompts.py          # System prompts — GMP context, explainability rules
│   │
│   ├── rag/
│   │   ├── chroma_store.py     # ChromaDB collection init, embed & query
│   │   └── ingest.py           # PDF ingestion pipeline for SOP/GMP docs
│   │
│   ├── db/
│   │   ├── database.py         # SQLAlchemy engine, session factory
│   │   ├── models.py           # ORM: Alert, TelemetryLog, AgentRun, BatchRecord
│   │   └── crud.py             # DB read/write; append-only for audit integrity
│   │
│   └── dashboard/
│       └── app.py              # Streamlit operator dashboard
│
├── docs/
│   └── gmp/                    # Source SOP, GMP, Codex Alimentarius, FDA PDFs
│
├── data/
│   └── telemetry_baseline.csv  # Clean batch data for IsolationForest training
│
├── tests/
│   ├── unit/                   # Pure unit tests — no external services
│   ├── integration/            # Tests requiring Redis + SQLite
│   └── contract/               # FastAPI contract tests
│
├── specs/                      # SpecKit per-feature spec artifacts
│   └── [###-feature-name]/
│       ├── spec.md
│       ├── plan.md
│       └── tasks.md
│
├── requirements.txt
├── .env.example
└── .specify/                   # SpecKit tooling — do not edit manually
```

---

## Spec-Driven Development Workflow

This project enforces spec-driven development using SpecKit. No code is written before a feature has an approved `SPEC.md` and a `PLAN.md`.

| Document | Purpose | SpecKit Command |
|----------|---------|----------------|
| `CONSTITUTION.md` | Immutable principles — GMP compliance, explainability, zero data loss | `/speckit-constitution` |
| `SPEC.md` | Feature requirements, acceptance scenarios, success criteria | `/speckit-specify` |
| `PLAN.md` | Implementation plan — phases, file layout, technical decisions | `/speckit-plan` |

### Development Cycle

```
1. /speckit-specify    → Write SPEC.md from feature description
2. /speckit-clarify    → Resolve ambiguities before planning
3. /speckit-plan       → Generate PLAN.md with phases and structure
4. /speckit-tasks      → Generate dependency-ordered tasks.md
5. /speckit-implement  → Execute tasks one by one
6. /speckit-analyze    → Cross-artifact consistency check
```

All implementation decisions must trace back to a spec requirement. Constitution violations require explicit justification in the Complexity Tracking table.

---

## Shell Commands

### Environment Setup
```bash
# Activate virtualenv (Windows)
source ERD_Hack_env/Scripts/activate

# Install all dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY and other values
```

### Running Services
```bash
# FastAPI telemetry ingestion API (http://localhost:8000)
uvicorn src.api.main:app --reload --port 8000

# Streamlit operator dashboard (http://localhost:8501)
streamlit run src/dashboard/app.py

# Redis (Docker)
docker run -d -p 6379:6379 redis:7-alpine

# Ingest SOP/GMP documents into ChromaDB
python -m src.rag.ingest --docs-dir docs/gmp/

# Train IsolationForest on clean batch baseline data
python -m src.detection.anomaly --fit --data-path data/telemetry_baseline.csv
```

### Testing
```bash
# Unit tests only (no external services required)
pytest tests/unit/ -v

# Integration tests (requires Redis running)
pytest tests/integration/ -v

# Full suite with coverage
pytest --cov=src --cov-report=term-missing
```

---

## Environment Variables

```
ANTHROPIC_API_KEY=           # Claude API key — never commit to git
REDIS_URL=redis://localhost:6379
CHROMA_PERSIST_DIR=./chroma_db
SQLITE_DB_PATH=./ifm_audit.db
ANOMALY_THRESHOLD=-0.1       # IsolationForest decision score cutoff
LOG_LEVEL=INFO
```

---

## Critical Design Constraints

### Safety-First (Non-Negotiable)
- **Zero silent failures**: Every telemetry ingestion error must be logged and alerted. No swallowed exceptions on the sensor pipeline.
- **Audit immutability**: The SQLite log is append-only. No UPDATE or DELETE on `TelemetryLog`, `Alert`, or `AgentRun` records. These are the audit trail.
- **Anomaly model is read-only at runtime**: The IsolationForest baseline is retrained offline on clean batch data. It must never auto-update from live data.

### GMP Compliance & Explainability
- Every AI agent response **must cite** the specific SOP/GMP document, section, and clause it draws from. No uncited guidance.
- Agent responses must include a **confidence level** and a **human review flag** when the anomaly is novel or confidence is below threshold.
- All deviations, alerts, and agent recommendations must be timestamped and stored for regulatory inspection.

### Architecture
- **Async-first**: All FastAPI routes and Redis subscriptions use `async def`. Never block the event loop.
- **No cloud storage**: All persistent data stays on-premise — SQLite and ChromaDB on local disk. Air-gapped factory network assumption.
- **Claude model**: Always `claude-sonnet-4-6` for agent reasoning tasks. Do not downgrade to Haiku for GMP decisions.
- **Prompt caching**: Enable `cache_control: ephemeral` on the system prompt and SOP context in every Claude API call to minimize latency and cost.

---

## Claude API Pattern

All Claude calls in `src/agent/` must use this pattern — prompt caching is mandatory:

```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system=[
        {
            "type": "text",
            "text": GMP_SYSTEM_PROMPT,        # Role: GMP compliance agent for infant food mfg
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": retrieved_sop_context,    # RAG output from ChromaDB
            "cache_control": {"type": "ephemeral"},
        },
    ],
    messages=[{"role": "user", "content": anomaly_query}],
)
```

The system prompt must instruct the model to:
1. Always cite SOP/GMP source and clause
2. State confidence level
3. Flag for human review if uncertain
4. Never speculate on regulatory interpretations

---

<!-- SPECKIT START -->
**Active feature**: `002-operator-dashboard`

| Artifact | Path |
|----------|------|
| Spec | `specs/002-operator-dashboard/spec.md` |
| Plan | `specs/002-operator-dashboard/plan.md` |
| Data Model | `specs/002-operator-dashboard/data-model.md` |
| UI Contract | `specs/002-operator-dashboard/contracts/UI_CONTRACT.md` |
| Quickstart | `specs/002-operator-dashboard/quickstart.md` |
| Tasks | `specs/002-operator-dashboard/tasks.md` *(generated by /speckit-tasks)* |
<!-- SPECKIT END -->
