# Infant Food Manufacturing — AI-Powered GMP Operations

> **Powering safer beginnings with AI — where every batch protects a life.**

An end-to-end AI monitoring system for infant food manufacturing facilities. Detects CCP deviations in real time, triggers an AI agent that retrieves SOP remediation steps via RAG, and surfaces everything to operators through a live Streamlit dashboard.

---

## Technology Stack

| Layer | Technology | Role |
|---|---|---|
| Telemetry API | FastAPI 0.111+ | Async REST ingestion of CCP sensor readings |
| Streaming | Redis 7+ (pub/sub) | Real-time sensor data fan-out to consumers |
| Anomaly Detection | scikit-learn IsolationForest + rolling window | Unsupervised ML deviation scoring |
| AI Agent | LangGraph + Claude `claude-sonnet-4-6` | GMP remediation guidance with SOP citations |
| Document Search | ChromaDB | Semantic RAG over SOP/GMP/regulatory corpus |
| Operator UI | Streamlit | Live dashboard — alerts, agent chat, audit trail |
| Audit Storage | SQLite + SQLAlchemy | Immutable log of all alerts, telemetry, agent runs |
| Python Runtime | Python 3.11 | All backend services |

---

## How to Run

### Step 1 — Install dependencies

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2 — Configure environment

```bash
cp .env.example .env
# Edit .env and fill in:
#   ANTHROPIC_API_KEY=sk-ant-...
#   OPENAI_API_KEY=...          (Capgemini gateway key, if using OpenAI route)
#   OPENAI_BASE_URL=https://openai.generative.engine.capgemini.com/v1
#   REDIS_URL=redis://localhost:6379
#   SQLITE_DB_PATH=./telemetry.db
#   CHROMA_PERSIST_DIR=./chroma_db
```

### Step 3 — Start Redis

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

### Step 4 — Start FastAPI (telemetry ingestion)

```bash
uvicorn src.api.main:app --reload --port 8000
```

### Step 5 — Train the ML anomaly model

```bash
python -m src.detection.anomaly --fit --data-path data/telemetry_baseline.csv
```

### Step 6 — Start the anomaly subscriber

```bash
python -m src.detection.subscriber
```

### Step 7 — Start the device simulators

```bash
# Run all three in separate terminals (or background them)
python -m src.simulators.boiler_sim
python -m src.simulators.pasteurizer_sim
python -m src.simulators.dryer_sim
```

### Step 8 — Start the Streamlit dashboard

```bash
streamlit run src/dashboard/app.py
```

Open http://localhost:8501 in your browser.

---

## Project Structure

```
ERD_IFM_Hackathon/
├── src/
│   ├── api/
│   │   ├── main.py             # FastAPI app entrypoint
│   │   ├── routes/telemetry.py # POST /telemetry — ingest sensor readings
│   │   └── schemas.py          # Pydantic models: SensorReading, BatchEvent
│   ├── streaming/
│   │   └── redis_client.py     # Redis pub/sub publisher & subscriber
│   ├── detection/
│   │   ├── anomaly.py          # IsolationForest fit/score + rolling window trend
│   │   ├── subscriber.py       # Redis subscriber → anomaly detection → alert
│   │   └── models/             # Persisted .pkl baseline model files (git-ignored)
│   ├── agent/
│   │   ├── agent.py            # LangGraph pipeline: rag_retrieve → call_llm → save_result
│   │   ├── tools.py            # Claude tools: query_alerts_db, search_gmp_docs, generate_report
│   │   └── prompts.py          # GMP system prompts with explainability rules
│   ├── rag/
│   │   ├── chroma_store.py     # ChromaDB collection init, embed & query
│   │   └── ingest.py           # SOP/GMP document ingestion pipeline
│   ├── db/
│   │   ├── database.py         # SQLAlchemy engine, session factory, schema migration
│   │   ├── models.py           # ORM: Alert, TelemetryLog, AgentRun, BatchRecord
│   │   └── crud.py             # DB helpers (append-only for audit integrity)
│   ├── dashboard/
│   │   ├── app.py              # Streamlit operator dashboard (main entrypoint)
│   │   └── chat.py             # GMP chat assistant page with agentic tool loop
│   └── simulators/             # Boiler, pasteurizer, dryer device simulators
├── docs/gmp/                   # Source SOP, HACCP, FDA, Codex Alimentarius docs
├── data/
│   └── telemetry_baseline.csv  # Clean batch data for IsolationForest training
├── tests/
│   ├── unit/
│   └── integration/
├── .env.example
├── requirements.txt
└── README.md
```

---

## Key Design Principles

- **Zero silent failures** — every telemetry error is logged and alerted.
- **Audit immutability** — SQLite log is append-only; no UPDATE/DELETE on alerts or telemetry.
- **Explainable AI** — every agent response cites SOP source, section, and confidence score.
- **Human-in-the-loop** — low-confidence recommendations are flagged for QA review.
- **Air-gapped ready** — all persistence is local (SQLite + ChromaDB); no cloud storage dependency.
