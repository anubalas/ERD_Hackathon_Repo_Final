from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TelemetryLog(Base):
    __tablename__ = "telemetry_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reading_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    device_type: Mapped[str] = mapped_column(String, nullable=False)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    ph: Mapped[float | None] = mapped_column(Float, nullable=True)
    flow_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    batch_id: Mapped[str] = mapped_column(String, nullable=False)
    device_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    server_received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    stream_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    stale_timestamp: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_telemetry_log_batch_id", "batch_id"),
        Index("ix_telemetry_log_status", "status"),
        Index("ix_telemetry_log_server_received_at", "server_received_at"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reading_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sensor_values: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_alerts_device_id", "device_id"),
        Index("ix_alerts_batch_id", "batch_id"),
        Index("ix_alerts_alert_type", "alert_type"),
        Index("ix_alerts_detected_at", "detected_at"),
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    citation: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_agent_runs_alert_id", "alert_id"),
        Index("ix_agent_runs_created_at", "created_at"),
    )
