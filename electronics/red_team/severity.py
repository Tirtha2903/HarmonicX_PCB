"""Severity ordering and report-status helpers for Circuit Red-Team."""

from __future__ import annotations

from electronics.red_team.models import (
    FindingSeverity,
    RedTeamFinding,
    RedTeamReport,
)
from schemas.circuit import CircuitDesign

SEVERITY_RANK: dict[FindingSeverity, int] = {
    FindingSeverity.CRITICAL: 5,
    FindingSeverity.HIGH: 4,
    FindingSeverity.MEDIUM: 3,
    FindingSeverity.LOW: 2,
    FindingSeverity.INFORMATIONAL: 1,
}

SEVERITY_ORDER: list[FindingSeverity] = [
    FindingSeverity.CRITICAL,
    FindingSeverity.HIGH,
    FindingSeverity.MEDIUM,
    FindingSeverity.LOW,
    FindingSeverity.INFORMATIONAL,
]


def rank(severity: FindingSeverity) -> int:
    return SEVERITY_RANK[severity]


def highest_severity(findings: list[RedTeamFinding]) -> FindingSeverity | None:
    if not findings:
        return None
    return max(findings, key=lambda finding: rank(finding.severity)).severity


def sort_findings(findings: list[RedTeamFinding]) -> list[RedTeamFinding]:
    return sorted(
        findings,
        key=lambda finding: (
            -rank(finding.severity),
            finding.component_reference or "",
            finding.rule_code,
            finding.finding_id,
        ),
    )


def severity_counts(findings: list[RedTeamFinding]) -> dict[str, int]:
    return {
        severity.value: sum(1 for item in findings if item.severity == severity)
        for severity in SEVERITY_ORDER
        if any(item.severity == severity for item in findings)
    }


def status_for(
    findings: list[RedTeamFinding],
    design: CircuitDesign | None = None,
) -> str:
    """Return FAIL / NEEDS_REVIEW / PASS.

    Only CRITICAL deterministic findings produce FAIL. Any other finding, or a
    design flagged as requiring confirmation, produces NEEDS_REVIEW. PASS is a
    finding-free review, never a safety certification.
    """
    if any(
        finding.severity == FindingSeverity.CRITICAL
        and finding.verification_status == "DETERMINISTIC"
        for finding in findings
    ):
        return "FAIL"
    if findings:
        return "NEEDS_REVIEW"
    if design is not None and design.requires_confirmation:
        return "NEEDS_REVIEW"
    return "PASS"


def build_summary(report: RedTeamReport, deterministic_count: int) -> str:
    if not report.findings:
        return (
            "No finding was produced by the implemented deterministic checks. "
            "This is not an electrical-safety certification; independent "
            "engineering verification is still required."
        )
    counts = ", ".join(
        f"{value} {name}" for name, value in report.severity_counts().items()
    )
    base = (
        f"Red-Team review produced {len(report.findings)} finding(s): {counts}. "
        f"{deterministic_count} deterministic, "
        f"{len(report.findings) - deterministic_count} AI-suggested."
    )
    if report.ai_review_error:
        base += f" AI contextual review was unavailable: {report.ai_review_error}"
    return base
