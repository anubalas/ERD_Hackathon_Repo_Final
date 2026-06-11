import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dotenv import load_dotenv
load_dotenv()  # must load before any os.getenv calls

import pandas as pd
import sqlalchemy.exc
import streamlit as st
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import Session, sessionmaker
from streamlit_autorefresh import st_autorefresh

from src.db.models import Alert, Base, TelemetryLog
from src.db.crud import (
    create_alert_sync,
    dismiss_alert,
    get_pending_alerts,
)

# ---------------------------------------------------------------------------
# Config & DB
# ---------------------------------------------------------------------------

SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "telemetry.db")


@st.cache_resource
def _get_engine():
    eng = create_engine(
        f"sqlite:///{SQLITE_DB_PATH}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


engine = _get_engine()
SessionLocal = sessionmaker(bind=engine)


def _ensure_schema() -> None:
    try:
        with engine.connect() as conn:
            for col, definition in [
                ("severity",        "VARCHAR(32)"),
                ("dismissed",       "BOOLEAN NOT NULL DEFAULT 0"),
                ("acknowledged",    "BOOLEAN NOT NULL DEFAULT 0"),
                ("acknowledged_at", "DATETIME"),
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE alerts ADD COLUMN {col} {definition}"))
                    conn.commit()
                except Exception:
                    pass
    except Exception:
        pass


_ensure_schema()

# ---------------------------------------------------------------------------
# Page routing — must happen before any st.* calls
# ---------------------------------------------------------------------------

st.set_page_config(page_title="IFM Operator Dashboard", layout="wide")

# Init session state
for _k, _v in [
    ("page", "dashboard"),
    ("popup_state", None),
    ("popup_alert_id", None),
    ("alert_context", None),
    ("pending_auto_message", None),
    ("chat_history", []),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

# Route to chat page
if st.session_state.page == "chat":
    from src.dashboard.chat import render_chat_page
    render_chat_page()
    st.stop()

# ---------------------------------------------------------------------------
# Dashboard page below
# ---------------------------------------------------------------------------

st_autorefresh(interval=5000, key="dashboard_refresh")

# Sidebar navigation
with st.sidebar:
    st.markdown("### Navigation")
    if st.button("💬 Chat with Agent", use_container_width=True):
        st.session_state.page = "chat"
        st.session_state.alert_context = None
        st.session_state.pending_auto_message = None
        st.rerun()
    st.markdown("---")
    st.caption("IFM Operator Dashboard")

st.title("IFM Operator Dashboard")
st.caption("Auto-refreshes every 5 seconds")

# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_live_feed(session: Session) -> tuple[pd.DataFrame, int, int, int]:
    """Returns (df of last 50 rows, total_count, total_accepted, total_rejected)."""
    total     = session.query(func.count(TelemetryLog.id)).scalar() or 0
    accepted  = session.query(func.count(TelemetryLog.id)).filter(TelemetryLog.status == "ACCEPTED").scalar() or 0
    rejected  = session.query(func.count(TelemetryLog.id)).filter(TelemetryLog.status == "REJECTED").scalar() or 0

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
        ]), total, accepted, rejected

    df = pd.DataFrame([{
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
    return df, total, accepted, rejected


def get_ccp_alerts(session: Session) -> tuple[pd.DataFrame, int]:
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


def get_ml_anomalies(session: Session) -> tuple[pd.DataFrame, int]:
    total = (
        session.query(func.count(Alert.id))
        .filter(Alert.alert_type.in_(["ANOMALY", "TREND_ANOMALY"]))
        .scalar() or 0
    )
    rows = (
        session.query(Alert)
        .filter(Alert.alert_type.in_(["ANOMALY", "TREND_ANOMALY"]))
        .order_by(Alert.detected_at.desc())
        .limit(50)
        .all()
    )
    if not rows:
        return pd.DataFrame(), total
    return pd.DataFrame([{
        "detected_at": r.detected_at,
        "device_id": r.device_id,
        "device_type": r.device_type,
        "alert_type": r.alert_type,
        "severity": r.severity or "—",
        "anomaly_score": f"{r.anomaly_score:.3f}" if r.anomaly_score else "—",
        "detail": (r.error_detail or "")[:80],
        "_alert_id": r.id,
    } for r in rows]), total

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _colour_row(row: pd.Series) -> list[str]:
    if row.get("status") == "REJECTED":
        return ["background-color: #ffcccc"] * len(row)
    if row.get("status") == "ACCEPTED" and not row.get("stream_published", True):
        return ["background-color: #ffe5b4"] * len(row)
    return ["background-color: #ccffcc"] * len(row)


def _ml_row_colour(row: pd.Series) -> list[str]:
    if row.get("alert_type") == "TREND_ANOMALY":
        return ["background-color: #fff3cd"] * len(row)
    return ["background-color: #ffe5b4"] * len(row)

# ---------------------------------------------------------------------------
# Navigate to chat with alert context
# ---------------------------------------------------------------------------

def _go_to_chat(alert: Alert) -> None:
    sensor_info = ""
    if alert.sensor_values:
        try:
            vals = json.loads(alert.sensor_values)
            parts = [f"{k}: {v}" for k, v in vals.items() if v is not None]
            sensor_info = ", ".join(parts)
        except Exception:
            pass
    detail = alert.error_detail or ""

    auto_msg = (
        f"Alert detected on {alert.device_id}: {alert.alert_type} "
        f"on batch {alert.batch_id}"
        + (f". Sensors: {sensor_info}" if sensor_info else "")
        + (f". {detail}" if detail else "")
        + ". What should I do?"
    )

    st.session_state.alert_context = {
        "alert_id":   alert.id,
        "device_id":  alert.device_id,
        "device_type": alert.device_type,
        "alert_type": alert.alert_type,
        "batch_id":   alert.batch_id,
        "sensor_values": alert.sensor_values,
        "error_detail":  alert.error_detail,
    }
    st.session_state.pending_auto_message = auto_msg
    st.session_state.chat_history = []
    st.session_state.popup_state = None
    st.session_state.popup_alert_id = None
    st.session_state.page = "chat"


def _go_to_chat_for_ccp(reading_id: str, device_id: str, device_type: str,
                         batch_id: str, rejection_reason: str) -> None:
    # Get or create CCP_BREACH alert
    with SessionLocal() as session:
        existing = (
            session.query(Alert)
            .filter(Alert.alert_type == "CCP_BREACH", Alert.reading_id == reading_id)
            .first()
        )
        if existing:
            alert = existing
        else:
            alert = create_alert_sync(
                session,
                device_id=device_id,
                device_type=device_type,
                batch_id=batch_id,
                alert_type="CCP_BREACH",
                severity="CRITICAL",
                detected_at=datetime.now(timezone.utc).replace(tzinfo=None),
                reading_id=reading_id,
                error_detail=(rejection_reason or "")[:512],
            )

    auto_msg = (
        f"CCP breach on {device_id} ({device_type}): {rejection_reason or 'CCP limit exceeded'} "
        f"on batch {batch_id}. What is the correct GMP procedure?"
    )
    st.session_state.alert_context = {
        "alert_id":   alert.id,
        "device_id":  device_id,
        "device_type": device_type,
        "alert_type": "CCP_BREACH",
        "batch_id":   batch_id,
    }
    st.session_state.pending_auto_message = auto_msg
    st.session_state.chat_history = []
    st.session_state.popup_state = None
    st.session_state.page = "chat"

# ---------------------------------------------------------------------------
# Popup rendering (Step 1 only — "Address Alert" now navigates to chat)
# ---------------------------------------------------------------------------

def _render_popup() -> None:
    alert_id = st.session_state.popup_alert_id
    if not alert_id:
        st.session_state.popup_state = None
        return

    try:
        with SessionLocal() as session:
            alert = session.query(Alert).filter(Alert.id == alert_id).first()
    except Exception:
        st.session_state.popup_state = None
        return

    if alert is None:
        st.session_state.popup_state = None
        return

    sensor_summary = ""
    if alert.sensor_values:
        try:
            vals = json.loads(alert.sensor_values)
            sensor_summary = " | ".join(
                f"{k}: {v}" for k, v in vals.items() if v is not None
            )
        except Exception:
            pass

    detected = alert.detected_at.strftime("%Y-%m-%d %H:%M") if alert.detected_at else "—"
    type_icon = {"ANOMALY": "🟠", "TREND_ANOMALY": "🟡", "CCP_BREACH": "🔴"}.get(
        alert.alert_type, "🔴"
    )

    st.markdown("---")
    st.markdown(
        f"""
        <div style="background:#fff3f3;border:2px solid #cc0000;border-radius:8px;
                    padding:16px 20px;margin-bottom:8px;">
          <h3 style="margin:0 0 8px;color:#cc0000;">{type_icon} NEW ALERT</h3>
          <table style="border-collapse:collapse;">
            <tr><td style="width:120px;color:#666;"><b>Device</b></td><td>{alert.device_id}</td></tr>
            <tr><td style="color:#666;"><b>Type</b></td><td>{alert.alert_type}</td></tr>
            <tr><td style="color:#666;"><b>Device Type</b></td><td>{alert.device_type}</td></tr>
            <tr><td style="color:#666;"><b>Batch</b></td><td><code>{alert.batch_id}</code></td></tr>
            <tr><td style="color:#666;"><b>Time</b></td><td>{detected}</td></tr>
            {"<tr><td style='color:#666;'><b>Sensors</b></td><td>" + sensor_summary + "</td></tr>" if sensor_summary else ""}
            {"<tr><td style='color:#666;'><b>Detail</b></td><td>" + (alert.error_detail or "") + "</td></tr>" if alert.error_detail else ""}
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 1, 5])
    with col1:
        if st.button("💬 Address Alert", key=f"addr_{alert.id}", type="primary"):
            _go_to_chat(alert)
            st.rerun()
    with col2:
        if st.button("❌ Dismiss", key=f"dismiss_{alert.id}"):
            with SessionLocal() as session:
                dismiss_alert(session, alert.id)
            st.session_state.popup_state = None
            st.session_state.popup_alert_id = None
            st.rerun()
    st.markdown("---")

# ---------------------------------------------------------------------------
# Auto-detect pending alerts
# ---------------------------------------------------------------------------

if st.session_state.popup_state is None:
    try:
        with SessionLocal() as session:
            _pending = get_pending_alerts(session)
        if _pending:
            st.session_state.popup_state = "step1"
            st.session_state.popup_alert_id = _pending[0].id
    except Exception:
        pass

if st.session_state.popup_state is not None:
    _render_popup()

# ---------------------------------------------------------------------------
# Tabs: Live Feed | CCP Alerts | ML Anomalies
# ---------------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["Live Feed", "CCP Alerts", "🤖 ML Anomalies"])

# ── Tab 1: Live Feed ─────────────────────────────────────────────────────────
with tab1:
    try:
        with SessionLocal() as session:
            df, total, accepted, rejected = get_live_feed(session)
    except sqlalchemy.exc.OperationalError as exc:
        st.error(f"Could not connect to database. Is the API running? ({exc})")
        st.stop()

    stream_fail = int(
        ((df["status"] == "ACCEPTED") & (~df["stream_published"])).sum()
    ) if not df.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Readings", total)
    c2.metric("ACCEPTED", accepted)
    c3.metric("REJECTED", rejected)
    c4.metric("Stream Failures", stream_fail)

    st.caption(f"Showing latest 50 of {total} readings")

    if df.empty:
        st.info("No readings yet — waiting for sensor data.")
    else:
        st.dataframe(df.style.apply(_colour_row, axis=1), use_container_width=True)

# ── Tab 2: CCP Alerts ────────────────────────────────────────────────────────
with tab2:
    try:
        with SessionLocal() as session:
            alerts_df, total_violations = get_ccp_alerts(session)
    except sqlalchemy.exc.OperationalError as exc:
        st.error(f"Could not connect to database. ({exc})")
        st.stop()

    st.metric("Total CCP Violations", total_violations)

    if alerts_df.empty:
        st.success("No CCP violations detected — all readings within safe range.")
    else:
        hcols = st.columns([2, 1, 2, 3, 2, 1])
        for col, label in zip(hcols, ["Time", "Device", "Type", "Reason", "Batch", "Action"]):
            col.markdown(f"**{label}**")
        st.markdown("<hr style='margin:4px 0;'>", unsafe_allow_html=True)

        for _, row in alerts_df.iterrows():
            cols = st.columns([2, 1, 2, 3, 2, 1])
            cols[0].write(str(row["server_received_at"])[:16])
            cols[1].write(row["device_id"])
            cols[2].write(row["device_type"])
            cols[3].write((row["rejection_reason"] or "")[:80])
            cols[4].write(row["batch_id"])
            with cols[5]:
                if st.button("💬 Address", key=f"ccp_{row['reading_id']}"):
                    _go_to_chat_for_ccp(
                        reading_id=str(row["reading_id"]),
                        device_id=str(row["device_id"]),
                        device_type=str(row["device_type"]),
                        batch_id=str(row["batch_id"]),
                        rejection_reason=str(row["rejection_reason"] or ""),
                    )
                    st.rerun()

# ── Tab 3: ML Anomalies ───────────────────────────────────────────────────────
with tab3:
    try:
        with SessionLocal() as session:
            ml_df, total_ml = get_ml_anomalies(session)
    except sqlalchemy.exc.OperationalError as exc:
        st.error(f"Could not connect to database. ({exc})")
        st.stop()

    c1, c2 = st.columns(2)
    c1.metric("Total ML Anomalies", total_ml)
    if not ml_df.empty:
        trend_count = int((ml_df["alert_type"] == "TREND_ANOMALY").sum())
        c2.metric("Trend Anomalies", trend_count)

    if ml_df.empty:
        st.success("No ML anomalies detected — all readings within normal range.")
    else:
        # Header
        hcols = st.columns([2, 1, 2, 1, 1, 2, 1])
        for col, label in zip(hcols, ["Time", "Device", "Type", "Severity", "Score", "Detail", "Action"]):
            col.markdown(f"**{label}**")
        st.markdown("<hr style='margin:4px 0;'>", unsafe_allow_html=True)

        for _, row in ml_df.iterrows():
            bg = "#fff3cd" if row["alert_type"] == "TREND_ANOMALY" else "#ffe5b4"
            cols = st.columns([2, 1, 2, 1, 1, 2, 1])
            cols[0].write(str(row["detected_at"])[:16])
            cols[1].write(row["device_id"])

            type_badge = "🟡 TREND" if row["alert_type"] == "TREND_ANOMALY" else "🟠 ANOMALY"
            cols[2].write(type_badge)
            cols[3].write(row["severity"])
            cols[4].write(row["anomaly_score"])
            cols[5].write(row["detail"])
            with cols[6]:
                if st.button("💬", key=f"ml_{row['_alert_id']}", help="Address in chat"):
                    with SessionLocal() as session:
                        alert_obj = (
                            session.query(Alert)
                            .filter(Alert.id == int(row["_alert_id"]))
                            .first()
                        )
                    if alert_obj:
                        _go_to_chat(alert_obj)
                        st.rerun()
