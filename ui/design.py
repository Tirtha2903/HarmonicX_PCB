"""Circuit analysis tab."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import streamlit as st

from agents.orchestrator import CircuitPilotOrchestrator
from config import Settings
from services.llm_client import LLMConfigurationError, LLMRequestError

logger = logging.getLogger(__name__)


def render_design_tab(settings: Settings) -> None:
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
            image_data: tuple[str, bytes] | None = None
            if uploaded_image:
                try:
                    from PIL import Image as PILImage

                    raw = uploaded_image.getvalue()
                    img = PILImage.open(io.BytesIO(raw))
                    img.verify()
                    image_data = (uploaded_image.name, raw)
                except Exception as exc:
                    st.error(f"The uploaded file is not a valid supported image: {exc}")
                    image_data = None

            if uploaded_image and image_data is None:
                return

            try:
                with st.spinner(
                    "Interpreting requirements, running Red-Team review and exporting artifacts..."
                ):
                    result = CircuitPilotOrchestrator(settings).run(
                        prompt.strip() or "Analyze the uploaded circuit image.",
                        image=image_data,
                    )
                st.session_state["circuitpilot_result"] = result
                st.session_state.pop("lab_procedure", None)
                st.success(
                    "Analysis completed. Switch to ⚔️ Red-Team, 🧪 Virtual Lab or "
                    "🧬 Circuit DNA tabs."
                )
            except LLMConfigurationError as exc:
                st.error(str(exc))
            except LLMRequestError as exc:
                st.error(str(exc))
            except Exception as exc:
                logger.exception("Circuit analysis failed")
                st.error(f"Analysis failed: {exc}")

    result = st.session_state.get("circuitpilot_result")
    if not result:
        return

    design = result["design"]
    checks = result["checks"]
    st.divider()
    st.subheader(design.project_name)
    st.write(design.project_description)

    first, second, third = st.columns(3)
    first.metric("Components", len(design.components))
    second.metric("Connections", len(design.connections))
    third.metric("AI confidence", f"{design.overall_confidence:.0%}")

    if design.requires_confirmation:
        st.warning("Engineering confirmation required before implementation.")
    else:
        st.info(
            "No confirmation flag was raised by the model. Independent engineering "
            "review is still required."
        )

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
