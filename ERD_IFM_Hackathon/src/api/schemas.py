from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

KNOWN_DEVICE_TYPES = {"boiler", "pasteurizer", "dryer"}


# ---------------------------------------------------------------------------
# Inbound payload (T004 — structural validation only, no CCP range checks)
# ---------------------------------------------------------------------------

class SensorReading(BaseModel):
    device_id: str
    device_type: str
    temperature: Optional[float] = None
    pressure: Optional[float] = None
    humidity: Optional[float] = None
    ph: Optional[float] = None
    flow_rate: Optional[float] = None
    batch_id: str
    timestamp: datetime

    @field_validator("device_id", "batch_id")
    @classmethod
    def must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("device_type")
    @classmethod
    def normalise_device_type(cls, v: str) -> str:
        normalised = v.strip().lower()
        if normalised not in KNOWN_DEVICE_TYPES:
            raise ValueError(
                f"Unknown device_type: {v!r}. "
                f"Must be one of {sorted(KNOWN_DEVICE_TYPES)}"
            )
        return normalised

    @field_validator("temperature", "pressure", "humidity", "ph", "flow_rate", mode="before")
    @classmethod
    def must_be_non_negative(cls, v):
        if v is not None and float(v) < 0:
            raise ValueError("must be >= 0")
        return v


# ---------------------------------------------------------------------------
# CCP threshold configuration (T007)
# ---------------------------------------------------------------------------

@dataclass
class CCPRange:
    min: float
    max: float


@dataclass
class DeviceThresholds:
    temperature: Optional[CCPRange] = field(default=None)
    pressure: Optional[CCPRange] = field(default=None)
    humidity: Optional[CCPRange] = field(default=None)
    ph: Optional[CCPRange] = field(default=None)
    flow_rate: Optional[CCPRange] = field(default=None)


CCP_THRESHOLDS: dict[str, DeviceThresholds] = {
    "boiler": DeviceThresholds(
        temperature=CCPRange(120.0, 200.0),
        pressure=CCPRange(1.0, 12.0),
    ),
    "pasteurizer": DeviceThresholds(
        temperature=CCPRange(72.0, 90.0),
        ph=CCPRange(3.5, 7.5),
        flow_rate=CCPRange(5.0, 200.0),
    ),
    "dryer": DeviceThresholds(
        temperature=CCPRange(80.0, 160.0),
        humidity=CCPRange(5.0, 60.0),
    ),
}


class CCPViolation(BaseModel):
    field: str
    message: str
    received: float
    allowed_range: dict


def validate_ccp_ranges(reading: SensorReading) -> list[CCPViolation]:
    thresholds = CCP_THRESHOLDS.get(reading.device_type)
    if thresholds is None:
        return []

    violations: list[CCPViolation] = []
    checks = [
        ("temperature", reading.temperature, thresholds.temperature),
        ("pressure", reading.pressure, thresholds.pressure),
        ("humidity", reading.humidity, thresholds.humidity),
        ("ph", reading.ph, thresholds.ph),
        ("flow_rate", reading.flow_rate, thresholds.flow_rate),
    ]

    for field_name, value, threshold in checks:
        if value is None or threshold is None:
            continue
        if value < threshold.min:
            violations.append(
                CCPViolation(
                    field=field_name,
                    message=(
                        f"Value {value} is below minimum {threshold.min} "
                        f"for {reading.device_type}"
                    ),
                    received=value,
                    allowed_range={"min": threshold.min, "max": threshold.max},
                )
            )
        elif value > threshold.max:
            violations.append(
                CCPViolation(
                    field=field_name,
                    message=(
                        f"Value {value} exceeds maximum {threshold.max} "
                        f"for {reading.device_type}"
                    ),
                    received=value,
                    allowed_range={"min": threshold.min, "max": threshold.max},
                )
            )

    return violations


# ---------------------------------------------------------------------------
# Response types (T007)
# ---------------------------------------------------------------------------

class TelemetryResponse(BaseModel):
    reading_id: str
    status: Literal["ACCEPTED"] = "ACCEPTED"
    server_received_at: datetime
    stream_published: bool
    warnings: list[str] = []
