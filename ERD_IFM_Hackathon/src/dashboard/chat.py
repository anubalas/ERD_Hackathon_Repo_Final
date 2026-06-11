"""IFM GMP Chat Assistant page (LangChain + OpenAI version)."""

import json
import logging
import os
import sys
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.crud import acknowledge_alert
from src.db.models import Base
from src.agent.tools import execute_tool

logger = logging.getLogger(__name__)

SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "telemetry.db")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")

MODEL_NAME = "gpt-4o-mini"


@st.cache_resource
def _get_engine():
    eng = create_engine(
        f"sqlite:///{SQLITE_DB_PATH}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


_engine = _get_engine()
_SessionLocal = sessionmaker(bind=_engine)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = """You are an AI GMP compliance assistant for an infant food manufacturing (IFM) facility.

You help operators understand alerts, find SOP procedures, and analyse batch safety data.
Infant food safety is the highest priority — be precise, cite sources, and never speculate.

You have access to three tools:
- query_alerts_db
- search_gmp_docs
- generate_report

Guidelines:
1. Alerts/history → query_alerts_db
2. SOP/procedures → search_gmp_docs
3. Trends/charts → generate_report
4. Always cite SOP sections
5. Flag when QA review is required
6. Keep answers concise and actionable
"""

# ---------------------------------------------------------------------------
# ChromaDB
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
# LangChain Agent
# ---------------------------------------------------------------------------

def _run_agent(history: list) -> tuple[str, object]:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return "⚠️ OPENAI_API_KEY not configured.", None

    client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL", "https://openai.generative.engine.capgemini.com/v1"))

    collection = _get_collection()
    pending_chart = None

    # ---- Define tools (OpenAI format) ----
    tools = [
        {
            "type": "function",
            "function": {
                "name": "query_alerts_db",
                "description": "Search alerts database",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_gmp_docs",
                "description": "Search SOP/GMP documents",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_report",
                "description": "Generate charts",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    },
                    "required": ["query"],
                },
            },
        },
    ]

    # ---- Convert history ----
    system_content = CHAT_SYSTEM_PROMPT
    ctx = st.session_state.get("alert_context")
    if ctx:
        system_content += (
            f"\n\nACTIVE ALERT CONTEXT:\n"
            f"- Device: {ctx.get('device_id')} ({ctx.get('device_type')})\n"
            f"- Alert type: {ctx.get('alert_type')}\n"
            f"- Batch: {ctx.get('batch_id')}\n"
            f"- Sensor values: {ctx.get('sensor_values')}\n"
            f"- Detail: {ctx.get('error_detail')}\n"
            f"When the user refers to 'the alert' or 'the above alert', they mean this alert."
        )
    messages = [{"role": "system", "content": system_content}]
    for msg in history:
        if msg["role"] in ["user", "assistant"]:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

    max_loops = 5

    for _ in range(max_loops):
        try:
            response = client.chat.completions.create(
                model="openai.gpt-5.2",
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
        except Exception as e:
            return f"❌ Agent error: {e}", None

        msg = response.choices[0].message

        # ---- If model wants to call tools ----
        if msg.tool_calls:
            messages.append(msg)

            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                with _SessionLocal() as session:
                    result, chart = execute_tool(
                        name, args, session, collection
                    )

                if chart is not None:
                    pending_chart = chart

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                })

        else:
            # Final response
            return msg.content, pending_chart

    return "Agent reached max steps.", pending_chart
    
# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------

def _process_message(user_text: str) -> None:
    if not user_text.strip():
        return

    st.session_state.chat_history.append({"role": "user", "content": user_text})

    with st.spinner("AI is thinking..."):
        response_text, chart = _run_agent(st.session_state.chat_history)

    st.session_state.chat_history.append({
        "role": "assistant",
        "content": response_text,
        "chart": chart,
    })

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def render_chat_page() -> None:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "alert_context" not in st.session_state:
        st.session_state.alert_context = None
    if "pending_auto_message" not in st.session_state:
        st.session_state.pending_auto_message = None

    # Sidebar
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

        if os.getenv("OPENAI_API_KEY"):
            st.success("API key ✓", icon="🔑")
        else:
            st.error("API key missing", icon="⚠️")

    # Header
    st.title("🤖 IFM GMP Assistant")
    st.caption("Powered by OpenAI + LangChain")

    # Alert banner
    ctx = st.session_state.alert_context
    if ctx:
        col_info, col_ack = st.columns([5, 1])

        with col_info:
            st.warning(
                f"**Active Alert** — {ctx.get('device_id')} "
                f"({ctx.get('alert_type')}) · Batch: {ctx.get('batch_id')}",
                icon="🔴",
            )

        with col_ack:
            if st.button("✅ Acknowledge"):
                alert_id = ctx.get("alert_id")
                if alert_id:
                    try:
                        with _SessionLocal() as session:
                            acknowledge_alert(session, alert_id)
                        st.success("Alert acknowledged!")
                    except Exception as e:
                        st.error(str(e))

                st.session_state.alert_context = None
                st.rerun()

        st.markdown("---")

    # Welcome
    if not st.session_state.chat_history:
        with st.chat_message("assistant"):
            st.markdown(
                "Hello! I'm your **GMP Compliance Assistant**.\n\n"
                "- 🚨 Alert analysis\n"
                "- 📋 SOP procedures\n"
                "- 📊 Reports\n"
                "- 🔍 Batch safety"
            )

    # Chat history
    for i, msg in enumerate(st.session_state.chat_history):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("chart") is not None:
                st.plotly_chart(msg["chart"], use_container_width=True)

    # Auto-fire pending alert message injected by the dashboard
    if st.session_state.pending_auto_message and not st.session_state.chat_history:
        auto_msg = st.session_state.pending_auto_message
        st.session_state.pending_auto_message = None
        _process_message(auto_msg)
        st.rerun()

    # Input
    user_input = st.chat_input("Type your message...")
    if user_input:
        _process_message(user_input)
        st.rerun()