"""Circuit DNA tab."""

from __future__ import annotations

import json
import logging

import streamlit as st

from config import Settings
from services.dna.storage import DNAStorage
from ui.common import require_result, short_timestamp

logger = logging.getLogger(__name__)


def _render_save_panel(settings: Settings, result: dict) -> None:
    storage = DNAStorage(settings.db_path)
    design = result["design"]
    checks = result["checks"]
    red_team = result.get("red_team")

    st.markdown("### Save current design to Circuit DNA")
    id_column, notes_column = st.columns([1, 2])
    with id_column:
        existing_id = st.text_input(
            "Existing Circuit ID (leave blank to create new)",
            placeholder="CP-XXXX-0001",
            key="dna_circuit_id_input",
        )
    with notes_column:
        version_notes = st.text_area(
            "Version notes",
            placeholder="What changed in this version?",
            height=80,
            key="dna_version_notes",
        )

    if st.button("💾 Save to DNA", type="primary"):
        try:
            saved_id, saved_version = storage.save_version(
                design,
                checks=checks,
                red_team=red_team,
                notes=version_notes,
                circuit_id=existing_id.strip() or None,
            )
            st.success(f"Saved as **{saved_id}** version **{saved_version}**")
            st.session_state["dna_last_saved_id"] = saved_id
        except (ValueError, TypeError) as exc:
            st.error(f"Save failed: {exc}")
        except Exception as exc:
            st.error(f"Save failed: {exc}")
            logger.exception("DNA save failed")


def _render_version(version, circuit_id: str) -> None:
    icon = "🆕" if version.version == "1.0" else "🔄"
    notes = f" — {version.notes}" if version.notes else ""
    with st.expander(
        f"{icon} Version {version.version} — "
        f"{short_timestamp(version.created_at)}{notes}"
    ):
        change = version.change_from_previous
        if change and change.has_changes:
            st.markdown("**Changes from previous version:**")
            st.code(change.human_readable, language=None)
            if change.validation_invalidated:
                st.warning(
                    "Validation invalidated. Re-run structural checks, Red-Team and "
                    "the Virtual Lab procedure for this version."
                )
            elif change.previous_review_still_applicable:
                st.info("The design content is unchanged; the previous review still applies.")
            if change.findings_added or change.findings_resolved:
                first, second = st.columns(2)
                first.metric("New findings", change.findings_added)
                second.metric("Resolved findings", change.findings_resolved)
            if change.checks_invalidated:
                st.warning(
                    "Checks that should be re-run:\n"
                    + "\n".join(f"• {item}" for item in change.checks_invalidated)
                )
        elif version.version == "1.0":
            st.info("Initial version — no previous version to compare.")
        else:
            st.success("No changes detected from the previous version.")

        component_count = len(version.design_snapshot.get("components", []))
        connection_count = len(version.design_snapshot.get("connections", []))
        supply = version.design_snapshot.get("supply_voltage_v", "N/A")
        st.write(
            f"Components: {component_count} | Connections: {connection_count} | "
            f"Declared supply: {supply} V"
        )
        st.caption(f"Design fingerprint: {version.design_hash or 'unknown'}")

        if version.red_team_snapshot:
            status = version.red_team_snapshot.get("overall_status", "unknown")
            findings = version.red_team_snapshot.get("findings", [])
            reviewed = version.red_team_snapshot.get("reviewed_at")
            review_fingerprint = version.red_team_snapshot.get("design_fingerprint", "")
            st.write(
                f"Red-Team: **{status}** ({len(findings)} finding(s)), "
                f"reviewed {short_timestamp(reviewed)}"
            )
            if review_fingerprint and version.design_hash:
                if review_fingerprint == version.design_hash:
                    st.caption(
                        "The stored Red-Team snapshot matches this design fingerprint."
                    )
                else:
                    st.warning(
                        "The stored Red-Team snapshot was produced for a different "
                        "design fingerprint. Re-run the review before relying on it."
                    )
        else:
            st.caption("No Red-Team review was stored with this version.")

        if version.checks_snapshot:
            status = version.checks_snapshot.get("status", "unknown")
            st.caption(f"Structural checks at save time: {status}")

        st.download_button(
            f"📥 Download design JSON (v{version.version})",
            data=json.dumps(version.design_snapshot, indent=2).encode("utf-8"),
            file_name=f"{circuit_id}_v{version.version}_design.json",
            mime="application/json",
            key=f"dl_dna_{circuit_id}_{version.version}",
        )


def render_dna_tab(settings: Settings) -> None:
    st.subheader("🧬 Circuit DNA")
    st.caption(
        "Persistent, versioned engineering identity for every circuit. "
        "Records are append-only — no version is overwritten, and previous "
        "reviews remain visible."
    )

    storage = DNAStorage(settings.db_path)
    result = require_result(
        "Run a circuit analysis first, then return here to save it to Circuit DNA."
    )
    if result is not None:
        _render_save_panel(settings, result)

    st.divider()
    st.markdown("### Circuit History")
    circuits = storage.list_circuits()
    if not circuits:
        st.info("No circuits saved yet. Run an analysis and save it to Circuit DNA.")
        return

    options = {
        f"{item['circuit_id']} — {item['name']} ({item['version_count']} version(s))": item[
            "circuit_id"
        ]
        for item in circuits
    }
    selected_label = st.selectbox(
        "Select circuit",
        options=list(options),
        key="dna_circuit_select",
    )
    selected_id = options[selected_label]
    record = storage.get_record(selected_id)
    if record is None:
        st.warning("The selected circuit could not be read.")
        return

    first, second, third = st.columns(3)
    first.metric("Circuit ID", record.circuit_id)
    second.metric("Versions", record.version_count)
    third.metric("Created", record.created_at[:10])

    st.write(f"**Description:** {record.description}")

    latest = record.latest_version
    if latest is not None:
        st.caption(
            f"Latest version: {latest.version} | "
            f"Design fingerprint: {latest.design_hash or 'unknown'}"
        )

    st.markdown("#### Version Timeline")
    for version in reversed(record.versions):
        _render_version(version, selected_id)

    st.caption(
        "Circuit DNA stores engineering snapshots only. Provider keys and other "
        "secrets are never written to the database. Back up the SQLite file to "
        "preserve history."
    )
