"""Pydantic models for the Virtual Lab Assistant output."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EquipmentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    specification: str | None = None
    reason: str
    required: bool = True
    is_ai_generated: bool = False


class PrePowerCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int
    description: str
    how_to_verify: str
    critical: bool = False
    is_ai_generated: bool = False


ExpectedBasis = Literal[
    "calculated",
    "design_target",
    "requires_verification",
    "ai_suggested",
]


class MeasurementPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_id: str
    description: str
    measurement_location: str
    reference_ground: str
    instrument: Literal[
        "Multimeter",
        "Oscilloscope",
        "Current Probe",
        "Power Supply",
        "Frequency Counter",
    ]
    measurement_mode: str
    expected_result: str
    expected_result_basis: ExpectedBasis = "requires_verification"
    is_calculated: bool = False
    is_ai_generated: bool = False
    abnormal_indication: str
    reason: str
    safety_note: str | None = None


class TestStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int
    title: str
    description: str
    expected_outcome: str
    safety_precaution: str | None = None
    is_ai_generated: bool = False


class TroubleshootingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symptom: str
    possible_causes: list[str]
    diagnostic_actions: list[str]
    is_ai_generated: bool = False


class SafetyNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["WARNING", "CAUTION", "INFO"]
    note: str
    is_deterministic: bool = True


class LabProcedure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    circuit_name: str
    supply_voltage_v: float | None = None
    required_components: list[str] = Field(default_factory=list)
    equipment: list[EquipmentItem] = Field(default_factory=list)
    pre_power_checks: list[PrePowerCheck] = Field(default_factory=list)
    measurement_points: list[MeasurementPoint] = Field(default_factory=list)
    test_sequence: list[TestStep] = Field(default_factory=list)
    troubleshooting: list[TroubleshootingEntry] = Field(default_factory=list)
    safety_notes: list[SafetyNote] = Field(default_factory=list)
    generation_mode: Literal["deterministic", "ai_assisted", "fallback"] = "deterministic"
    ai_assisted: bool = False
    design_fingerprint: str = ""
    generated_at: str = Field(default_factory=_utc_now)
    disclaimer: str = (
        "This testing procedure is engineering guidance, not a verified test "
        "procedure. Expected values marked 'Requires calculation or datasheet "
        "confirmation' have not been calculated. No simulation or physical "
        "measurement was performed. Never work on a powered circuit without "
        "appropriate training, equipment and supervision."
    )
    generation_notes: list[str] = Field(default_factory=list)
