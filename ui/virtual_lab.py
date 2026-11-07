"""Virtual Lab Assistant tab."""

from __future__ import annotations

import logging

import streamlit as st

from config import Settings
from services.virtual_lab.generator import VirtualLabGenerator
from services.virtual_lab.report import build_lab_report
from ui.common import BASIS_LABELS, require_result

logger = logging.getLogger(__name__)


def _render_equipment(procedure) -> None:
    if not procedure.equipment:
        st.info("No equipment list generated.")
        return
    for item in procedure.equipment:
        badge = "🔴 Required" if item.required else "🔵 Optional"
        suffix = " (AI-suggested)" if item.is_ai_generated else ""
        with st.expander(f"{badge} — {item.name}{suffix}"):
            if item.specification:
                st.write(f"**Specification:** {item.specification}")
            st.write(f"**Purpose:** {item.reason}")


def _render_pre_power(procedure) -> None:
    if not procedure.pre_power_checks:
        st.info("No pre-power checks generated.")
        return
    for check in procedure.pre_power_checks:
        icon = "🔴" if check.critical else "🔵"
        suffix = " *(AI-suggested, unverified)*" if check.is_ai_generated else ""
        st.markdown(
            f"**{icon} Step {check.step_number}:** {check.description}{suffix}"
        )
        st.write(f"*How to verify:* {check.how_to_verify}")
        st.divider()


def _render_measurements(procedure) -> None:
    if not procedure.measurement_points:
        st.info("No measurement points generated.")
        return
    for point in procedure.measurement_points:
        suffix = " (AI-suggested, unverified)" if point.is_ai_generated else ""
        with st.expander(f"{point.point_id} — {point.description}{suffix}"):
            first, second = st.columns(2)
            first.write(f"**Location:** {point.measurement_location}")
            first.write(f"**Reference:** {point.reference_ground}")
            first.write(f"**Instrument:** {point.instrument}")
            first.write(f"**Mode:** {point.measurement_mode}")

            second.write(f"**Expected result:** {point.expected_result}")
            basis = BASIS_LABELS.get(
                point.expected_result_basis, point.expected_result_basis.upper()
            )
            if point.expected_result_basis == "calculated":
                second.success(f"✅ {basis}")
            elif point.expected_result_basis == "design_target":
                second.info(f"🎯 {basis}")
            else:
                second.warning(f"⚠️ {basis}")

            st.write(f"**Reason:** {point.reason}")
            st.write(f"**Abnormal reading indicates:** {point.abnormal_indication}")
            if point.safety_note:
                st.error(f"⚠️ Safety: {point.safety_note}")


def _render_sequence(procedure) -> None:
    if not procedure.test_sequence:
        st.info("No test sequence generated.")
        return
    for step in procedure.test_sequence:
        suffix = " *(AI-suggested)*" if step.is_ai_generated else ""
        st.markdown(f"**Step {step.step_number}: {step.title}**{suffix}")
        st.write(step.description)
        st.write(f"*Expected outcome:* {step.expected_outcome}")
        if step.safety_precaution:
            st.error(f"⚠️ {step.safety_precaution}")
        st.divider()


def _render_troubleshooting(procedure) -> None:
    if not procedure.troubleshooting:
        st.info("No troubleshooting guide generated.")
        return
    for entry in procedure.troubleshooting:
        suffix = " (AI-suggested)" if entry.is_ai_generated else ""
        with st.expander(f"🔍 {entry.symptom}{suffix}"):
            st.markdown("**Possible causes:**")
            for cause in entry.possible_causes:
                st.write(f"• {cause}")
            st.markdown("**Diagnostic actions:**")
            for action in entry.diagnostic_actions:
                st.write(f"→ {action}")


def _render_safety(procedure) -> None:
    for note in procedure.safety_notes:
        icon = {"WARNING": "🚨", "CAUTION": "⚠️", "INFO": "ℹ️"}.get(
            note.severity, "ℹ️"
        )
        renderer = {
            "WARNING": st.error,
            "CAUTION": st.warning,
            "INFO": st.info,
        }.get(note.severity, st.info)
        renderer(f"{icon} {note.note}")


def render_virtual_lab_tab(settings: Settings) -> None:
    st.subheader("🧪 Virtual Lab Assistant")
    st.caption(
        "Circuit-specific testing procedure for physical implementation. "
        "Deterministic checks and calculations are built first; AI additions are "
        "optional and always labelled unverified."
    )

    result = require_result()
    if result is None:
        return

    design = result["design"]
    red_team = result.get("red_team")

    generate_column, _ = st.columns([1, 3])
    if generate_column.button("Generate Lab Procedure", type="primary"):
        with st.spinner("Generating testing procedure..."):
            try:
                generator = VirtualLabGenerator(settings)
                procedure = generator.generate(design, red_team_report=red_team)
                st.session_state["lab_procedure"] = procedure
            except Exception as exc:
                st.error(f"Lab generation failed: {exc}")
                logger.exception("Virtual lab generation failed")

    procedure = st.session_state.get("lab_procedure")
    if procedure is None:
        st.info(
            "Click **Generate Lab Procedure** to create the testing guide for this circuit."
        )
        return

    st.markdown(f"### Testing Procedure: {procedure.circuit_name}")
    if procedure.supply_voltage_v:
        st.caption(f"Declared supply voltage: {procedure.supply_voltage_v:g} V")
    st.caption(
        f"Generation mode: {procedure.generation_mode} | "
        f"Design fingerprint: {procedure.design_fingerprint or 'unknown'}"
    )

    lab_tabs = st.tabs(
        [
            "🔧 Equipment",
            "✅ Pre-Power Checks",
            "📏 Measurement Points",
            "📋 Test Sequence",
            "🔍 Troubleshooting",
            "⚠️ Safety Notes",
        ]
    )
    with lab_tabs[0]:
        _render_equipment(procedure)
    with lab_tabs[1]:
        _render_pre_power(procedure)
    with lab_tabs[2]:
        _render_measurements(procedure)
    with lab_tabs[3]:
        _render_sequence(procedure)
    with lab_tabs[4]:
        _render_troubleshooting(procedure)
    with lab_tabs[5]:
        _render_safety(procedure)

    st.divider()
    st.caption(procedure.disclaimer)

    with st.expander("Generation notes"):
        for note in procedure.generation_notes:
            st.write(f"• {note}")

    report_text = build_lab_report(procedure, design)
    safe_name = design.project_name.replace(" ", "_")
    st.download_button(
        "📄 Download Lab Report (Markdown)",
        data=report_text.encode("utf-8"),
        file_name=f"lab_procedure_{safe_name}.md",
        mime="text/markdown",
    )
