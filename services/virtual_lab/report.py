"""Printable Virtual Lab report generation."""

from __future__ import annotations

from schemas.circuit import CircuitDesign
from services.virtual_lab.models import LabProcedure

_BASIS_LABEL = {
    "calculated": "CALCULATED from declared data",
    "design_target": "DESIGN TARGET (not simulated)",
    "requires_verification": "REQUIRES CALCULATION / DATASHEET",
    "ai_suggested": "AI-SUGGESTED — UNVERIFIED",
}


def build_lab_report(procedure: LabProcedure, design: CircuitDesign) -> str:
    lines: list[str] = [
        "# Virtual Lab Testing Procedure",
        "",
        f"**Circuit:** {design.project_name}",
        f"**Design fingerprint:** `{procedure.design_fingerprint or 'unknown'}`",
        f"**Generated (UTC):** {procedure.generated_at}",
        f"**Generation mode:** {procedure.generation_mode}",
        "**Supply voltage:** "
        + (f"{procedure.supply_voltage_v:g} V" if procedure.supply_voltage_v else "not declared"),
        "",
        "> " + procedure.disclaimer,
        "",
        "## Required components",
        "",
    ]
    if procedure.required_components:
        lines.extend(f"- {item}" for item in procedure.required_components)
    else:
        lines.append("No components declared in the structured design.")

    lines.extend(["", "## Equipment", ""])
    for item in procedure.equipment:
        badge = "REQUIRED" if item.required else "OPTIONAL"
        ai = " (AI-suggested)" if item.is_ai_generated else ""
        specification = f" — {item.specification}" if item.specification else ""
        lines.append(f"- **[{badge}]** {item.name}{ai}{specification}: {item.reason}")

    lines.extend(["", "## Safety notes", ""])
    for note in procedure.safety_notes:
        lines.append(f"- **{note.severity}:** {note.note}")

    lines.extend(["", "## Pre-power checklist", ""])
    for check in procedure.pre_power_checks:
        critical = " **(critical)**" if check.critical else ""
        ai = " *(AI-suggested)*" if check.is_ai_generated else ""
        lines.extend(
            [
                f"### {check.step_number}. {check.description}{critical}{ai}",
                "",
                check.how_to_verify,
                "",
            ]
        )

    lines.extend(["", "## Test sequence", ""])
    for step in procedure.test_sequence:
        lines.extend(
            [
                f"### Step {step.step_number}: {step.title}",
                "",
                step.description,
                "",
                f"- **Expected outcome:** {step.expected_outcome}",
            ]
        )
        if step.safety_precaution:
            lines.append(f"- **Safety:** {step.safety_precaution}")
        if step.is_ai_generated:
            lines.append("- **Source:** AI-suggested, unverified")
        lines.append("")

    lines.extend(["## Measurement points", ""])
    for point in procedure.measurement_points:
        basis = _BASIS_LABEL.get(
            point.expected_result_basis, point.expected_result_basis.upper()
        )
        ai = " *(AI-suggested, unverified)*" if point.is_ai_generated else ""
        lines.extend(
            [
                f"### {point.point_id} — {point.description}{ai}",
                "",
                f"- **Location:** {point.measurement_location}",
                f"- **Reference ground:** {point.reference_ground}",
                f"- **Instrument / mode:** {point.instrument}, {point.measurement_mode}",
                f"- **Expected result:** {point.expected_result}",
                f"- **Value basis:** {basis}",
                f"- **Reason:** {point.reason}",
                f"- **Abnormal reading indicates:** {point.abnormal_indication}",
            ]
        )
        if point.safety_note:
            lines.append(f"- **Safety:** {point.safety_note}")
        lines.append("")

    lines.extend(["## Troubleshooting", ""])
    for entry in procedure.troubleshooting:
        ai = " *(AI-suggested)*" if entry.is_ai_generated else ""
        lines.extend(
            [
                f"### {entry.symptom}{ai}",
                "",
                "**Possible causes**",
                *[f"- {cause}" for cause in entry.possible_causes],
                "",
                "**Diagnostic actions**",
                *[f"- {action}" for action in entry.diagnostic_actions],
                "",
            ]
        )

    lines.extend(["## Generation notes", ""])
    lines.extend(f"- {note}" for note in procedure.generation_notes)
    lines.extend(
        [
            "",
            "---",
            "",
            "This report does not claim that the circuit was simulated, measured or "
            "electrically certified. Record actual measured values separately and retain "
            "the instrument settings used.",
            "",
        ]
    )
    return "\n".join(lines)
