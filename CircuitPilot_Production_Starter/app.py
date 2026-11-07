from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

from agents.orchestrator import CircuitPilotOrchestrator
from config import get_settings
from electronics.kicad import KiCadError, run_schematic_erc
from services.llm_client import LLMConfigurationError, LLMRequestError
from services.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="CircuitPilot AI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("⚡ CircuitPilot AI")
st.caption("Multimodal electronics analysis • Structured design specification • Engineering review")

with st.sidebar:
    st.header("System status")
    st.write(f"Model configured: {'Yes' if settings.ai_model else 'No'}")
    st.write(f"API endpoint configured: {'Yes' if settings.ai_base_url else 'No'}")
    st.write("KiCad CLI: " + ("Configured" if settings.kicad_cli_path else "PATH lookup"))
    st.divider()
    st.caption(
        "AI analysis is not electrical certification. Review every component, "
        "connection, rating and footprint before implementation."
    )

tab_design, tab_kicad, tab_about = st.tabs(
    ["Circuit analysis", "KiCad ERC", "About & limitations"]
)

with tab_design:
    st.subheader("Describe or upload a circuit")
    prompt = st.text_area(
        "Circuit requirements",
        placeholder=(
            "Example: Design a 5 V LED flasher using an NE555 at approximately "
            "2 Hz. Include the component values and explain any missing design inputs."
        ),
        height=140,
        max_chars=settings.max_prompt_chars,
    )
    uploaded_image = st.file_uploader(
        "Optional circuit image",
        type=["png", "jpg", "jpeg", "webp"],
        help=f"Maximum file size: {settings.max_image_mb} MB.",
    )

    if st.button("Analyze circuit", type="primary", use_container_width=True):
        if not prompt.strip() and uploaded_image is None:
            st.warning("Enter a requirement or upload a circuit image.")
        elif uploaded_image and uploaded_image.size > settings.max_image_mb * 1024 * 1024:
            st.error(f"Image exceeds the {settings.max_image_mb} MB limit.")
        else:
            image_data = None
            if uploaded_image:
                try:
                    from PIL import Image as PILImage
                    import io

                    raw = uploaded_image.getvalue()
                    # verify() must be called on a freshly opened (not context-managed)
                    # image object; it reads to EOF and leaves the object unusable.
                    img = PILImage.open(io.BytesIO(raw))
                    img.verify()
                    image_data = (uploaded_image.name, raw)
                except Exception as exc:
                    st.error(f"The uploaded file is not a valid supported image: {exc}")
                    image_data = None

            if uploaded_image and image_data is None:
                st.stop()

            try:
                with st.spinner("Interpreting requirements and reviewing the circuit..."):
                    result = CircuitPilotOrchestrator(settings).run(
                        prompt.strip() or "Analyze the uploaded circuit image.",
                        image=image_data,
                    )
                st.session_state["circuitpilot_result"] = result
                st.success("Analysis completed. Review the uncertainties before using the design.")
            except LLMConfigurationError as exc:
                st.error(str(exc))
            except LLMRequestError as exc:
                st.error(str(exc))
            except Exception as exc:
                logger.exception("Circuit analysis failed")
                st.error(f"Analysis failed: {exc}")

    result = st.session_state.get("circuitpilot_result")
    if result:
        design = result["design"]
        checks = result["checks"]
        st.divider()
        st.subheader(design.project_name)
        st.write(design.project_description)

        c1, c2, c3 = st.columns(3)
        c1.metric("Components", len(design.components))
        c2.metric("Connections", len(design.connections))
        c3.metric("AI confidence", f"{design.overall_confidence:.0%}")

        if design.requires_confirmation:
            st.warning("Engineering confirmation required before implementation.")
        else:
            st.info("No confirmation flag was raised by the model. Independent engineering review is still required.")

        with st.expander("Component list", expanded=True):
            if design.components:
                st.dataframe(
                    [component.model_dump() for component in design.components],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No components identified.")

        with st.expander("Electrical connections", expanded=True):
            if design.connections:
                st.dataframe(
                    [
                        {
                            "Net": connection.net_name,
                            "Pins": " ↔ ".join(connection.pins),
                            "Confidence": connection.confidence,
                            "Evidence": connection.evidence or "",
                        }
                        for connection in design.connections
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No explicit connections identified.")

        with st.expander("Board specifications"):
            st.json(design.board.model_dump())

        with st.expander("Assumptions, missing information and design notes", expanded=True):
            st.markdown("**Missing information**")
            st.write(design.missing_information or ["None listed by the model."])
            st.markdown("**Assumptions**")
            st.write(design.assumptions or ["None listed."])
            st.markdown("**Design notes**")
            st.write(design.design_notes or ["None listed."])

        st.subheader("Automated structural checks")
        st.write(f"Status: **{checks['status']}**")
        for item in checks["errors"]:
            st.error(item)
        for item in checks["warnings"]:
            st.warning(item)
        st.caption(
            "These checks do not perform electrical simulation, KiCad ERC, PCB DRC "
            "or manufacturing validation."
        )

        artifact_dir = Path(result["artifact_dir"])
        st.subheader("Generated review artifacts")
        for filename, label in [
            ("circuit_design.json", "Download structured design JSON"),
            ("bom.csv", "Download BOM CSV"),
            ("connections.csv", "Download connections CSV"),
        ]:
            file_path = artifact_dir / filename
            if file_path.exists():
                st.download_button(
                    label,
                    data=file_path.read_bytes(),
                    file_name=filename,
                    mime="application/json" if filename.endswith(".json") else "text/csv",
                    key=f"download_{filename}",
                )
        st.caption(f"Artifacts saved locally in: {artifact_dir}")

with tab_kicad:
    st.subheader("Run ERC on an existing KiCad schematic")
    st.info(
        "This action checks the uploaded KiCad schematic only. It does not "
        "validate the AI-generated JSON, and ERC passing does not prove the "
        "circuit is functionally safe."
    )
    schematic_file = st.file_uploader(
        "Upload .kicad_sch",
        type=["kicad_sch"],
        key="kicad_schematic_upload",
    )
    if st.button("Run KiCad ERC", use_container_width=True):
        if schematic_file is None:
            st.warning("Upload a .kicad_sch file first.")
        else:
            temp_dir = settings.output_dir / "kicad_uploads"
            temp_dir.mkdir(parents=True, exist_ok=True)
            safe_name = Path(schematic_file.name).name
            schematic_path = temp_dir / safe_name
            schematic_path.write_bytes(schematic_file.getvalue())
            report_dir = temp_dir / "reports"
            try:
                with st.spinner("Running KiCad ERC..."):
                    report = run_schematic_erc(
                        schematic_path,
                        report_dir,
                        settings.kicad_cli_path,
                    )
                st.write(f"KiCad CLI return code: {report['return_code']}")
                st.write(f"Result: **{report['status']}**")
                st.json(report["report"] if report["report"] is not None else {
                    "stdout": report["stdout"],
                    "stderr": report["stderr"],
                })
                if Path(report["report_path"]).exists():
                    st.download_button(
                        "Download ERC report",
                        data=Path(report["report_path"]).read_bytes(),
                        file_name=Path(report["report_path"]).name,
                        mime="application/json",
                    )
            except KiCadError as exc:
                st.error(str(exc))
            except Exception as exc:
                logger.exception("KiCad ERC failed")
                st.error(f"KiCad ERC failed: {exc}")

with tab_about:
    st.subheader("What CircuitPilot currently does")
    st.markdown(
        """
        - Interprets text requirements and supported circuit images.
        - Produces a structured, reviewable circuit-design specification.
        - Records assumptions, missing information and uncertainty.
        - Exports JSON, BOM CSV and connection CSV.
        - Runs KiCad ERC on an uploaded native KiCad schematic when KiCad CLI is available.
        """
    )
    st.subheader("What it does not claim to do")
    st.markdown(
        """
        - It does not yet synthesize a native `.kicad_sch` or `.kicad_pcb` from the AI output.
        - It does not perform SPICE simulation, PCB DRC on generated boards, thermal analysis,
          signal-integrity analysis or manufacturing certification.
        - AI confidence is not an electrical correctness score.
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
