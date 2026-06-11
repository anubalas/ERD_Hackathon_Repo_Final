"""Agent tools for the IFM GMP Chat Assistant.

Three tools available to Claude:
  - query_alerts_db  : query SQLite alerts table with structured filters
  - search_gmp_docs  : semantic search over SOP/GMP documents in ChromaDB
  - generate_report  : create a Plotly chart from alert data
"""
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Claude tool definitions (passed to client.messages.create)
# ---------------------------------------------------------------------------

CLAUDE_TOOLS = [
    {
        "name": "query_alerts_db",
        "description": (
            "Query the IFM alerts database for anomaly and CCP breach records. "
            "Use this when the operator asks about alerts, breaches, or device history. "
            "Returns a text summary of matching alert records."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "Look back this many hours (default 24). Use 168 for 1 week.",
                },
                "device_type": {
                    "type": "string",
                    "description": "Filter by device type: boiler, pasteurizer, or dryer.",
                },
                "alert_type": {
                    "type": "string",
                    "description": "Filter by type: ANOMALY, TREND_ANOMALY, CCP_BREACH, or PIPELINE_ERROR.",
                },
                "severity": {
                    "type": "string",
                    "description": "Filter by severity: CRITICAL or WARNING.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of records to return (default 20).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_gmp_docs",
        "description": (
            "Search GMP/SOP documents for procedures, regulations, and remediation steps. "
            "Use this when the operator asks about SOPs, procedures, compliance, or what to do "
            "about a specific type of alert or device issue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query for SOP/GMP documents.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "generate_report",
        "description": (
            "Generate a visual chart of alert data. Use when the operator asks for a summary, "
            "trend analysis, or visual breakdown of alerts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": ["alerts_by_device", "alerts_by_severity", "alerts_over_time"],
                    "description": (
                        "alerts_by_device: bar chart of alert count per device type. "
                        "alerts_by_severity: pie chart of CRITICAL vs WARNING. "
                        "alerts_over_time: line chart of alert frequency over time."
                    ),
                },
                "hours": {
                    "type": "integer",
                    "description": "Time window in hours (default 24).",
                },
            },
            "required": ["report_type"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _query_alerts_db(session, hours=24, device_type=None, alert_type=None,
                     severity=None, limit=20) -> str:
    from sqlalchemy import text

    hours = int(hours or 24)
    limit = int(limit or 20)

    sql = (
        "SELECT id, device_id, device_type, alert_type, severity, "
        "detected_at, error_detail, anomaly_score "
        "FROM alerts WHERE detected_at > datetime('now', :hrs)"
    )
    params: dict = {"hrs": f"-{hours} hours"}

    if device_type:
        sql += " AND device_type = :dt"
        params["dt"] = device_type
    if alert_type:
        sql += " AND alert_type = :at"
        params["at"] = alert_type
    if severity:
        sql += " AND severity = :sev"
        params["sev"] = severity

    sql += f" ORDER BY detected_at DESC LIMIT {limit}"

    try:
        rows = session.execute(text(sql), params).fetchall()
    except Exception as exc:
        logger.error("query_alerts_db error: %s", exc)
        return f"Database query failed: {exc}"

    if not rows:
        return f"No alerts found in the last {hours} hours matching your criteria."

    lines = [f"Found {len(rows)} alert(s) in the last {hours} hours:\n"]
    for r in rows:
        score = f"  score={r.anomaly_score:.3f}" if r.anomaly_score else ""
        detail = f"  detail={r.error_detail[:60]}" if r.error_detail else ""
        lines.append(
            f"• [{r.detected_at}] {r.device_id} ({r.device_type}) "
            f"— {r.alert_type} [{r.severity or 'N/A'}]{score}{detail}"
        )
    return "\n".join(lines)


def _search_gmp_docs(collection, query: str) -> str:
    if collection is None:
        return "SOP document search is unavailable — ChromaDB collection not loaded."
    try:
        from src.rag.chroma_store import query_collection
        from src.agent.agent import format_sop_context
        chunks = query_collection(collection, query, n_results=3)
        return format_sop_context(chunks)
    except Exception as exc:
        logger.error("search_gmp_docs error: %s", exc)
        return f"SOP search failed: {exc}"


def _generate_report(session, report_type: str, hours: int = 24):
    """Returns (summary_text, plotly_figure_or_None)."""
    try:
        import plotly.graph_objects as go
        from sqlalchemy import text

        hours = int(hours or 24)
        sql = (
            "SELECT device_type, severity, alert_type, detected_at "
            "FROM alerts WHERE detected_at > datetime('now', :hrs) "
            "ORDER BY detected_at ASC"
        )
        rows = session.execute(text(sql), {"hrs": f"-{hours} hours"}).fetchall()

        if not rows:
            return f"No alert data available for the last {hours} hours.", None

        if report_type == "alerts_by_device":
            counts: dict = defaultdict(int)
            for r in rows:
                counts[r.device_type or "unknown"] += 1
            fig = go.Figure(
                go.Bar(
                    x=list(counts.keys()),
                    y=list(counts.values()),
                    marker_color=["#e74c3c", "#f39c12", "#3498db"][: len(counts)],
                )
            )
            fig.update_layout(
                title=f"Alerts by Device Type (last {hours}h)",
                xaxis_title="Device Type",
                yaxis_title="Alert Count",
                height=350,
            )
            summary = (
                f"Alert breakdown by device (last {hours}h): "
                + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
            )
            return summary, fig

        elif report_type == "alerts_by_severity":
            counts = defaultdict(int)
            for r in rows:
                counts[r.severity or "UNCLASSIFIED"] += 1
            colors = {"CRITICAL": "#e74c3c", "WARNING": "#f39c12", "UNCLASSIFIED": "#95a5a6"}
            fig = go.Figure(
                go.Pie(
                    labels=list(counts.keys()),
                    values=list(counts.values()),
                    marker_colors=[colors.get(k, "#3498db") for k in counts],
                )
            )
            fig.update_layout(
                title=f"Alerts by Severity (last {hours}h)", height=350
            )
            summary = (
                f"Severity breakdown (last {hours}h): "
                + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
            )
            return summary, fig

        elif report_type == "alerts_over_time":
            hourly: dict = defaultdict(int)
            for r in rows:
                hour_key = str(r.detected_at)[:13]  # "2026-06-09 17"
                hourly[hour_key] += 1
            sorted_hours = sorted(hourly.keys())
            fig = go.Figure(
                go.Scatter(
                    x=sorted_hours,
                    y=[hourly[h] for h in sorted_hours],
                    mode="lines+markers",
                    line={"color": "#e74c3c"},
                )
            )
            fig.update_layout(
                title=f"Alerts Over Time (last {hours}h)",
                xaxis_title="Time",
                yaxis_title="Alert Count",
                height=350,
            )
            summary = f"Total {len(rows)} alerts over the last {hours} hours."
            return summary, fig

        return "Unknown report type.", None

    except Exception as exc:
        logger.error("generate_report error: %s", exc)
        return f"Report generation failed: {exc}", None


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def execute_tool(tool_name: str, tool_input: dict, session, collection):
    """Execute a named tool. Returns (result_text, chart_or_None)."""
    logger.info("  [tool] executing: %s input=%s", tool_name, tool_input)

    if tool_name == "query_alerts_db":
        # Remove free-text 'query' key — not a valid param for _query_alerts_db
        structured = {k: v for k, v in tool_input.items() if k != "query"}
        return _query_alerts_db(session, **structured), None

    if tool_name == "search_gmp_docs":
        return _search_gmp_docs(collection, tool_input.get("query", "")), None

    if tool_name == "generate_report":
        return _generate_report(
            session,
            report_type=tool_input.get("report_type", "alerts_by_device"),
            hours=tool_input.get("hours", 24),
        )

    return f"Unknown tool: {tool_name}", None
