"""Human-readable Red-Team report export."""

from __future__ import annotations

from electronics.red_team.models import RedTeamReport
from electronics.red_team.severity import SEVERITY_ORDER
from schemas.circuit import CircuitDesign


def report_to_markdown(report: RedTeamReport, design: CircuitDesign) -> str:
    lines: list[str] = [
        "# Circuit Red-Team Review",
        "",
        f"- **Circuit:** {design.project_name}",
        f"- **Design fingerprint:** `{report.design_fingerprint or 'unknown'}`",
        f"- **Reviewed at (UTC):** {report.reviewed_at}",
        f"- **Overall review status:** **{report.overall_status}**",
        f"- **Findings:** {len(report.findings)}",
        "",
        "> " + report.electrical_safety_disclaimer,
        ">",
        "> " + report.review_scope,
        "",
        "## Summary",
        "",
        report.summary,
        "",
        "## Severity counts",
        "",
        "| Severity | Count |",
        "|---|---:|",
    ]
    for severity in SEVERITY_ORDER:
        lines.append(f"| {severity.value} | {report.count(severity)} |")

    lines.extend(["", "## Findings", ""])
    if not report.findings:
        lines.append(
            "No finding was produced by the implemented checks. This is not an "
            "electrical-safety certification."
        )
    for severity in SEVERITY_ORDER:
        findings = [f for f in report.findings if f.severity == severity]
        if not findings:
            continue
        lines.extend([f"### {severity.value}", ""])
        for finding in findings:
            component = (
                f" `{finding.component_reference}`" if finding.component_reference else ""
            )
            lines.extend(
                [
                    f"#### {finding.finding_id}{component} — {finding.description}",
                    "",
                    f"- **Category:** {finding.category.value}",
                    f"- **Verification:** {finding.verification_status}",
                    f"- **Data provenance:** {finding.data_provenance}",
                    f"- **Confidence:** {finding.confidence:.0%}",
                    f"- **Rule:** {finding.rule_code or 'AI contextual review'}",
                    "- **Affected pins:** "
                    + (", ".join(finding.affected_pins) if finding.affected_pins else "none declared"),
                    "",
                    "**Why it matters**",
                    "",
                    finding.engineering_reason,
                    "",
                    "**Evidence**",
                    "",
                    finding.evidence,
                    "",
                    "**Recommended action**",
                    "",
                    finding.recommended_action,
                    "",
                ]
            )

    lines.extend(
        [
            "## Deterministic checks performed",
            "",
            *[f"- {check}" for check in report.deterministic_checks_run],
            "",
            "## AI contextual review",
            "",
            f"- Attempted: {report.ai_review_attempted}",
            f"- Completed: {report.ai_review_performed}",
            f"- Error: {report.ai_review_error or 'none'}",
            "- AI-suggested findings are not verified findings and must be checked independently.",
            "",
        ]
    )
    return "\n".join(lines)
