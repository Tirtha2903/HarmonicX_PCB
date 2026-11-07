"""Deterministic tests for engineering value parsing and calculations."""

from __future__ import annotations

import pytest

from electronics.calculations import (
    component_capacitance,
    component_resistance,
    direct_supply_current,
    direct_supply_power,
    find_voltage_dividers,
    led_worst_case_current,
    led_worst_case_resistor_power,
)
from electronics.values import (
    capacitance_label,
    format_si,
    parse_capacitance,
    parse_resistance,
    resistance_label,
)
from schemas.circuit import CircuitDesign, Component, Connection


def _resistor_divider_design(supply: float = 5.0) -> CircuitDesign:
    return CircuitDesign(
        project_name="Divider",
        project_description="Divider under test",
        supply_voltage_v=supply,
        components=[
            Component(reference="J1", name="Power connector"),
            Component(reference="R1", name="Resistor", value="10k"),
            Component(reference="R2", name="Resistor", value="10k"),
        ],
        connections=[
            Connection(net_name="VCC", pins=["J1.1", "R1.1"]),
            Connection(net_name="MID", pins=["R1.2", "R2.1"]),
            Connection(net_name="GND", pins=["R2.2", "J1.2"]),
        ],
    )


class TestParseHelpers:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("220", 220.0),
            ("220R", 220.0),
            ("1k", 1000.0),
            ("4k7", 4700.0),
            ("1M", 1_000_000.0),
            ("10 ohm", 10.0),
        ],
    )
    def test_parse_resistance(self, text, expected):
        assert parse_resistance(text) == expected

    @pytest.mark.parametrize("text", [None, "", "red", "10V"])
    def test_parse_resistance_rejects_unknown(self, text):
        assert parse_resistance(text) is None

    def test_parse_capacitance(self):
        assert parse_capacitance("100nF") == pytest.approx(100e-9)
        assert parse_capacitance("10uF") == pytest.approx(10e-6)
        assert parse_capacitance("1mF") == pytest.approx(1e-3)

    def test_parse_capacitance_rejects_resistance_units(self):
        assert parse_capacitance("10k") is None

    def test_format_si(self):
        assert format_si(4700, "Ω") == "4.7 kΩ"
        assert format_si(None, "V") == "unknown"
        assert resistance_label(1000) == "1 kΩ"
        assert capacitance_label(100e-9) == "100 nF"


class TestDirectSupplyCalculations:
    def test_power_and_current_for_resistor_across_supply(self):
        design = _resistor_divider_design()
        resistor = design.components[1]
        # The divider resistors are not directly across the supply.
        assert direct_supply_power(design, resistor) is None
        assert direct_supply_current(design, resistor) is None

        direct = CircuitDesign(
            project_name="Direct",
            project_description="Load across supply",
            supply_voltage_v=5.0,
            components=[
                Component(reference="J1", name="Power connector"),
                Component(reference="R1", name="Resistor", value="1k"),
            ],
            connections=[
                Connection(net_name="VCC", pins=["J1.1", "R1.1"]),
                Connection(net_name="GND", pins=["J1.2", "R1.2"]),
            ],
        )
        assert direct_supply_power(direct, direct.components[1]) == pytest.approx(0.025)
        assert direct_supply_current(direct, direct.components[1]) == pytest.approx(
            0.005
        )

    def test_missing_supply_or_value_returns_none(self):
        design = _resistor_divider_design(supply=5.0)
        no_value = Component(reference="R9", name="Resistor")
        assert direct_supply_power(design, no_value) is None
        no_supply = _resistor_divider_design().model_copy(
            update={"supply_voltage_v": None}
        )
        assert direct_supply_current(no_supply, no_supply.components[1]) is None

    def test_component_helpers(self):
        resistor = Component(reference="R1", name="Resistor", value="2k2")
        capacitor = Component(reference="C1", name="Capacitor", value="100nF")
        assert component_resistance(resistor) == pytest.approx(2200)
        assert component_resistance(capacitor) is None
        assert component_capacitance(capacitor) == pytest.approx(100e-9)
        assert component_capacitance(resistor) is None


class TestVoltageDivider:
    def test_unloaded_divider_is_calculated_from_declared_values(self):
        results = find_voltage_dividers(_resistor_divider_design())
        assert len(results) == 1
        divider = results[0]
        assert {divider.top_reference, divider.bottom_reference} == {"R1", "R2"}
        assert divider.output_net == "MID"
        assert divider.output_voltage_v == pytest.approx(2.5)
        assert divider.quiescent_current_a == pytest.approx(0.00025)

    def test_no_supply_voltage_means_no_calculation(self):
        design = _resistor_divider_design().model_copy(
            update={"supply_voltage_v": None}
        )
        assert find_voltage_dividers(design) == []

    def test_no_ground_means_no_calculation(self):
        design = _resistor_divider_design()
        ungrounded = design.model_copy(
            update={
                "connections": [
                    Connection(net_name="VCC", pins=["J1.1", "R1.1"]),
                    Connection(net_name="MID", pins=["R1.2", "R2.1"]),
                    Connection(net_name="RETURN", pins=["R2.2", "J1.2"]),
                ]
            }
        )
        assert find_voltage_dividers(ungrounded) == []

    def test_single_resistor_is_not_a_divider(self):
        design = CircuitDesign(
            project_name="Single",
            project_description="One resistor",
            supply_voltage_v=5.0,
            components=[
                Component(reference="J1", name="Power connector"),
                Component(reference="R1", name="Resistor", value="1k"),
            ],
            connections=[
                Connection(net_name="VCC", pins=["J1.1", "R1.1"]),
                Connection(net_name="GND", pins=["J1.2", "R1.2"]),
            ],
        )
        assert find_voltage_dividers(design) == []


class TestLedWorstCase:
    def test_worst_case_current_and_power(self):
        design = _resistor_divider_design()
        resistor = Component(reference="R1", name="Resistor", value="220")
        assert led_worst_case_current(design, resistor) == pytest.approx(5.0 / 220)
        assert led_worst_case_resistor_power(design, resistor) == pytest.approx(
            25.0 / 220
        )

    def test_unknown_value_or_supply_returns_none(self):
        design = _resistor_divider_design()
        unvalued = Component(reference="R1", name="Resistor")
        assert led_worst_case_current(design, unvalued) is None
        assert led_worst_case_resistor_power(design, unvalued) is None
        no_supply = design.model_copy(update={"supply_voltage_v": None})
        valued = Component(reference="R1", name="Resistor", value="220")
        assert led_worst_case_current(no_supply, valued) is None
