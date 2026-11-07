from __future__ import annotations

import json

from electronics.red_team.engine import RedTeamEngine
from electronics.red_team.models import FindingSeverity, RedTeamReport
from electronics.red_team.rules import (
    check_component_voltage_ratings,
    check_led_current_limiting,
    check_no_ground_net,
    check_supply_voltage_declared,
    run_all_deterministic_rules,
)
from schemas.circuit import CircuitDesign, Component, Connection


def _make_simple_design(**kwargs) -> CircuitDesign:
    defaults = dict(
        project_name="Test Circuit",
        project_description="A simple test circuit",
        supply_voltage_v=5.0,
        components=[
            Component(reference="R1", name="Resistor", value="220 Ohm", evidence_status="unverified"),
            Component(reference="D1", name="LED", value="Red LED", evidence_status="unverified"),
        ],
        connections=[
            Connection(
                net_name="GND",
                pins=["R1.2", "D1.2"],
                confidence=0.9,
            ),
            Connection(
                net_name="VCC",
                pins=["R1.1", "D1.1"],
                confidence=0.9,
            ),
        ],
    )
    defaults.update(kwargs)
    return CircuitDesign(**defaults)


def _make_series_led_design(**kwargs) -> CircuitDesign:
    """VCC -> R1 -> LED -> GND, a true series current-limiting path."""
    defaults = dict(
        project_name="Series LED",
        project_description="An LED with a series resistor",
        supply_voltage_v=5.0,
        components=[
            Component(reference="R1", name="Resistor", value="220 Ohm", evidence_status="unverified"),
            Component(reference="D1", name="LED", value="Red LED", evidence_status="unverified"),
            Component(reference="J1", name="Power connector", evidence_status="unverified"),
        ],
        connections=[
            Connection(net_name="VCC", pins=["J1.1", "R1.1"], confidence=0.9),
            Connection(net_name="LED_A", pins=["R1.2", "D1.1"], confidence=0.9),
            Connection(net_name="GND", pins=["D1.2", "J1.2"], confidence=0.9),
        ],
    )
    defaults.update(kwargs)
    return CircuitDesign(**defaults)


# ---------------------------------------------------------------------------
# Deterministic rule tests
# ---------------------------------------------------------------------------

class TestSupplyVoltageDeclared:
    def test_no_findings_when_supply_declared(self):
        design = _make_simple_design(supply_voltage_v=5.0)
        findings = check_supply_voltage_declared(design)
        assert findings == []

    def test_medium_finding_when_supply_missing(self):
        design = _make_simple_design(supply_voltage_v=None)
        findings = check_supply_voltage_declared(design)
        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.MEDIUM
        assert findings[0].verification_status == "DETERMINISTIC"


class TestComponentVoltageRatings:
    def test_critical_when_rating_below_supply(self):
        design = CircuitDesign(
            project_name="Test",
            project_description="Test",
            supply_voltage_v=12.0,
            components=[
                Component(
                    reference="C1",
                    name="Capacitor",
                    value="100uF",
                    voltage_rating_v=6.3,  # Below 12V supply
                    evidence_status="unverified",
                )
            ],
            connections=[],
        )
        findings = check_component_voltage_ratings(design)
        assert any(f.severity == FindingSeverity.CRITICAL for f in findings)
        assert findings[0].component_reference == "C1"
        assert findings[0].verification_status == "DETERMINISTIC"

    def test_no_findings_when_rating_above_supply(self):
        design = CircuitDesign(
            project_name="Test",
            project_description="Test",
            supply_voltage_v=5.0,
            components=[
                Component(
                    reference="C1",
                    name="Capacitor",
                    value="100uF",
                    voltage_rating_v=16.0,
                    evidence_status="unverified",
                )
            ],
            connections=[],
        )
        findings = check_component_voltage_ratings(design)
        assert findings == []

    def test_no_findings_when_no_supply_voltage(self):
        design = CircuitDesign(
            project_name="Test",
            project_description="Test",
            supply_voltage_v=None,
            components=[
                Component(
                    reference="C1",
                    name="Capacitor",
                    value="100uF",
                    voltage_rating_v=6.3,
                    evidence_status="unverified",
                )
            ],
            connections=[],
        )
        # Cannot check without supply voltage — should return empty
        findings = check_component_voltage_ratings(design)
        assert findings == []


class TestLedCurrentLimiting:
    def test_high_finding_for_led_without_resistor(self):
        design = CircuitDesign(
            project_name="Test",
            project_description="Test",
            supply_voltage_v=5.0,
            components=[
                Component(reference="D1", name="LED", evidence_status="unverified"),
                Component(reference="U1", name="Microcontroller", evidence_status="unverified"),
            ],
            connections=[
                Connection(net_name="GND", pins=["D1.2", "U1.2"], confidence=0.9),
                Connection(net_name="OUT", pins=["D1.1", "U1.1"], confidence=0.9),
            ],
        )
        findings = check_led_current_limiting(design)
        assert any(f.severity == FindingSeverity.HIGH for f in findings)
        assert any(f.component_reference == "D1" for f in findings)

    def test_no_finding_when_resistor_is_in_series(self):
        design = _make_series_led_design()
        findings = check_led_current_limiting(design)
        assert all(
            finding.component_reference != "D1"
            or finding.severity != FindingSeverity.HIGH
            for finding in findings
        )

    def test_parallel_resistor_is_not_a_series_limiter(self):
        design = _make_simple_design()
        findings = check_led_current_limiting(design)
        assert any(
            finding.component_reference == "D1"
            and finding.severity == FindingSeverity.HIGH
            and "parallel" in finding.description.lower()
            for finding in findings
        )


class TestNoGroundNet:
    def test_high_finding_when_no_gnd(self):
        design = CircuitDesign(
            project_name="Test",
            project_description="Test",
            supply_voltage_v=5.0,
            components=[
                Component(reference="R1", name="Resistor", evidence_status="unverified"),
                Component(reference="R2", name="Resistor", evidence_status="unverified"),
            ],
            connections=[
                Connection(net_name="NET1", pins=["R1.1", "R2.1"], confidence=0.9),
                Connection(net_name="NET2", pins=["R1.2", "R2.2"], confidence=0.9),
            ],
        )
        findings = check_no_ground_net(design)
        assert any(f.severity == FindingSeverity.HIGH for f in findings)

    def test_no_finding_when_gnd_present(self):
        design = _make_simple_design()
        findings = check_no_ground_net(design)
        assert findings == []


class TestUnknownVoltageRatings:
    def test_informational_for_unrated_component_when_supply_known(self):
        design = _make_simple_design()
        # Neither R1 nor D1 have voltage ratings
        from electronics.red_team.rules import check_missing_voltage_ratings
        findings = check_missing_voltage_ratings(design)
        assert any(f.severity == FindingSeverity.INFORMATIONAL for f in findings)
        assert all(f.verification_status == "INCOMPLETE_DATA" for f in findings)


class TestRunAllRules:
    def test_returns_findings_and_check_names(self):
        design = _make_simple_design()
        findings, checks_run = run_all_deterministic_rules(design)
        assert isinstance(findings, list)
        assert isinstance(checks_run, list)
        assert len(checks_run) > 0

    def test_no_critical_for_well_formed_simple_circuit(self):
        design = CircuitDesign(
            project_name="Test",
            project_description="Simple LED circuit",
            supply_voltage_v=5.0,
            components=[
                Component(
                    reference="R1",
                    name="Resistor",
                    value="220 Ohm",
                    voltage_rating_v=25.0,
                    evidence_status="user_supplied",
                    confidence=0.9,
                ),
                Component(
                    reference="D1",
                    name="LED",
                    value="Red LED",
                    voltage_rating_v=5.0,
                    evidence_status="user_supplied",
                    confidence=0.9,
                ),
            ],
            connections=[
                Connection(net_name="GND", pins=["R1.2", "D1.2"], confidence=0.95),
                Connection(net_name="VCC", pins=["R1.1", "D1.1"], confidence=0.95),
            ],
        )
        findings, _ = run_all_deterministic_rules(design)
        critical = [f for f in findings if f.severity == FindingSeverity.CRITICAL]
        assert critical == [], f"Unexpected CRITICAL findings: {[f.description for f in critical]}"


# ---------------------------------------------------------------------------
# Engine tests (no LLM)
# ---------------------------------------------------------------------------

class TestRedTeamEngine:
    def test_engine_returns_report_without_ai(self):
        design = _make_simple_design()
        engine = RedTeamEngine(settings=None, enable_ai_review=False)
        report = engine.review(design)
        assert isinstance(report, RedTeamReport)
        assert report.overall_status in ("PASS", "NEEDS_REVIEW", "FAIL")
        assert report.ai_review_performed is False

    def test_critical_voltage_rating_gives_fail_status(self):
        design = CircuitDesign(
            project_name="Test",
            project_description="Test",
            supply_voltage_v=12.0,
            components=[
                Component(
                    reference="C1",
                    name="Capacitor",
                    value="100uF",
                    voltage_rating_v=6.3,
                    evidence_status="unverified",
                )
            ],
            connections=[],
        )
        engine = RedTeamEngine(settings=None, enable_ai_review=False)
        report = engine.review(design)
        assert report.overall_status == "FAIL"
        assert report.critical_count >= 1


class _DummyClient:
    def __init__(self, response: str | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        if self.error:
            raise self.error
        assert "adversarial" in system_prompt
        assert "Circuit design data" in user_prompt
        return self.response or "[]"


class TestRedTeamAiBoundary:
    def test_ai_findings_are_suggestions_not_verified(self):
        client = _DummyClient(
            json.dumps(
                [
                    {
                        "category": "Component Protection",
                        "severity": "HIGH",
                        "component_reference": "D1",
                        "affected_pins": ["D1.1"],
                        "description": "Consider LED reverse-voltage stress during start-up.",
                        "engineering_reason": "The start-up transient is not modelled.",
                        "evidence": "No soft-start network is declared.",
                        "recommended_action": "Measure the start-up transient.",
                        "confidence": 0.55,
                    }
                ]
            )
        )
        engine = RedTeamEngine(settings=None, enable_ai_review=True)
        engine._client = client
        report = engine.review(_make_series_led_design())

        ai_findings = [
            finding
            for finding in report.findings
            if finding.verification_status == "AI_SUGGESTED"
        ]
        assert len(ai_findings) == 1
        assert ai_findings[0].is_confirmed_violation is False
        assert report.ai_review_attempted is True
        assert report.ai_review_performed is True
        assert report.ai_review_error is None
        # AI findings cannot produce a PASS.
        assert report.overall_status != "PASS"

    def test_ai_failure_does_not_crash_or_hide_deterministic_work(self):
        engine = RedTeamEngine(settings=None, enable_ai_review=True)
        engine._client = _DummyClient(error=RuntimeError("provider unavailable"))
        report = engine.review(_make_series_led_design())

        assert report.ai_review_attempted is True
        assert report.ai_review_performed is False
        assert "provider unavailable" in (report.ai_review_error or "")
        assert report.deterministic_checks_run
        assert report.overall_status in ("PASS", "NEEDS_REVIEW", "FAIL")
