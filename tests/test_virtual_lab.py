from __future__ import annotations

import json

from schemas.circuit import CircuitDesign, Component, Connection
from services.virtual_lab.generator import (
    VirtualLabGenerator,
    build_deterministic_procedure,
)
from services.virtual_lab.models import LabProcedure, SafetyNote
from services.virtual_lab.report import build_lab_report
from services.virtual_lab.safety import get_safety_notes


def _make_design(supply_voltage_v=5.0, **kwargs) -> CircuitDesign:
    defaults = dict(
        project_name="Test Lab Circuit",
        project_description="A test circuit for lab procedures",
        supply_voltage_v=supply_voltage_v,
        components=[
            Component(reference="R1", name="Resistor", value="220 Ohm", evidence_status="unverified"),
            Component(reference="D1", name="LED", value="Red LED", evidence_status="unverified"),
        ],
        connections=[
            Connection(net_name="GND", pins=["R1.2", "D1.2"], confidence=0.9),
            Connection(net_name="VCC", pins=["R1.1", "D1.1"], confidence=0.9),
        ],
    )
    defaults.update(kwargs)
    return CircuitDesign(**defaults)


def _make_series_led_design(**kwargs) -> CircuitDesign:
    defaults = dict(
        project_name="Series LED Lab",
        project_description="A 5 V LED with a series resistor",
        supply_voltage_v=5.0,
        components=[
            Component(reference="R1", name="Resistor", value="220 Ohm", evidence_status="user_supplied"),
            Component(reference="D1", name="LED", value="Red LED", evidence_status="user_supplied"),
            Component(reference="J1", name="Power connector", evidence_status="user_supplied"),
        ],
        connections=[
            Connection(net_name="VCC", pins=["J1.1", "R1.1"], confidence=0.95),
            Connection(net_name="LED_A", pins=["R1.2", "D1.1"], confidence=0.95),
            Connection(net_name="GND", pins=["D1.2", "J1.2"], confidence=0.95),
        ],
    )
    defaults.update(kwargs)
    return CircuitDesign(**defaults)


def _make_divider_design(**kwargs) -> CircuitDesign:
    defaults = dict(
        project_name="Divider Lab",
        project_description="A 5 V resistor divider",
        supply_voltage_v=5.0,
        components=[
            Component(reference="R1", name="Resistor", value="10 kOhm", evidence_status="user_supplied"),
            Component(reference="R2", name="Resistor", value="10 kOhm", evidence_status="user_supplied"),
            Component(reference="J1", name="Power connector", evidence_status="user_supplied"),
        ],
        connections=[
            Connection(net_name="VCC", pins=["J1.1", "R1.1"], confidence=0.95),
            Connection(net_name="MID", pins=["R1.2", "R2.1"], confidence=0.95),
            Connection(net_name="GND", pins=["R2.2", "J1.2"], confidence=0.95),
        ],
    )
    defaults.update(kwargs)
    return CircuitDesign(**defaults)


class TestSafetyNotes:
    def test_always_has_base_note(self):
        design = _make_design(supply_voltage_v=5.0)
        notes = get_safety_notes(design)
        assert len(notes) > 0
        assert all(isinstance(n, SafetyNote) for n in notes)

    def test_warning_for_dangerous_voltage(self):
        design = _make_design(supply_voltage_v=50.0)
        notes = get_safety_notes(design)
        warning_notes = [n for n in notes if n.severity == "WARNING"]
        assert len(warning_notes) >= 1

    def test_no_voltage_warning_for_low_voltage(self):
        design = _make_design(supply_voltage_v=5.0)
        notes = get_safety_notes(design)
        for note in notes:
            if note.severity == "WARNING":
                assert str(design.supply_voltage_v) not in note.note or "above 50" not in note.note

    def test_polarity_warning_for_leds(self):
        design = _make_design()
        notes = get_safety_notes(design)
        polarity_notes = [n for n in notes if "polarity" in n.note.lower()]
        assert len(polarity_notes) >= 1

    def test_ammeter_note_always_present(self):
        design = _make_design()
        notes = get_safety_notes(design)
        ammeter_notes = [
            n for n in notes if "ammeter" in n.note.lower() or "current mode" in n.note.lower()
        ]
        assert len(ammeter_notes) >= 1

    def test_all_notes_are_deterministic(self):
        design = _make_design()
        notes = get_safety_notes(design)
        assert all(n.is_deterministic is True for n in notes)


class TestLabProcedureModel:
    def test_disclaimer_present(self):
        proc = LabProcedure(circuit_name="Test", supply_voltage_v=5.0)
        assert "testing procedure" in proc.disclaimer.lower()

    def test_empty_procedure_is_valid(self):
        proc = LabProcedure(circuit_name="Test")
        assert proc.equipment == []
        assert proc.pre_power_checks == []
        assert proc.measurement_points == []
        assert proc.test_sequence == []
        assert proc.troubleshooting == []


class TestDeterministicProcedure:
    def test_builds_circuit_specific_procedure_without_ai(self):
        design = _make_series_led_design()
        procedure = build_deterministic_procedure(design)

        assert procedure.generation_mode == "deterministic"
        assert procedure.ai_assisted is False
        assert procedure.design_fingerprint
        assert any("multimeter" in item.name.lower() for item in procedure.equipment)
        assert any(check.critical for check in procedure.pre_power_checks)
        assert any("LED" in point.description for point in procedure.measurement_points)
        assert any("LED" in step.title for step in procedure.test_sequence)
        assert any(note.severity == "CAUTION" for note in procedure.safety_notes)

    def test_unknown_expected_values_are_not_invented(self):
        procedure = build_deterministic_procedure(_make_series_led_design())
        current_points = [
            point
            for point in procedure.measurement_points
            if "Current through" in point.description
        ]
        assert current_points
        assert current_points[0].expected_result_basis == "requires_verification"
        assert current_points[0].is_calculated is False

    def test_led_current_is_calculated_when_forward_voltage_is_declared(self):
        design = _make_series_led_design(
            components=[
                Component(
                    reference="R1",
                    name="Resistor",
                    value="220 Ohm",
                    evidence_status="user_supplied",
                ),
                Component(
                    reference="D1",
                    name="LED",
                    value="Red LED",
                    forward_voltage_v=2.0,
                    evidence_status="user_supplied",
                ),
                Component(reference="J1", name="Power connector", evidence_status="user_supplied"),
            ]
        )
        procedure = build_deterministic_procedure(design)
        point = next(
            item
            for item in procedure.measurement_points
            if "Current through D1" in item.description
        )
        assert point.expected_result_basis == "calculated"
        assert point.is_calculated is True
        assert "13.64 mA" in point.expected_result

    def test_divider_output_is_calculated(self):
        procedure = build_deterministic_procedure(_make_divider_design())
        point = next(
            item
            for item in procedure.measurement_points
            if "Divider output" in item.description
        )
        assert point.expected_result_basis == "calculated"
        assert "2.500 V" in point.expected_result
        assert point.is_calculated is True

    def test_supply_rail_is_a_design_target_not_a_calculation(self):
        procedure = build_deterministic_procedure(_make_series_led_design())
        point = next(
            item
            for item in procedure.measurement_points
            if item.description == "Positive supply rail voltage"
        )
        assert point.expected_result_basis == "design_target"
        assert point.is_calculated is False

    def test_printable_report_contains_labels_and_fingerprint(self):
        design = _make_divider_design()
        procedure = build_deterministic_procedure(design)
        report = build_lab_report(procedure, design)

        assert "# Virtual Lab Testing Procedure" in report
        assert procedure.design_fingerprint in report
        assert "CALCULATED from declared data" in report
        assert "REQUIRES CALCULATION / DATASHEET" in report
        assert "does not claim" in report.lower()


class _DummyLabClient:
    def __init__(self, payload: dict | None = None, error: Exception | None = None):
        self.payload = payload or {}
        self.error = error
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        if self.error:
            raise self.error
        assert "lab instructor" in system_prompt
        return json.dumps(self.payload)


class TestAiMergeBoundary:
    def test_ai_cannot_overwrite_calculated_values(self):
        design = _make_divider_design()
        baseline = build_deterministic_procedure(design)
        baseline_point = next(
            item for item in baseline.measurement_points if "Divider output" in item.description
        )

        client = _DummyLabClient(
            {
                "equipment": [
                    {
                        "name": "Thermal camera",
                        "reason": "Check component heating",
                        "required": True,
                    }
                ],
                "pre_power_checks": [],
                "measurement_points": [
                    {
                        "description": "AI-suggested divider check",
                        "measurement_location": "MID",
                        "reference_ground": "GND",
                        "instrument": "Multimeter",
                        "measurement_mode": "DC voltage",
                        "expected_result": "999 V",
                        "abnormal_indication": "Any difference",
                        "reason": "Because",
                        "safety_note": None,
                    }
                ],
                "troubleshooting": [],
                "notes": ["AI note"],
            }
        )
        generator = VirtualLabGenerator(settings=None, enable_ai=True)
        generator._client = client
        procedure = generator.generate(design, use_ai=True)

        assert client.calls == 1
        assert procedure.generation_mode == "ai_assisted"
        assert procedure.ai_assisted is True

        calculated = [
            item
            for item in procedure.measurement_points
            if item.description == baseline_point.description
        ]
        assert len(calculated) == 1
        assert calculated[0].expected_result == baseline_point.expected_result
        assert calculated[0].expected_result_basis == "calculated"
        assert calculated[0].is_ai_generated is False

        ai_points = [item for item in procedure.measurement_points if item.is_ai_generated]
        assert len(ai_points) == 1
        assert ai_points[0].expected_result_basis == "ai_suggested"
        assert ai_points[0].is_calculated is False
        assert "UNVERIFIED" in ai_points[0].expected_result

        assert any(item.name == "Thermal camera" for item in procedure.equipment)
        ai_equipment = next(
            item for item in procedure.equipment if item.name == "Thermal camera"
        )
        assert ai_equipment.required is False
        assert ai_equipment.is_ai_generated is True
        assert any("AI contextual" in note or "AI contextual" in note for note in procedure.generation_notes)

    def test_ai_failure_returns_deterministic_baseline(self):
        generator = VirtualLabGenerator(settings=None, enable_ai=True)
        generator._client = _DummyLabClient(error=RuntimeError("provider unavailable"))
        procedure = generator.generate(_make_divider_design(), use_ai=True)

        assert procedure.generation_mode == "deterministic"
        assert procedure.ai_assisted is False
        assert any("provider unavailable" in note for note in procedure.generation_notes)
