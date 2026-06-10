"""AI agent — LangGraph pipeline: RAG → Claude → AgentRun.

Graph:
  rag_retrieve → call_llm → parse_response ──(high conf)──→ save_result → END
                                     └────(low conf)──→ flag_review ──┘

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
from typing import TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
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

MODEL_NAME = "openai.gpt-5.2"
AGENT_HUMAN_REVIEW_THRESHOLD = float(os.getenv("AGENT_HUMAN_REVIEW_THRESHOLD", "0.7"))
AGENT_POLL_INTERVAL = int(os.getenv("AGENT_POLL_INTERVAL", "10"))
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "./ifm_audit.db")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")

_JSON_PATTERN = re.compile(
    r'\{[^{}]*"citation"[^{}]*"confidence"[^{}]*"requires_human_review"[^{}]*\}',
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Helper functions — kept intact (imported by dashboard)
# ---------------------------------------------------------------------------

def extract_json_block(text: str) -> dict | None:
    match = _JSON_PATTERN.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def clamp_confidence(value: float) -> float:
    if value < 0.0 or value > 1.0:
        logger.warning("Model returned confidence %s outside [0,1] — clamping", value)
    return max(0.0, min(1.0, value))


def build_query(alert: Alert) -> str:
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
    if not chunks:
        return "No relevant SOP documents found for this device type."
    lines = ["RETRIEVED SOP CONTEXT (top semantic matches):"]
    for i, chunk in enumerate(chunks, 1):
        lines.append(f"\n[Result {i} — Source: {chunk['source']}]")
        lines.append(chunk["text"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LangGraph state schema
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    # From alert
    alert_id: int
    device_id: str
    device_type: str
    batch_id: str
    alert_type: str
    anomaly_score: float | None
    sensor_values: str | None
    error_detail: str | None
    detected_at: str
    # Pipeline outputs (populated by nodes)
    sop_context: str
    raw_response: str
    citation: str
    confidence: float
    requires_human_review: bool


# ---------------------------------------------------------------------------
# Node factory — closes over shared resources
# ---------------------------------------------------------------------------

def _make_nodes(collection, llm: ChatOpenAI, session):

    def rag_retrieve(state: AgentState) -> dict:
        """Node 1: Query ChromaDB for relevant SOP chunks."""
        query_parts = [state["device_type"], "CCP deviation remediation procedure"]
        if state.get("sensor_values"):
            try:
                vals = json.loads(state["sensor_values"])
                query_parts.extend(f"{k}={v}" for k, v in vals.items() if v is not None)
            except Exception:
                pass
        if state.get("anomaly_score") is not None:
            query_parts.append(f"anomaly_score={state['anomaly_score']:.3f}")

        chunks = query_collection(collection, " ".join(query_parts), n_results=3)
        sop_context = format_sop_context(chunks)

        logger.info(
            "  [rag_retrieve] alert_id=%s — %d chunks (%s)",
            state["alert_id"],
            len(chunks),
            ", ".join(c["source"] for c in chunks) or "none",
        )
        return {"sop_context": sop_context}

    def call_llm(state: AgentState) -> dict:
        """Node 2: Call Claude with system prompt + SOP context + alert details."""
        user_msg = (
            f"ALERT TYPE: {state['alert_type']}\n"
            f"Device ID: {state['device_id']}\n"
            f"Device Type: {state['device_type']}\n"
            f"Batch ID: {state['batch_id']}\n"
            f"Anomaly Score: {state.get('anomaly_score')}\n"
            f"Sensor Values: {state.get('sensor_values')}\n"
            f"Details: {state.get('error_detail') or ''}\n"
            f"Detected At: {state['detected_at']}\n\n"
            f"Please provide GMP remediation guidance with full SOP citations."
        )

        messages = [
            SystemMessage(content=[
                {
                    "type": "text",
                    "text": GMP_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": state["sop_context"],
                    "cache_control": {"type": "ephemeral"},
                },
            ]),
            HumanMessage(content=user_msg),
        ]

        response = llm.invoke(messages)

        # Handle both str and list content from ChatOpenAI
        if isinstance(response.content, str):
            raw = response.content
        else:
            raw = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in response.content
            )

        logger.info(
            "  [call_llm] alert_id=%s — response %d chars",
            state["alert_id"], len(raw),
        )
        return {"raw_response": raw}

    def parse_response(state: AgentState) -> dict:
        """Node 3: Extract citation, confidence, and review flag from Claude output."""
        json_block = extract_json_block(state["raw_response"])
        if json_block:
            citation = json_block.get("citation", "")
            confidence = clamp_confidence(float(json_block.get("confidence", 0.0)))
            requires_review = bool(json_block.get("requires_human_review", False))
        else:
            logger.warning(
                "  [parse_response] alert_id=%s — JSON block missing",
                state["alert_id"],
            )
            citation = ""
            confidence = 0.0
            requires_review = True

        logger.info(
            "  [parse_response] alert_id=%s — confidence=%.2f citation=%s",
            state["alert_id"], confidence, citation or "(none)",
        )
        return {
            "citation": citation,
            "confidence": confidence,
            "requires_human_review": requires_review,
        }

    def flag_review(state: AgentState) -> dict:
        """Node 4a: Force human review when confidence is low or citation missing."""
        logger.warning(
            "  [flag_review] alert_id=%s — confidence=%.2f below threshold or no citation",
            state["alert_id"], state.get("confidence", 0.0),
        )
        return {"requires_human_review": True}

    def save_result(state: AgentState) -> dict:
        """Node 5: Persist AgentRun to SQLite."""
        run = create_agent_run(
            session,
            alert_id=state["alert_id"],
            recommendation=state["raw_response"],
            citation=state["citation"],
            confidence_score=state["confidence"],
            requires_human_review=state["requires_human_review"],
            model_name=MODEL_NAME,
            raw_response=state["raw_response"],
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        logger.info(
            "  [save_result] alert_id=%s — AgentRun id=%s saved",
            state["alert_id"], run.id,
        )
        return {}

    return rag_retrieve, call_llm, parse_response, flag_review, save_result


def _route_confidence(state: AgentState) -> str:
    """Conditional edge: route to flag_review or directly to save_result."""
    if not state.get("citation") or state.get("confidence", 0.0) < AGENT_HUMAN_REVIEW_THRESHOLD:
        return "flag_review"
    return "save_result"


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_graph(collection, llm: ChatOpenAI, session):
    """Compile the LangGraph agent graph.

    rag_retrieve → call_llm → parse_response ──(high conf)──→ save_result → END
                                       └────(low conf)──→ flag_review ──┘
    """
    rag_retrieve, call_llm, parse_response, flag_review, save_result = _make_nodes(
        collection, llm, session
    )

    g = StateGraph(AgentState)
    g.add_node("rag_retrieve",   rag_retrieve)
    g.add_node("call_llm",       call_llm)
    g.add_node("parse_response", parse_response)
    g.add_node("flag_review",    flag_review)
    g.add_node("save_result",    save_result)

    g.set_entry_point("rag_retrieve")
    g.add_edge("rag_retrieve",   "call_llm")
    g.add_edge("call_llm",       "parse_response")
    g.add_conditional_edges(
        "parse_response",
        _route_confidence,
        {"flag_review": "flag_review", "save_result": "save_result"},
    )
    g.add_edge("flag_review", "save_result")
    g.add_edge("save_result", END)

    return g.compile()


# ---------------------------------------------------------------------------
# Alert processing — uses compiled graph
# ---------------------------------------------------------------------------

def process_alert(alert: Alert, graph) -> None:
    """Invoke the LangGraph pipeline for a single alert."""
    initial_state: AgentState = {
        "alert_id":    alert.id,
        "device_id":   alert.device_id,
        "device_type": alert.device_type,
        "batch_id":    alert.batch_id,
        "alert_type":  alert.alert_type,
        "anomaly_score":  alert.anomaly_score,
        "sensor_values":  alert.sensor_values,
        "error_detail":   alert.error_detail,
        "detected_at":    alert.detected_at.isoformat() if alert.detected_at else "",
        # Pipeline outputs — empty until nodes populate them
        "sop_context":          "",
        "raw_response":         "",
        "citation":             "",
        "confidence":           0.0,
        "requires_human_review": False,
    }
    graph.invoke(initial_state)


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

_stop = False


def _handle_signal(signum, frame):
    global _stop
    logger.info("[AGENT] Shutdown signal — stopping after current poll.")
    _stop = True


def polling_loop(session, graph, interval: int) -> None:
    while not _stop:
        unprocessed = get_unprocessed_alerts(session)
        if not unprocessed:
            logger.debug("No new alerts.")
        for alert in unprocessed:
            if _stop:
                break
            logger.info(
                "[%s] Processing alert_id=%s device=%s batch=%s type=%s",
                datetime.now().strftime("%H:%M:%S"),
                alert.id, alert.device_id, alert.batch_id, alert.alert_type,
            )
            try:
                process_alert(alert, graph)
            except Exception as exc:
                logger.error(
                    "Error processing alert_id=%s: %s — will retry next cycle",
                    alert.id, exc,
                )
        if not _stop:
            time.sleep(interval)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="IFM AI Agent — LangGraph GMP Remediation")
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=AGENT_POLL_INTERVAL,
        help=f"Seconds between Alert polls (default: {AGENT_POLL_INTERVAL})",
    )
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("[AGENT] ANTHROPIC_API_KEY not set — exiting")
        sys.exit(1)

    try:
        chroma_client = get_chroma_client(CHROMA_PERSIST_DIR)
        collection = get_collection(chroma_client)
        logger.info("[AGENT] ChromaDB gmp_docs — %d chunks", collection.count())
    except Exception as exc:
        logger.error("[AGENT] ChromaDB not available: %s — run ingest first", exc)
        sys.exit(1)

    engine = create_engine(
        f"sqlite:///{SQLITE_DB_PATH}",
        connect_args={"check_same_thread": False},
    )
    session = sessionmaker(bind=engine)()

    llm = ChatOpenAI(
        model=MODEL_NAME,
        max_tokens=1024,
        base_url=os.getenv("OPENAI_BASE_URL", "https://openai.generative.engine.capgemini.com/v1"),
        api_key=os.getenv("OPENAI_API_KEY", ""),
    )
    graph = build_graph(collection, llm, session)

    logger.info(
        "[AGENT] LangGraph ready — "
        "rag_retrieve → call_llm → parse_response → (route) → save_result"
    )

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("[AGENT] Polling every %ss ...", args.poll_interval)
    try:
        polling_loop(session, graph, args.poll_interval)
    finally:
        session.close()
        logger.info("[AGENT] Session closed. Exiting.")


if __name__ == "__main__":
    main()
