"""Circuit Red-Team tab."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from ui.common import (
    SEVERITY_ICONS,
    SEVERITY_ORDER,
    STATUS_ICONS,
    render_artifact_downloads,
    require_result,
    short_timestamp,
)

_VERIFICATION_MESSAGES = {
    "DETERMINISTIC": (
        "success",
        "🔬 Deterministically detected from declared component data",
    ),
    "VERIFIED_COMPONENT_DATA": (
        "success",
        "🔬 Confirmed against verified component data",
    ),
    "AI_SUGGESTED": (
        "warning",
        "🤖 AI-suggested finding — requires independent engineering verification",
    ),
    "INCOMPLETE_DATA": (
        "info",
        "⚠️ Based on incomplete information — verify when data is available",
    ),
}


def _render_finding(finding) -> None:
    label_parts = []
    if finding.component_reference:
        label_parts.append(f"**{finding.component_reference}**")
    label_parts.append(finding.description)
    with st.expander(" — ".join(label_parts)):
        first, second = st.columns(2)
        first.markdown(f"**Category:** {finding.category.value}")
        second.markdown(f"**Severity:** {finding.severity.value}")

        level, message = _VERIFICATION_MESSAGES.get(
            finding.verification_status,
            ("info", f"Verification status: {finding.verification_status}"),
        )
        getattr(st, level)(message)

        st.markdown("**Engineering reason**")
        st.write(finding.engineering_reason)

        st.markdown("**Evidence**")
        st.write(finding.evidence)

        if finding.affected_pins:
            st.markdown("**Affected pins**")
            st.write(", ".join(finding.affected_pins))

        st.markdown("**Recommended action**")
        st.success(finding.recommended_action)

        st.caption(
            f"Finding ID: {finding.finding_id} | "
            f"Confidence: {finding.confidence:.0%} | "
            f"Provenance: {finding.data_provenance}"
        )


def render_red_team_tab() -> None:
    st.subheader("⚔️ Circuit Red-Team Review")
    st.caption(
        "Adversarial review of the circuit design. Findings are deterministic where "
        "sufficient data is available. AI-suggested findings require independent "
        "verification. A PASS is not a safety certification."
    )

    result = require_result()
    if result is None:
        return

    red_team = result.get("red_team")
    if red_team is None:
        st.warning("Red-Team review data not available. Re-run the circuit analysis.")
        return

    st.markdown(
        f"### {STATUS_ICONS.get(red_team.overall_status, '❓')} Overall Status: "
        f"**{red_team.overall_status}**"
    )
    st.write(red_team.summary)
    st.caption(f"Reviewed at: {short_timestamp(red_team.reviewed_at)}")

    if red_team.findings:
        columns = st.columns(5)
        columns[0].metric("🚨 CRITICAL", red_team.critical_count)
        columns[1].metric("🔴 HIGH", red_team.high_count)
        columns[2].metric("🟡 MEDIUM", red_team.medium_count)
        columns[3].metric("🔵 LOW", red_team.low_count)
        columns[4].metric("ℹ️ INFO", red_team.info_count)

    st.info(red_team.electrical_safety_disclaimer)
    st.divider()

    if not red_team.findings:
        st.success(
            "No finding was produced by the implemented checks. Independent "
            "engineering verification is still required."
        )
    else:
        for severity in SEVERITY_ORDER:
            findings = [
                finding
                for finding in red_team.findings
                if finding.severity == severity
            ]
            if not findings:
                continue
            st.markdown(
                f"#### {SEVERITY_ICONS[severity]} {severity.value} ({len(findings)})"
            )
            for finding in findings:
                _render_finding(finding)

    with st.expander("Deterministic checks performed"):
        for check in red_team.deterministic_checks_run:
            st.write(f"• {check}")

    st.markdown("**AI contextual review**")
    st.write(f"Attempted: {red_team.ai_review_attempted}")
    st.write(f"Completed: {red_team.ai_review_performed}")
    if red_team.ai_review_error:
        st.warning(f"AI contextual review error: {red_team.ai_review_error}")
    st.caption(
        "AI-suggested items are never upgraded to verified findings. Their verification "
        "status remains AI_SUGGESTED."
    )

    artifact_dir = Path(result["artifact_dir"])
    st.subheader("Review artifacts")
    render_artifact_downloads(artifact_dir, include_review=True)
