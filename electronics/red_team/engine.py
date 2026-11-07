"""Circuit Red-Team engine.

Pipeline: deterministic rules first, then an optional, clearly-labelled AI
contextual review. The engine never upgrades an AI suggestion to a verified
finding and never declares a circuit electrically safe.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from config import Settings
from electronics.red_team.models import (
    FindingCategory,
    FindingSeverity,
    RedTeamFinding,
    RedTeamReport,
    utc_now_iso,
)
from electronics.red_team.rules import run_all_deterministic_rules
from electronics.red_team.severity import (
    build_summary,
    sort_findings,
    status_for,
)
from schemas.circuit import CircuitDesign
from schemas.fingerprint import design_fingerprint

logger = logging.getLogger(__name__)

_AI_REVIEW_SYSTEM_PROMPT = """\
You are an adversarial electronics design reviewer. You receive a structured
circuit design and findings already produced by deterministic checks.

Your task is to identify ADDITIONAL potential concerns that require engineering
investigation. You are not the authority on whether the circuit is safe.

RULES:
1. Do NOT repeat deterministic findings.
2. Do NOT declare any circuit safe, compliant, certified or simulated.
3. Only raise concerns relevant to this specific circuit and its declared data.
4. Do NOT invent datasheet values, component ratings, pinouts or measurements.
5. If a concern depends on unknown data, say so in evidence and lower confidence.
6. Return a raw JSON array. No markdown fences, no commentary.
7. Each item must contain exactly these keys:
   category (one of "Power Integrity", "Component Protection", "Connectivity",
   "Component Compatibility", "Requirement Consistency"),
   severity (CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL),
   component_reference (string or null),
   affected_pins (array of strings),
   description (one sentence),
   engineering_reason (why it matters),
   evidence (what in the supplied data suggests it),
   recommended_action (specific action),
   confidence (0.0 to 1.0)
8. Return [] if you have no additional concern. Do not manufacture findings.
"""


def _ai_fid(description: str) -> str:
    digest = hashlib.sha1(description.strip().lower().encode("utf-8")).hexdigest()[:6]
    return f"RT-AI-{digest.upper()}"


def _coerce_category(value: Any) -> FindingCategory:
    text = str(value).strip().lower()
    for category in FindingCategory:
        if category.value.lower() == text or category.name.lower() == text:
            return category
    return FindingCategory.REQUIREMENT_CONSISTENCY


def _coerce_severity(value: Any) -> FindingSeverity:
    text = str(value).strip().upper()
    try:
        return FindingSeverity(text)
    except ValueError:
        return FindingSeverity.INFORMATIONAL


class RedTeamEngine:
    """Runs the Red-Team review pipeline on a CircuitDesign."""

    def __init__(
        self,
        settings: Settings | None = None,
        enable_ai_review: bool | None = None,
    ):
        self.settings = settings
        if enable_ai_review is None:
            enable_ai_review = bool(settings and settings.enable_ai_red_team)
        self.enable_ai_review = enable_ai_review
        self._client = None

    def _get_client(self):
        if self._client is None:
            if self.settings is None:
                raise RuntimeError("No provider settings are available.")
            from services.llm_client import OpenAICompatibleClient

            self._client = OpenAICompatibleClient(self.settings)
        return self._client

    def _ai_review(
        self,
        design: CircuitDesign,
        deterministic_findings: list[RedTeamFinding],
    ) -> tuple[list[RedTeamFinding], str | None]:
        """Return AI-suggested findings and an optional error message."""
        try:
            client = self._get_client()
            design_summary = {
                "project_name": design.project_name,
                "project_description": design.project_description,
                "supply_voltage_v": design.supply_voltage_v,
                "target_frequency_hz": design.target_frequency_hz,
                "components": [
                    {
                        "reference": component.reference,
                        "name": component.name,
                        "value": component.value,
                        "voltage_rating_v": component.voltage_rating_v,
                        "current_rating_a": component.current_rating_a,
                        "power_rating_w": component.power_rating_w,
                        "evidence_status": component.evidence_status,
                    }
                    for component in design.components
                ],
                "connections": [
                    {"net_name": connection.net_name, "pins": connection.pins}
                    for connection in design.connections
                ],
                "missing_information": design.missing_information,
                "assumptions": design.assumptions,
            }
            deterministic_summary = [
                {
                    "finding_id": finding.finding_id,
                    "category": finding.category.value,
                    "severity": finding.severity.value,
                    "description": finding.description,
                }
                for finding in deterministic_findings
            ]
            user_prompt = (
                "Circuit design data:\n"
                + json.dumps(design_summary, indent=2)
                + "\n\nAlready-identified deterministic findings:\n"
                + json.dumps(deterministic_summary, indent=2)
                + "\n\nIdentify additional concerns not already listed."
            )
            response = client.complete(_AI_REVIEW_SYSTEM_PROMPT, user_prompt)
            text = response.strip()
            fence = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n\s*```", text)
            if fence:
                text = fence.group(1).strip()
            start, end = text.find("["), text.rfind("]")
            if start < 0 or end < start:
                raise ValueError("AI review did not return a JSON array.")
            raw_findings = json.loads(text[start : end + 1])
            if not isinstance(raw_findings, list):
                raise ValueError("AI review JSON was not an array.")

            ai_findings: list[RedTeamFinding] = []
            for item in raw_findings:
                if not isinstance(item, dict):
                    continue
                description = str(item.get("description", "")).strip()
                if not description:
                    continue
                try:
                    confidence = float(item.get("confidence", 0.5))
                except (TypeError, ValueError):
                    confidence = 0.5
                try:
                    finding = RedTeamFinding(
                        finding_id=_ai_fid(description),
                        rule_code="AI-REVIEW",
                        category=_coerce_category(item.get("category")),
                        severity=_coerce_severity(item.get("severity")),
                        component_reference=(
                            str(item["component_reference"]).strip()
                            if item.get("component_reference")
                            else None
                        ),
                        affected_pins=[
                            str(pin) for pin in item.get("affected_pins", []) or []
                        ][:20],
                        description=description[:500],
                        engineering_reason=str(
                            item.get("engineering_reason", "")
                        )[:1200],
                        evidence=str(item.get("evidence", "AI contextual review"))[:600],
                        recommended_action=str(item.get("recommended_action", ""))[:600],
                        confidence=max(0.0, min(1.0, confidence)),
                        verification_status="AI_SUGGESTED",
                        data_provenance="unverified",
                        requires_measurement=True,
                    )
                    ai_findings.append(finding)
                except Exception as exc:
                    logger.debug("Skipping malformed AI finding: %s", exc)
            return ai_findings, None
        except Exception as exc:
            logger.warning("AI red-team review failed: %s", exc)
            return [], str(exc)[:300]

    def review(self, design: CircuitDesign) -> RedTeamReport:
        """Run the full Red-Team review and return a structured report."""
        deterministic_findings, checks_run = run_all_deterministic_rules(design)

        ai_findings: list[RedTeamFinding] = []
        ai_attempted = False
        ai_performed = False
        ai_error: str | None = None
        if self.enable_ai_review:
            ai_attempted = True
            ai_findings, ai_error = self._ai_review(design, deterministic_findings)
            ai_performed = ai_error is None

        all_findings = sort_findings(deterministic_findings + ai_findings)
        report = RedTeamReport(
            overall_status="NEEDS_REVIEW",  # replaced below after counts are known
            findings=all_findings,
            summary="",
            deterministic_checks_run=checks_run,
            ai_review_attempted=ai_attempted,
            ai_review_performed=ai_performed,
            ai_review_error=ai_error,
            reviewed_at=utc_now_iso(),
            design_fingerprint=design_fingerprint(design),
        )
        report.overall_status = status_for(all_findings, design)
        report.summary = build_summary(report, len(deterministic_findings))
        return report
