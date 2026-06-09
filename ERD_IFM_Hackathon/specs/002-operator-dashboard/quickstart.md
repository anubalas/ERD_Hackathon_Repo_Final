# Quickstart: Streamlit Operator Dashboard

**Feature**: `002-operator-dashboard` | **Date**: 2026-06-09

---

## Prerequisites

- Virtual environment activated (`ERD_Hack_env`)
- Telemetry Ingestion API already set up (feature `001`) — the dashboard reads from the same SQLite DB
- At least a few rows in `telemetry_log` (run some curl requests against the API first)

---

## 1. Install Additional Dependency

```bash
pip install streamlit streamlit-autorefresh
```

---

## 2. Start the Dashboard

```bash
streamlit run src/dashboard/app.py
```

Opens at **http://localhost:8501**

---

## 3. Populate the Database (if empty)

Start the API first, then send some test readings:

```bash
# Valid boiler reading (ACCEPTED)
curl -X POST http://localhost:8000/telemetry \
  -H "Content-Type: application/json" \
  -d '{"device_id":"boiler-01","device_type":"boiler","temperature":165.0,"pressure":6.0,"batch_id":"BATCH-001","timestamp":"2026-06-09T08:00:00Z"}'

# CCP violation — pasteurizer too cold (REJECTED)
curl -X POST http://localhost:8000/telemetry \
  -H "Content-Type: application/json" \
  -d '{"device_id":"past-01","device_type":"pasteurizer","temperature":60.0,"ph":5.0,"flow_rate":50.0,"batch_id":"BATCH-001","timestamp":"2026-06-09T08:01:00Z"}'

# Dryer reading (ACCEPTED)
curl -X POST http://localhost:8000/telemetry \
  -H "Content-Type: application/json" \
  -d '{"device_id":"dryer-01","device_type":"dryer","temperature":120.0,"humidity":25.0,"batch_id":"BATCH-001","timestamp":"2026-06-09T08:02:00Z"}'
```

---

## 4. Verify Each Panel

**Live Feed tab**:
- Should show all 3 readings
- Boiler and dryer rows: green
- Pasteurizer row: red

**CCP Alerts tab**:
- Should show 1 alert (pasteurizer temperature violation)
- "Total CCP Violations: 1"

**Batch Audit tab**:
- Enter `BATCH-001` and click Search
- Should show all 3 readings for that batch in chronological order

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Could not connect to database" | Make sure the API has been started at least once (`uvicorn src.api.main:app`) so `init_db()` creates the SQLite file |
| Dashboard shows stale data | Wait for the 5-second auto-refresh, or switch tabs |
| `ModuleNotFoundError: streamlit` | Run `pip install streamlit streamlit-autorefresh` |
| Port 8501 already in use | Run `streamlit run src/dashboard/app.py --server.port 8502` |
