# Quickstart: Telemetry Ingestion API

**Feature**: `001-telemetry-ingestion-api` | **Date**: 2026-06-09

---

## Prerequisites

- Python 3.11 installed
- Redis 7+ running locally on `localhost:6379`
- Virtual environment at `ERD_Hack_env/` already created (or create it per the step below)

---

## 1. Activate the Virtual Environment

```bash
# Windows (Git Bash or PowerShell)
source ERD_Hack_env/Scripts/activate
```

---

## 2. Install Dependencies

```bash
pip install -r requirements.txt
```

Key packages this feature requires (add to `requirements.txt` if not present):

```
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
pydantic>=2.0.0
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.20.0
redis[asyncio]>=4.2.0
httpx>=0.27.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

---

## 3. Configure Environment Variables

Copy `.env.example` to `.env` and set:

```bash
REDIS_URL=redis://localhost:6379
REDIS_CHANNEL=telemetry
SQLITE_DB_PATH=./ifm_audit.db
LOG_LEVEL=INFO
```

---

## 4. Start Redis (local, no Docker)

Redis must be running before the API starts. On Windows, install Redis via
[Memurai](https://www.memurai.com/) (Windows-native Redis) or WSL:

```bash
# WSL / Linux
redis-server

# Verify Redis is reachable
redis-cli ping
# Expected: PONG
```

---

## 5. Start the FastAPI Service

```bash
uvicorn src.api.main:app --reload --port 8000
```

Expected startup output:

```
INFO:     Started server process [...]
INFO:     Waiting for application startup.
INFO:     Audit database initialised at ./ifm_audit.db
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

---

## 6. Submit a Test Reading

### Valid boiler reading (expect HTTP 200):

```bash
curl -X POST http://localhost:8000/telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "device_id":   "boiler-line-1",
    "device_type": "boiler",
    "temperature": 165.3,
    "pressure":    5.8,
    "batch_id":    "BATCH-20260609-001",
    "timestamp":   "2026-06-09T08:00:00Z"
  }'
```

Expected response:

```json
{
  "reading_id": "<uuid>",
  "status": "ACCEPTED",
  "server_received_at": "2026-06-09T08:00:00.412Z",
  "stream_published": true,
  "warnings": []
}
```

### CCP violation — pasteurizer temperature too low (expect HTTP 422):

```bash
curl -X POST http://localhost:8000/telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "device_id":   "past-02",
    "device_type": "pasteurizer",
    "temperature": 60.0,
    "ph":          5.0,
    "flow_rate":   42.0,
    "batch_id":    "BATCH-20260609-001",
    "timestamp":   "2026-06-09T08:01:00Z"
  }'
```

Expected response:

```json
{
  "detail": [
    {
      "field": "temperature",
      "message": "Value 60.0 is below minimum 72.0 for pasteurizer",
      "received": 60.0,
      "allowed_range": {"min": 72.0, "max": 90.0}
    }
  ]
}
```

---

## 7. Verify Audit Log

```bash
# Open SQLite DB and check the log
sqlite3 ifm_audit.db "SELECT reading_id, device_type, status, stream_published FROM telemetry_log ORDER BY created_at DESC LIMIT 5;"
```

---

## 8. Run Unit Tests

```bash
# Run all unit tests for this feature
pytest tests/unit/ -v

# Run with coverage
pytest tests/unit/ --cov=src --cov-report=term-missing
```

Expected: all tests pass. Coverage target: 100% of the following modules:
- `src/api/schemas.py`
- `src/api/routes/telemetry.py`
- `src/db/crud.py`
- `src/streaming/redis_client.py`

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `redis.exceptions.ConnectionError` on startup | Redis not running | Start Redis (`redis-server`) |
| `sqlite3.OperationalError: no such table` | `init_db()` not called | Check lifespan in `main.py` |
| `422 Unprocessable Entity` on a valid reading | Wrong field type or missing field | Check that `timestamp` is ISO 8601 with timezone |
| `stream_published: false` in response | Redis down after startup | Restart Redis; reading is safely stored in audit DB |
