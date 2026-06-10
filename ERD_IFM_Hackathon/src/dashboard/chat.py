"""IFM GMP Chat Assistant page.

Rendered by app.py when st.session_state.page == "chat".
Supports alert-context auto-messages and free-form operator queries.
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.crud import acknowledge_alert
from src.agent.tools import CLAUDE_TOOLS, execute_tool

logger = logging.getLogger(__name__)

SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "telemetry.db")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
MODEL_NAME = "claude-sonnet-4-6"

_engine = create_engine(
    f"sqlite:///{SQLITE_DB_PATH}",
    connect_args={"check_same_thread": False},
)
_SessionLocal = sessionmaker(bind=_engine)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = """You are an AI GMP compliance assistant for an infant food manufacturing (IFM) facility.

You help operators understand alerts, find SOP procedures, and analyse batch safety data.
Infant food safety is the highest priority — be precise, cite sources, and never speculate.

You have access to three tools:
- query_alerts_db   : search the live alerts database (anomaly, CCP breach, trend data)
- search_gmp_docs   : search SOP/GMP documents for procedures and regulatory guidance
- generate_report   : produce a visual chart (bar, pie, or line) of alert trends

Guidelines:
1. When asked about specific alerts or history → use query_alerts_db first.
2. When asked about procedures, what to do, or SOP → use search_gmp_docs.
3. When asked for a summary, visual, or trend → use generate_report.
4. Always cite SOP source and section when giving remediation advice.
5. Flag when human QA review is required.
6. Keep answers concise and action-oriented.
"""

# ---------------------------------------------------------------------------
# ChromaDB collection (cached per session)
# ---------------------------------------------------------------------------

def _get_collection():
    if "chroma_collection" not in st.session_state:
        try:
            from src.rag.chroma_store import get_chroma_client, get_collection
            client = get_chroma_client(CHROMA_PERSIST_DIR)
            st.session_state.chroma_collection = get_collection(client)
        except Exception:
            st.session_state.chroma_collection = None
    return st.session_state.chroma_collection

# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------

def _run_agent(history: list) -> tuple[str, object]:
    """Call Claude with tool use. Returns (response_text, chart_or_None)."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return (
            "⚠️ **ANTHROPIC_API_KEY not configured.**\n\n"
            "Please set it in your `.env` file or run:\n"
            "```\n$env:ANTHROPIC_API_KEY='sk-ant-...'\n```",
            None,
        )

    try:
        import anthropic
    except ImportError:
        return "⚠️ `anthropic` package not installed — run `pip install anthropic`.", None

    # Build message list from history (skip chart metadata)
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m["role"] in ("user", "assistant")
    ]

    client = anthropic.Anthropic(api_key=api_key)
    collection = _get_collection()
    pending_chart = None
    max_loops = 5

    for _ in range(max_loops):
        try:
            response = client.messages.create(
                model=MODEL_NAME,
                max_tokens=2048,
                system=CHAT_SYSTEM_PROMPT,
                tools=CLAUDE_TOOLS,
                messages=messages,
            )
        except Exception as exc:
            return f"❌ Agent error: {exc}", None

        if response.stop_reason == "end_turn":
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            return text, pending_chart

        if response.stop_reason == "tool_use":
            # Add assistant message with tool calls
            messages.append({"role": "assistant", "content": response.content})

            # Execute each tool and collect results
            tool_results = []
            with _SessionLocal() as session:
                for block in response.content:
                    if getattr(block, "type", None) == "tool_use":
                        result_text, chart = execute_tool(
                            block.name, block.input, session, collection
                        )
                        if chart is not None:
                            pending_chart = chart
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result_text),
                        })

            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return "Agent reached maximum reasoning steps.", pending_chart

# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------

def _process_message(user_text: str) -> None:
    """Add user message, call agent, add response — all in one call."""
    if not user_text.strip():
        return

    st.session_state.chat_history.append({"role": "user", "content": user_text})

    with st.spinner("Claude is thinking..."):
        response_text, chart = _run_agent(st.session_state.chat_history)

    st.session_state.chat_history.append({
        "role": "assistant",
        "content": response_text,
        "chart": chart,
    })

# ---------------------------------------------------------------------------
# Main render function (called from app.py)
# ---------------------------------------------------------------------------

def render_chat_page() -> None:
    # ── Session state defaults ──────────────────────────────────────────────
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "alert_context" not in st.session_state:
        st.session_state.alert_context = None
    if "pending_auto_message" not in st.session_state:
        st.session_state.pending_auto_message = None

    # ── Sidebar ─────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### Navigation")
        if st.button("📊 Dashboard", use_container_width=True):
            st.session_state.page = "dashboard"
            st.rerun()

        st.markdown("---")
        if st.button("🔄 New Chat", use_container_width=True):
            st.session_state.chat_history = []
            st.session_state.alert_context = None
            st.session_state.pending_auto_message = None
            st.rerun()

        st.markdown("---")
        st.caption("IFM GMP Assistant")
        st.caption(f"Model: {MODEL_NAME}")
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if api_key:
            st.success("API key ✓", icon="🔑")
        else:
            st.error("API key missing", icon="⚠️")

    # ── Page header ─────────────────────────────────────────────────────────
    st.title("🤖 IFM GMP Assistant")
    st.caption("Powered by Claude · Ask about alerts, SOPs, or batch safety")

    # ── Alert context banner ─────────────────────────────────────────────────
    ctx = st.session_state.alert_context
    if ctx:
        col_info, col_ack = st.columns([5, 1])
        with col_info:
            st.warning(
                f"**Active Alert** — {ctx.get('device_id', '?')} "
                f"({ctx.get('alert_type', '?')}) · Batch: {ctx.get('batch_id', '?')}",
                icon="🔴",
            )
        with col_ack:
            if st.button("✅ Acknowledge", key="ack_chat"):
                alert_id = ctx.get("alert_id")
                if alert_id:
                    try:
                        with _SessionLocal() as session:
                            acknowledge_alert(session, alert_id)
                        st.success("Alert acknowledged!")
                    except Exception as exc:
                        st.error(f"Could not acknowledge: {exc}")
                st.session_state.alert_context = None
                st.rerun()
        st.markdown("---")

    # ── Auto-send pending alert message ─────────────────────────────────────
    if st.session_state.pending_auto_message and not st.session_state.chat_history:
        auto_msg = st.session_state.pending_auto_message
        st.session_state.pending_auto_message = None
        _process_message(auto_msg)

    # ── Welcome message if empty ─────────────────────────────────────────────
    if not st.session_state.chat_history:
        with st.chat_message("assistant", avatar="🤖"):
            st.markdown(
                "Hello! I'm your **GMP Compliance Assistant**.\n\n"
                "I can help you with:\n"
                "- 🚨 **Alert analysis** — *'What alerts happened in the last 24 hours?'*\n"
                "- 📋 **SOP procedures** — *'What's the boiler shutdown procedure?'*\n"
                "- 📊 **Visual reports** — *'Show me a chart of alerts by device'*\n"
                "- 🔍 **Batch safety** — *'Is BATCH-001 safe to continue?'*"
            )

    # ── Chat history ─────────────────────────────────────────────────────────
    for i, msg in enumerate(st.session_state.chat_history):
        avatar = "🤖" if msg["role"] == "assistant" else "👤"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            if msg.get("chart") is not None:
                st.plotly_chart(
                    msg["chart"],
                    use_container_width=True,
                    key=f"chart_{i}",
                )

    # ── Chat input ────────────────────────────────────────────────────────────
    user_input = st.chat_input("Type your message...")
    if user_input:
        _process_message(user_input)
        st.rerun()
