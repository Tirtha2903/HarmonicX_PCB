from __future__ import annotations

from collections import Counter

from schemas.circuit import CircuitDesign


def run_structural_checks(design: CircuitDesign) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    refs = [component.reference for component in design.components]
    duplicates = [ref for ref, count in Counter(refs).items() if count > 1]
    if duplicates:
        errors.append("Duplicate component references: " + ", ".join(duplicates))

    known = set(refs)
    for connection in design.connections:
        for pin in connection.pins:
            ref = pin.split(".", 1)[0]
            if ref not in known:
                errors.append(
                    f"Net {connection.net_name} references unknown component {ref}."
                )

    if not design.components:
        warnings.append("No components were identified.")
    if not design.connections:
        warnings.append("No explicit electrical connections were identified.")
    if design.missing_information:
        warnings.extend(
            "Missing information: " + item for item in design.missing_information
        )
    if any(c.evidence_status == "unverified" for c in design.components):
        warnings.append("Some component selections have not been verified against datasheets.")
    if any(c.confidence < 0.85 for c in design.connections):
        warnings.append("One or more connections have confidence below 0.85.")

    warnings.append(
        "Structural checks are not electrical ERC, PCB DRC, simulation or safety certification."
    )

    return {
        "status": "failed" if errors else (
            "needs_review" if design.requires_confirmation or warnings else "passed"
        ),
        "errors": errors,
        "warnings": warnings,
        "checks_performed": [
            "Pydantic schema validation",
            "Unique component reference check",
            "Connection reference integrity check",
            "Uncertainty and missing-information review",
        ],
        "electrical_erc_performed": False,
        "pcb_drc_performed": False,
        "simulation_performed": False,
    }
