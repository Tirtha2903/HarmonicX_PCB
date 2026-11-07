import pytest
from pydantic import ValidationError

from schemas.circuit import CircuitDesign, Component, Connection


def minimal_design(**overrides):
    data = {
        "project_name": "Test circuit",
        "project_description": "Unit test circuit",
        "supply_voltage_v": 5,
        "components": [
            {"reference": "R1", "name": "resistor", "value": "1k"}
        ],
        "connections": [
            {
                "net_name": "NET1",
                "pins": ["R1.1", "R1.2"],
                "confidence": 0.9,
            }
        ],
        "missing_information": [],
        "assumptions": [],
        "requires_confirmation": False,
        "design_notes": [],
        "overall_confidence": 0.9,
    }
    data.update(overrides)
    return CircuitDesign.model_validate(data)


def test_valid_design_parses():
    design = minimal_design()
    assert design.project_name == "Test circuit"


def test_duplicate_reference_rejected():
    with pytest.raises(ValidationError):
        minimal_design(components=[
            {"reference": "R1", "name": "resistor", "value": "1k"},
            {"reference": "R1", "name": "resistor", "value": "2k"},
        ])


def test_unknown_component_reference_rejected():
    with pytest.raises(ValidationError):
        minimal_design(connections=[
            {"net_name": "NET1", "pins": ["R1.1", "U9.2"]}
        ])


def test_missing_information_forces_confirmation():
    design = minimal_design(missing_information=["Supply current is unknown"])
    assert design.requires_confirmation is True


def test_bad_pin_format_rejected():
    with pytest.raises(ValidationError):
        Connection(net_name="N1", pins=["R1-1", "R1.2"])


def test_single_pin_connection_rejected():
    """A connection with only one pin must be rejected (minimum is 2)."""
    with pytest.raises(ValidationError):
        Connection(net_name="N1", pins=["R1.1"])
