import os
import sys

# Add project root to path so `src.*` imports work when launched via `streamlit run`
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import pandas as pd
import sqlalchemy.exc
import streamlit as st
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import Session, sessionmaker
from streamlit_autorefresh import st_autorefresh

from src.db.models import AgentRun, Alert, TelemetryLog

SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "telemetry.db")

engine = create_engine(
    f"sqlite:///{SQLITE_DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine)

st.set_page_config(page_title="IFM Operator Dashboard", layout="wide")
st_autorefresh(interval=5000, key="dashboard_refresh")
st.title("IFM Operator Dashboard")
st.caption("Auto-refreshes every 5 seconds")


# ---------------------------------------------------------------------------
# Query functions (independently testable)
# ---------------------------------------------------------------------------

def get_live_feed(session: Session) -> pd.DataFrame:
    rows = (
        session.query(TelemetryLog)
        .order_by(TelemetryLog.server_received_at.desc())
        .limit(50)
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=[
            "server_received_at", "device_id", "device_type", "batch_id",
            "temperature", "pressure", "humidity", "ph", "flow_rate",
            "status", "stream_published",
        ])
    return pd.DataFrame([{
        "server_received_at": r.server_received_at,
        "device_id": r.device_id,
        "device_type": r.device_type,
        "batch_id": r.batch_id,
        "temperature": r.temperature,
        "pressure": r.pressure,
        "humidity": r.humidity,
        "ph": r.ph,
        "flow_rate": r.flow_rate,
        "status": r.status,
        "stream_published": r.stream_published,
    } for r in rows])


def get_alerts(session: Session) -> tuple[pd.DataFrame, int]:
    total = session.query(func.count(TelemetryLog.id)).filter(
        TelemetryLog.status == "REJECTED"
    ).scalar() or 0

    rows = (
        session.query(TelemetryLog)
        .filter(TelemetryLog.status == "REJECTED")
        .order_by(TelemetryLog.server_received_at.desc())
        .limit(20)
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=[
            "server_received_at", "device_id", "device_type",
            "rejection_reason", "batch_id", "reading_id",
        ]), total
    return pd.DataFrame([{
        "server_received_at": r.server_received_at,
        "device_id": r.device_id,
        "device_type": r.device_type,
        "rejection_reason": (r.rejection_reason or "")[:120],
        "batch_id": r.batch_id,
        "reading_id": r.reading_id,
    } for r in rows]), total


def get_batch_audit(session: Session, batch_id: str) -> pd.DataFrame:
    rows = (
        session.query(TelemetryLog)
        .filter(TelemetryLog.batch_id == batch_id)
        .order_by(TelemetryLog.device_timestamp.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=[
            "device_timestamp", "device_id", "device_type",
            "temperature", "pressure", "humidity", "ph", "flow_rate",
            "status", "rejection_reason", "stream_published",
        ])
    return pd.DataFrame([{
        "device_timestamp": r.device_timestamp,
        "device_id": r.device_id,
        "device_type": r.device_type,
        "temperature": r.temperature,
        "pressure": r.pressure,
        "humidity": r.humidity,
        "ph": r.ph,
        "flow_rate": r.flow_rate,
        "status": r.status,
        "rejection_reason": r.rejection_reason,
        "stream_published": r.stream_published,
    } for r in rows])


# ---------------------------------------------------------------------------
# Colour helper (shared across all tabs)
# ---------------------------------------------------------------------------

def _colour_row(row: pd.Series) -> list[str]:
    if row.get("status") == "REJECTED":
        return ["background-color: #ffcccc"] * len(row)
    if row.get("status") == "ACCEPTED" and not row.get("stream_published", True):
        return ["background-color: #ffe5b4"] * len(row)
    return ["background-color: #ccffcc"] * len(row)


# ---------------------------------------------------------------------------
# Tab layout
# ---------------------------------------------------------------------------

def get_ai_recommendations(session: Session) -> pd.DataFrame:
    try:
        rows = (
            session.query(
                AgentRun.id,
                AgentRun.alert_id,
                AgentRun.citation,
                AgentRun.confidence_score,
                AgentRun.requires_human_review,
                AgentRun.model_name,
                AgentRun.created_at,
                AgentRun.recommendation,
                Alert.device_id,
                Alert.device_type,
                Alert.anomaly_score,
                Alert.batch_id,
            )
            .join(Alert, AgentRun.alert_id == Alert.id)
            .order_by(AgentRun.created_at.desc())
            .limit(20)
            .all()
        )
    except Exception:
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame([{
        "created_at": r.created_at,
        "device_id": r.device_id,
        "device_type": r.device_type,
        "batch_id": r.batch_id,
        "anomaly_score": r.anomaly_score,
        "citation": r.citation,
        "confidence_score": r.confidence_score,
        "requires_human_review": bool(r.requires_human_review),
        "recommendation": (r.recommendation or "")[:200],
        "model_name": r.model_name,
    } for r in rows])


def _ai_row_colour(row: pd.Series) -> list[str]:
    conf = row.get("confidence_score", 0.0)
    review = row.get("requires_human_review", False)
    citation = row.get("citation", "")
    if conf < 0.4 or not citation:
        colour = "#ffcccc"
    elif conf < 0.7 or review:
        colour = "#ffe5b4"
    else:
        colour = "#ccffcc"
    return [f"background-color: {colour}"] * len(row)


tab1, tab2, tab3, tab4 = st.tabs(["Live Feed", "CCP Alerts", "Batch Audit", "🤖 AI Recommendations"])

# --- Tab 1: Live Feed ---
with tab1:
    try:
        with SessionLocal() as session:
            df = get_live_feed(session)
    except sqlalchemy.exc.OperationalError as exc:
        st.error(f"Could not connect to database. Is the API running? ({exc})")
        st.stop()

    total = len(df)
    accepted = int((df["status"] == "ACCEPTED").sum()) if total else 0
    rejected = int((df["status"] == "REJECTED").sum()) if total else 0
    stream_fail = int(
        ((df["status"] == "ACCEPTED") & (~df["stream_published"])).sum()
    ) if total else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Readings", total)
    c2.metric("ACCEPTED", accepted)
    c3.metric("REJECTED", rejected)
    c4.metric("Stream Failures", stream_fail)

    if df.empty:
        st.info("No readings yet — waiting for sensor data.")
    else:
        st.dataframe(df.style.apply(_colour_row, axis=1), use_container_width=True)

# --- Tab 2: CCP Alerts ---
with tab2:
    try:
        with SessionLocal() as session:
            alerts_df, total_violations = get_alerts(session)
    except sqlalchemy.exc.OperationalError as exc:
        st.error(f"Could not connect to database. ({exc})")
        st.stop()

    st.metric("Total CCP Violations", total_violations)

    if alerts_df.empty:
        st.success("No CCP violations detected — all readings within safe range.")
    else:
        red_style = alerts_df.style.apply(
            lambda row: ["background-color: #ffcccc"] * len(row), axis=1
        )
        st.dataframe(red_style, use_container_width=True)

# --- Tab 3: Batch Audit ---
with tab3:
    if "batch_search" not in st.session_state:
        st.session_state["batch_search"] = ""

    st.text_input("Search batch ID", key="batch_search")
    search_clicked = st.button("Search")

    batch_id = st.session_state.get("batch_search", "").strip()

    if batch_id:
        try:
            with SessionLocal() as session:
                audit_df = get_batch_audit(session, batch_id)
        except sqlalchemy.exc.OperationalError as exc:
            st.error(f"Could not connect to database. ({exc})")
            st.stop()

        if audit_df.empty:
            st.warning(f"No records found for batch '{batch_id}'.")
        else:
            st.dataframe(
                audit_df.style.apply(_colour_row, axis=1),
                use_container_width=True,
            )
    else:
        st.info("Enter a batch ID above to view its full audit trail.")

# --- Tab 4: AI Recommendations ---
with tab4:
    try:
        with SessionLocal() as session:
            ai_df = get_ai_recommendations(session)
    except sqlalchemy.exc.OperationalError as exc:
        st.error(f"Could not connect to database. ({exc})")
        st.stop()

    if ai_df.empty:
        st.info("No AI recommendations yet — waiting for the agent to process alerts.")
    else:
        for _, row in ai_df.iterrows():
            conf = row["confidence_score"]
            review = row["requires_human_review"]
            citation = row["citation"]

            if conf < 0.4 or not citation:
                border_colour = "#cc0000"
                bg_colour = "#ffcccc"
            elif conf < 0.7 or review:
                border_colour = "#cc7700"
                bg_colour = "#fff3cc"
            else:
                border_colour = "#007700"
                bg_colour = "#ccffcc"

            review_badge = (
                '<span style="background:#cc7700;color:white;padding:2px 8px;'
                'border-radius:4px;font-size:0.8em;margin-left:8px;">⚠️ REQUIRES HUMAN REVIEW</span>'
                if review else ""
            )

            st.markdown(
                f'<div style="background:{bg_colour};border-left:4px solid {border_colour};'
                f'padding:10px 14px;margin-bottom:8px;border-radius:4px;">'
                f'<strong>{row["device_id"]}</strong> ({row["device_type"]}) &nbsp;|&nbsp; '
                f'Batch: <code>{row["batch_id"]}</code> &nbsp;|&nbsp; '
                f'Anomaly score: <code>{row["anomaly_score"]:.3f}</code>'
                f'{review_badge}<br>'
                f'<small>Citation: <em>{citation or "NO CITATION"}</em> &nbsp;|&nbsp; '
                f'Confidence: <strong>{conf:.2f}</strong> &nbsp;|&nbsp; '
                f'Model: {row["model_name"]} &nbsp;|&nbsp; {row["created_at"]}</small><br>'
                f'<small>{row["recommendation"]}</small>'
                f'</div>',
                unsafe_allow_html=True,
            )
