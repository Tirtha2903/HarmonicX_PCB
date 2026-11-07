"""Structured data contracts for Circuit Red-Team."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


class FindingCategory(str, Enum):
    POWER_INTEGRITY = "Power Integrity"
    COMPONENT_PROTECTION = "Component Protection"
    CONNECTIVITY = "Connectivity"
    COMPONENT_COMPATIBILITY = "Component Compatibility"
    REQUIREMENT_CONSISTENCY = "Requirement Consistency"


VerificationStatus = Literal[
    "DETERMINISTIC",
    "AI_SUGGESTED",
    "INCOMPLETE_DATA",
    "VERIFIED_COMPONENT_DATA",
]

DataProvenance = Literal[
    "verified",
    "user_supplied",
    "unverified",
    "unknown",
    "not_applicable",
]


class RedTeamFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    rule_code: str = ""
    category: FindingCategory
    severity: FindingSeverity
    component_reference: str | None = None
    affected_pins: list[str] = Field(default_factory=list)
    description: str
    engineering_reason: str
    evidence: str
    recommended_action: str
    confidence: float = Field(ge=0, le=1)
    verification_status: VerificationStatus
    data_provenance: DataProvenance = "unknown"
    requires_measurement: bool = False

    def signature(self) -> str:
        """Stable identity used to detect new/resolved findings across versions."""
        text = re.sub(r"\s+", " ", self.description.strip().lower())
        return "|".join(
            [
                self.rule_code or "AI",
                self.category.value,
                self.component_reference or "-",
                text[:160],
            ]
        )

    @property
    def is_confirmed_violation(self) -> bool:
        """True only for deterministic findings against usable declared data."""
        return (
            self.verification_status == "DETERMINISTIC"
            and self.data_provenance in {"verified", "user_supplied", "not_applicable"}
        )


class RedTeamReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_status: Literal["PASS", "NEEDS_REVIEW", "FAIL"]
    findings: list[RedTeamFinding] = Field(default_factory=list)
    summary: str
    deterministic_checks_run: list[str] = Field(default_factory=list)
    ai_review_attempted: bool = False
    ai_review_performed: bool = False
    ai_review_error: str | None = None
    reviewed_at: str = Field(default_factory=utc_now_iso)
    design_fingerprint: str = ""
    electrical_safety_disclaimer: str = (
        "This review does not constitute electrical safety certification, "
        "simulation, ERC, DRC or manufacturing approval. Deterministic findings "
        "are calculated from declared component data only. AI-suggested findings "
        "require independent engineering verification. Never deploy a circuit "
        "based solely on this review."
    )
    review_scope: str = (
        "PASS means no finding was produced by the implemented checks for this "
        "declared design snapshot. It does not mean the circuit is electrically safe."
    )

    @property
    def critical_count(self) -> int:
        return self.count(FindingSeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return self.count(FindingSeverity.HIGH)

    @property
    def medium_count(self) -> int:
        return self.count(FindingSeverity.MEDIUM)

    @property
    def low_count(self) -> int:
        return self.count(FindingSeverity.LOW)

    @property
    def info_count(self) -> int:
        return self.count(FindingSeverity.INFORMATIONAL)

    def count(self, severity: FindingSeverity) -> int:
        return sum(1 for finding in self.findings if finding.severity == severity)

    def severity_counts(self) -> dict[str, int]:
        return {
            severity.value: self.count(severity)
            for severity in FindingSeverity
            if self.count(severity)
        }

    def findings_by_severity(self) -> dict[FindingSeverity, list[RedTeamFinding]]:
        return {
            severity: [f for f in self.findings if f.severity == severity]
            for severity in FindingSeverity
        }
