import pytest
from pydantic import ValidationError

from src.api.schemas import SensorReading, validate_ccp_ranges


VALID_BOILER = {
    "device_id": "boiler-01",
    "device_type": "boiler",
    "temperature": 150.0,
    "pressure": 6.0,
    "batch_id": "B001",
    "timestamp": "2026-06-09T10:00:00Z",
}

VALID_PASTEURIZER = {
    "device_id": "past-01",
    "device_type": "pasteurizer",
    "temperature": 80.0,
    "ph": 5.5,
    "flow_rate": 100.0,
    "batch_id": "B002",
    "timestamp": "2026-06-09T10:00:00Z",
}

VALID_DRYER = {
    "device_id": "dryer-01",
    "device_type": "dryer",
    "temperature": 120.0,
    "humidity": 30.0,
    "batch_id": "B003",
    "timestamp": "2026-06-09T10:00:00Z",
}


# ---------------------------------------------------------------------------
# Structural validation (T011)
# ---------------------------------------------------------------------------

class TestSensorReadingStructural:
    def test_valid_boiler_reading(self):
        r = SensorReading(**VALID_BOILER)
        assert r.device_id == "boiler-01"
        assert r.device_type == "boiler"

    def test_missing_device_id_raises(self):
        data = {**VALID_BOILER}
        del data["device_id"]
        with pytest.raises(ValidationError):
            SensorReading(**data)

    def test_missing_batch_id_raises(self):
        data = {**VALID_BOILER}
        del data["batch_id"]
        with pytest.raises(ValidationError):
            SensorReading(**data)

    def test_empty_device_id_raises(self):
        with pytest.raises(ValidationError, match="non-empty"):
            SensorReading(**{**VALID_BOILER, "device_id": "  "})

    def test_empty_batch_id_raises(self):
        with pytest.raises(ValidationError, match="non-empty"):
            SensorReading(**{**VALID_BOILER, "batch_id": ""})

    def test_negative_temperature_raises(self):
        with pytest.raises(ValidationError, match=">= 0"):
            SensorReading(**{**VALID_BOILER, "temperature": -1.0})

    def test_negative_ph_raises(self):
        with pytest.raises(ValidationError, match=">= 0"):
            SensorReading(**{**VALID_PASTEURIZER, "ph": -0.1})

    def test_optional_fields_default_none(self):
        r = SensorReading(**VALID_BOILER)
        assert r.humidity is None
        assert r.ph is None
        assert r.flow_rate is None

    def test_missing_timestamp_raises(self):
        data = {**VALID_BOILER}
        del data["timestamp"]
        with pytest.raises(ValidationError):
            SensorReading(**data)


# ---------------------------------------------------------------------------
# device_type normalisation (T019)
# ---------------------------------------------------------------------------

class TestDeviceTypeValidation:
    def test_uppercase_device_type_normalised(self):
        r = SensorReading(**{**VALID_BOILER, "device_type": "BOILER"})
        assert r.device_type == "boiler"

    def test_mixed_case_device_type_normalised(self):
        r = SensorReading(**{**VALID_BOILER, "device_type": "Pasteurizer"})
        assert r.device_type == "pasteurizer"

    def test_unknown_device_type_raises(self):
        with pytest.raises(ValidationError, match="Unknown device_type"):
            SensorReading(**{**VALID_BOILER, "device_type": "oven"})

    def test_all_known_types_accepted(self):
        for dtype in ("boiler", "pasteurizer", "dryer"):
            data = {**VALID_BOILER, "device_type": dtype}
            r = SensorReading(**data)
            assert r.device_type == dtype


# ---------------------------------------------------------------------------
# CCP range validation (T016)
# ---------------------------------------------------------------------------

class TestValidateCcpRanges:
    def test_no_violations_for_valid_boiler(self):
        r = SensorReading(**VALID_BOILER)
        assert validate_ccp_ranges(r) == []

    def test_no_violations_for_valid_pasteurizer(self):
        r = SensorReading(**VALID_PASTEURIZER)
        assert validate_ccp_ranges(r) == []

    def test_no_violations_for_valid_dryer(self):
        r = SensorReading(**VALID_DRYER)
        assert validate_ccp_ranges(r) == []

    def test_boiler_temperature_below_min(self):
        r = SensorReading(**{**VALID_BOILER, "temperature": 119.9})
        violations = validate_ccp_ranges(r)
        assert len(violations) == 1
        assert violations[0].field == "temperature"
        assert "below minimum" in violations[0].message

    def test_boiler_temperature_above_max(self):
        r = SensorReading(**{**VALID_BOILER, "temperature": 200.1})
        violations = validate_ccp_ranges(r)
        assert len(violations) == 1
        assert violations[0].field == "temperature"
        assert "exceeds maximum" in violations[0].message

    def test_boiler_temperature_at_boundary_min(self):
        r = SensorReading(**{**VALID_BOILER, "temperature": 120.0})
        assert validate_ccp_ranges(r) == []

    def test_boiler_temperature_at_boundary_max(self):
        r = SensorReading(**{**VALID_BOILER, "temperature": 200.0})
        assert validate_ccp_ranges(r) == []

    def test_pasteurizer_ph_out_of_range(self):
        r = SensorReading(**{**VALID_PASTEURIZER, "ph": 8.0})
        violations = validate_ccp_ranges(r)
        assert any(v.field == "ph" for v in violations)

    def test_dryer_humidity_out_of_range(self):
        r = SensorReading(**{**VALID_DRYER, "humidity": 61.0})
        violations = validate_ccp_ranges(r)
        assert any(v.field == "humidity" for v in violations)

    def test_multiple_violations_reported(self):
        r = SensorReading(**{**VALID_BOILER, "temperature": 50.0, "pressure": 0.5})
        violations = validate_ccp_ranges(r)
        assert len(violations) == 2

    def test_ccp_field_not_provided_skipped(self):
        # boiler with no pressure — no pressure violation
        r = SensorReading(**{**VALID_BOILER})
        r2 = SensorReading(**{**VALID_BOILER, "pressure": None})
        violations = validate_ccp_ranges(r2)
        # temperature is in range; pressure None → skipped
        assert all(v.field != "pressure" for v in violations)

    def test_violation_contains_allowed_range(self):
        r = SensorReading(**{**VALID_BOILER, "temperature": 50.0})
        v = validate_ccp_ranges(r)[0]
        assert v.allowed_range == {"min": 120.0, "max": 200.0}
        assert v.received == 50.0
