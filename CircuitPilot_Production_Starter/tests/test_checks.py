from electronics.checks import run_structural_checks
from schemas.circuit import CircuitDesign


def test_structural_checks_are_not_erc():
    design = CircuitDesign(
        project_name="Test",
        project_description="Test",
        supply_voltage_v=5,
        components=[],
        connections=[],
        missing_information=["Current requirement unknown"],
        requires_confirmation=True,
    )
    report = run_structural_checks(design)
    assert report["electrical_erc_performed"] is False
    assert report["pcb_drc_performed"] is False
    assert report["status"] == "needs_review"
