"""Tests for canonical design fingerprints."""

from __future__ import annotations

import re

from schemas.circuit import CircuitDesign, Component, Connection
from schemas.fingerprint import design_fingerprint


def _design(**overrides) -> CircuitDesign:
    data = {
        "project_name": "Fingerprint circuit",
        "project_description": "Content identity test",
        "supply_voltage_v": 5.0,
        "components": [
            Component(
                reference="R1",
                name="Resistor",
                value="220 Ohm",
                evidence_status="verified",
                confidence=0.9,
            ),
            Component(
                reference="D1",
                name="LED",
                value="Red LED",
                evidence_status="verified",
                confidence=0.9,
            ),
        ],
        "connections": [
            Connection(net_name="VCC", pins=["R1.1", "D1.1"], confidence=0.9),
            Connection(net_name="GND", pins=["R1.2", "D1.2"], confidence=0.9),
        ],
    }
    data.update(overrides)
    return CircuitDesign(**data)


class TestDesignFingerprint:
    def test_is_16_hex_characters(self):
        fingerprint = design_fingerprint(_design())
        assert re.fullmatch(r"[0-9a-f]{16}", fingerprint)

    def test_is_stable_for_identical_content(self):
        assert design_fingerprint(_design()) == design_fingerprint(_design())

    def test_changes_when_value_changes(self):
        changed = _design(
            components=[
                Component(
                    reference="R1",
                    name="Resistor",
                    value="470 Ohm",
                    evidence_status="verified",
                    confidence=0.9,
                ),
                Component(
                    reference="D1",
                    name="LED",
                    value="Red LED",
                    evidence_status="verified",
                    confidence=0.9,
                ),
            ]
        )
        assert design_fingerprint(_design()) != design_fingerprint(changed)

    def test_changes_when_connection_changes(self):
        changed = _design(
            connections=[
                Connection(net_name="VCC", pins=["R1.1", "D1.1"], confidence=0.9),
                Connection(net_name="RETURN", pins=["R1.2", "D1.2"], confidence=0.9),
            ]
        )
        assert design_fingerprint(_design()) != design_fingerprint(changed)

    def test_ignores_confidence_and_confirmation_fields(self):
        base = _design()
        rerun = _design(
            components=[
                Component(
                    reference="R1",
                    name="Resistor",
                    value="220 Ohm",
                    evidence_status="verified",
                    confidence=0.2,
                ),
                Component(
                    reference="D1",
                    name="LED",
                    value="Red LED",
                    evidence_status="verified",
                    confidence=0.1,
                ),
            ],
            connections=[
                Connection(net_name="VCC", pins=["R1.1", "D1.1"], confidence=0.1),
                Connection(net_name="GND", pins=["R1.2", "D1.2"], confidence=0.2),
            ],
            requires_confirmation=True,
            overall_confidence=0.05,
        )
        assert design_fingerprint(base) == design_fingerprint(rerun)

    def test_changes_when_evidence_status_changes(self):
        unverified = _design(
            components=[
                Component(
                    reference="R1",
                    name="Resistor",
                    value="220 Ohm",
                    evidence_status="unverified",
                ),
                Component(reference="D1", name="LED", value="Red LED"),
            ]
        )
        assert design_fingerprint(_design()) != design_fingerprint(unverified)
