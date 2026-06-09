"""AI agent polling loop: detect unprocessed anomaly alerts → RAG → Claude → AgentRun.

Usage:
    python -m src.agent.agent
    python -m src.agent.agent --poll-interval 30
"""
import argparse
import json
import logging
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone

import anthropic
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent.prompts import GMP_SYSTEM_PROMPT
from src.db.crud import create_agent_run, get_unprocessed_alerts
from src.db.models import Alert
from src.rag.chroma_store import get_chroma_client, get_collection, query_collection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MODEL_NAME = "claude-sonnet-4-6"
AGENT_HUMAN_REVIEW_THRESHOLD = float(
    os.getenv("AGENT_HUMAN_REVIEW_THRESHOLD", "0.7")
)
AGENT_POLL_INTERVAL = int(os.getenv("AGENT_POLL_INTERVAL", "10"))
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "./ifm_audit.db")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")

_JSON_PATTERN = re.compile(
    r'\{[^{}]*"citation"[^{}]*"confidence"[^{}]*"requires_human_review"[^{}]*\}',
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Core helper functions
# ---------------------------------------------------------------------------

def extract_json_block(text: str) -> dict | None:
    """Extract the structured JSON block from a Claude response (Decision 6)."""
    match = _JSON_PATTERN.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def clamp_confidence(value: float) -> float:
    """Clamp confidence to [0.0, 1.0]. Log if out of range."""
    if value < 0.0 or value > 1.0:
        logger.warning("Model returned confidence %s outside [0,1] — clamping", value)
    return max(0.0, min(1.0, value))


def build_query(alert: Alert) -> str:
    """Construct semantic query string from alert fields (GmpQuery)."""
    parts = [alert.device_type, "CCP deviation remediation procedure"]
    if alert.sensor_values:
        try:
            vals = json.loads(alert.sensor_values)
            parts.extend(f"{k}={v}" for k, v in vals.items())
        except (json.JSONDecodeError, AttributeError):
            pass
    if alert.anomaly_score is not None:
        parts.append(f"anomaly_score={alert.anomaly_score:.3f}")
    return " ".join(parts)


def format_sop_context(chunks: list[dict]) -> str:
    """Format retrieved SOP chunks as a system prompt context block."""
    if not chunks:
        return "No relevant SOP documents found for this device type."
    lines = ["RETRIEVED SOP CONTEXT (top semantic matches):"]
    for i, chunk in enumerate(chunks, 1):
        lines.append(f"\n[Result {i} — Source: {chunk['source']}]")
        lines.append(chunk["text"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Alert processing
# ---------------------------------------------------------------------------

def process_alert(
    alert: Alert,
    collection,
    client: anthropic.Anthropic,
    session,
) -> None:
    """Run the full RAG → Claude → AgentRun pipeline for one alert."""
    query = build_query(alert)
    chunks = query_collection(collection, query, n_results=3)

    citation = ""
    confidence_score = 0.0
    requires_human_review = False

    if not chunks:
        logger.warning(
            "CITATION_VIOLATION alert_id=%s — no SOP chunks retrieved for %s",
            alert.id, alert.device_type,
        )
        requires_human_review = True
        sop_context = format_sop_context([])
    else:
        sop_context = format_sop_context(chunks)
        logger.info(
            "  RAG: %d chunks retrieved (%s)",
            len(chunks),
            ", ".join(c["source"] for c in chunks),
        )

    alert_user_message = (
        f"ANOMALY ALERT\n"
        f"Device ID: {alert.device_id}\n"
        f"Device Type: {alert.device_type}\n"
        f"Batch ID: {alert.batch_id}\n"
        f"Anomaly Score: {alert.anomaly_score}\n"
        f"Sensor Values: {alert.sensor_values}\n"
        f"Detected At: {alert.detected_at.isoformat()}\n\n"
        f"Please provide GMP remediation guidance with full SOP citations."
    )

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": GMP_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": sop_context,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[{"role": "user", "content": alert_user_message}],
    )

    raw_response = response.content[0].text if response.content else ""

    json_block = extract_json_block(raw_response)
    if json_block is None:
        logger.warning(
            "CITATION_VIOLATION alert_id=%s — JSON block missing from Claude response",
            alert.id,
        )
        requires_human_review = True
    else:
        citation = json_block.get("citation", "")
        confidence_score = clamp_confidence(float(json_block.get("confidence", 0.0)))
        requires_human_review = bool(json_block.get("requires_human_review", False))
        logger.info(
            "  Claude: confidence=%.2f citation=%s",
            confidence_score, citation or "(none)",
        )

    if not citation:
        requires_human_review = True

    if confidence_score < AGENT_HUMAN_REVIEW_THRESHOLD:
        requires_human_review = True

    run = create_agent_run(
        session,
        alert_id=alert.id,
        recommendation=raw_response,
        citation=citation,
        confidence_score=confidence_score,
        requires_human_review=requires_human_review,
        model_name=MODEL_NAME,
        raw_response=raw_response,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    logger.info("  AgentRun saved: id=%s", run.id)


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

_stop = False


def _handle_signal(signum, frame):
    global _stop
    logger.info("[AGENT] Shutdown signal received — stopping after current poll.")
    _stop = True


def polling_loop(session, collection, client: anthropic.Anthropic, interval: int) -> None:
    """Poll for unprocessed alerts and process each one serially."""
    while not _stop:
        unprocessed = get_unprocessed_alerts(session)
        if not unprocessed:
            logger.debug("No new alerts.")
        for alert in unprocessed:
            if _stop:
                break
            logger.info(
                "[%s] Processing alert_id=%s device=%s batch=%s",
                datetime.now().strftime("%H:%M:%S"),
                alert.id, alert.device_id, alert.batch_id,
            )
            try:
                process_alert(alert, collection, client, session)
            except anthropic.APIError as exc:
                logger.error(
                    "Claude API error for alert_id=%s: %s — alert will retry next cycle",
                    alert.id, exc,
                )
            except Exception as exc:
                logger.error(
                    "Unexpected error processing alert_id=%s: %s — skipping",
                    alert.id, exc,
                )
        if not _stop:
            time.sleep(interval)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="IFM AI Agent — GMP Remediation")
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=AGENT_POLL_INTERVAL,
        help="Seconds between Alert table polls (default: 10)",
    )
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("[AGENT] ANTHROPIC_API_KEY not set — exiting")
        sys.exit(1)

    chroma_dir = CHROMA_PERSIST_DIR
    try:
        chroma_client = get_chroma_client(chroma_dir)
        collection = get_collection(chroma_client)
        count = collection.count()
        logger.info("[AGENT] ChromaDB collection gmp_docs — %d chunks loaded", count)
    except Exception as exc:
        logger.error("[AGENT] ChromaDB collection not found: %s — run ingest first", exc)
        sys.exit(1)

    engine = create_engine(
        f"sqlite:///{SQLITE_DB_PATH}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine)
    session = Session()

    client = anthropic.Anthropic(api_key=api_key)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("[AGENT] Polling alerts every %ss ...", args.poll_interval)
    try:
        polling_loop(session, collection, client, args.poll_interval)
    finally:
        session.close()
        logger.info("[AGENT] Session closed. Exiting.")


if __name__ == "__main__":
    main()
