"""About and limitations tab."""

from __future__ import annotations

import streamlit as st


def render_about_tab() -> None:
    st.subheader("What CircuitPilot currently does")
    st.markdown(
        """
        - Interprets text requirements and supported circuit images using a
          configurable OpenAI-compatible provider.
        - Produces a structured, reviewable circuit-design specification.
        - Records assumptions, missing information and uncertainty.
        - Exports `circuit_design.json`, `bom.csv` and `connections.csv`.
        - Runs **Circuit Red-Team**: deterministic power, protection, connectivity,
          compatibility and requirement-consistency checks, followed by an optional,
          clearly-labelled AI contextual review.
        - Generates **Virtual Lab** procedures: circuit-specific equipment, pre-power
          checks, measurement points, test sequence, troubleshooting and safety notes.
        - Maintains **Circuit DNA**: stable identifiers, append-only SQLite versions,
          design fingerprints, change detection and Red-Team review snapshots.
        - Runs KiCad ERC on an uploaded native KiCad schematic when KiCad CLI is available.
        """
    )

    st.subheader("What it does not claim to do")
    st.markdown(
        """
        - It does not synthesize a native `.kicad_sch` or `.kicad_pcb` from the AI output.
        - It does not perform SPICE simulation, PCB DRC on generated boards, thermal
          analysis, signal-integrity analysis or manufacturing certification.
        - AI confidence is not an electrical correctness score.
        - Red-Team `PASS` means no finding was produced by the implemented checks for
          the declared snapshot. It does **not** mean the circuit is electrically safe.
          Only a `CRITICAL` deterministic finding produces `FAIL`.
        - AI-suggested Red-Team findings and AI-suggested Lab items are never verified
          by this application and must be checked independently.
        - Virtual Lab expected values marked "Requires calculation / datasheet" have
          not been calculated. No simulation or physical measurement is performed.
        - Circuit DNA stores the data you provide. It does not prove that a component,
          rating or connection is correct.
        """
    )

    st.subheader("Before building or manufacturing")
    st.markdown(
        """
        Have a qualified electronics reviewer verify component datasheets, pinouts,
        absolute maximum ratings, power dissipation, current paths, protection,
        clearances, creepage, thermal behavior, grounding and manufacturability.
        """
    )

    st.subheader("Circuit DNA disclaimer")
    st.markdown(
        """
        Circuit DNA records are stored locally in a SQLite database. Records are
        append-only — no version is overwritten. Back up this file to preserve history.
        API keys and other provider secrets are never written to the database.
        """
    )

    st.subheader("Safety")
    st.markdown(
        """
        The Virtual Lab Assistant provides engineering guidance, not a verified test
        procedure or risk assessment. Never work on a powered circuit without
        appropriate training, equipment and supervision. Energized high-voltage,
        mains-powered and battery-bank circuits require a documented risk assessment
        and qualified supervision.
        """
    )
