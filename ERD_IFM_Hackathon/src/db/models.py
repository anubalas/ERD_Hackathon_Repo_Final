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
