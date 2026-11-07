"""Circuit analysis tab."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import streamlit as st
from PIL import Image, UnidentifiedImageError

from agents.orchestrator import CircuitPilotOrchestrator
from config import Settings
from services.llm_client import LLMConfigurationError, LLMRequestError

logger = logging.getLogger(__name__)

MAX_REFERENCE_IMAGES = 4
EXAMPLE_PROMPT = (
    "I want to build a low-voltage LED indicator circuit. The available supply is "
    "5 V DC. The LED should turn on when power is connected. Please identify the "
    "information and components needed, but do not guess an LED part number, pinout, "
    "or resistor value without stating the assumptions and calculations required. "
    "List any missing details I should confirm before building."
)


def _read_uploaded_images(
    uploaded_images: list[Any],
    max_image_mb: int,
) -> tuple[list[tuple[str, bytes]], list[str]]:
    images: list[tuple[str, bytes]] = []
    errors: list[str] = []
    max_size = max_image_mb * 1024 * 1024

    for uploaded_image in uploaded_images:
        if uploaded_image.size > max_size:
            errors.append(
                f"{uploaded_image.name} exceeds the {max_image_mb} MB per-image limit."
            )
            continue

        raw = uploaded_image.getvalue()
        try:
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            errors.append(f"{uploaded_image.name} is not a valid supported image: {exc}")
            continue

        images.append((uploaded_image.name, raw))

    return images, errors


def render_design_tab(settings: Settings) -> None:
    st.subheader("Add project details and reference photos")
    st.write(
        "Describe what you want to build or review. Add clear circuit, breadboard, "
        "or PCB photos if they help explain the design."
    )

    with st.expander("Need help writing the requirements?", expanded=False):
        st.markdown(
            """
            Include what the circuit should do, its power source, known components
            and values, important constraints, and what you want CircuitPilot to
            check. For photos, use a sharp, well-lit image with labels and
            connections visible; you can add up to four PNG, JPEG, or WEBP images.
            """
        )
        st.code(EXAMPLE_PROMPT, language="text")

    st.caption(
        "Your written requirements and selected photos are sent to the configured "
        "AI provider for analysis. Do not upload confidential designs without permission."
    )

    with st.container(border=True):
        details_column, photos_column = st.columns([1.2, 0.8], gap="large")
        with details_column:
            prompt = st.text_area(
                "Written requirements",
                placeholder=(
                    "What should the circuit do? Include supply voltage, known "
                    "components or values, constraints, and questions you want answered."
                ),
                height=220,
                max_chars=settings.max_prompt_chars,
                key="design_requirements",
                help="Text and photos can be submitted together.",
            )
            st.caption(f"{len(prompt)} / {settings.max_prompt_chars} characters")

        with photos_column:
            uploaded_images = st.file_uploader(
                "Circuit photos or schematic images",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                help=(
                    f"Add up to {MAX_REFERENCE_IMAGES} images. Maximum "
                    f"{settings.max_image_mb} MB per image."
                ),
                key="circuit_reference_images",
            )
            images: list[tuple[str, bytes]] = []
            image_errors: list[str] = []
            if len(uploaded_images) > MAX_REFERENCE_IMAGES:
                image_errors.append(
                    f"Select no more than {MAX_REFERENCE_IMAGES} images."
                )
            else:
                images, image_errors = _read_uploaded_images(
                    uploaded_images,
                    settings.max_image_mb,
                )

            for error in image_errors:
                st.error(error)

            if images:
                st.caption(f"{len(images)} valid reference image(s) ready")
                preview_columns = st.columns(min(2, len(images)))
                for index, (filename, image_bytes) in enumerate(images):
                    with preview_columns[index % len(preview_columns)]:
                        st.image(
                            image_bytes,
                            caption=filename,
                            use_container_width=True,
                        )

        analyze_clicked = st.button(
            "Analyze my circuit",
            type="primary",
            use_container_width=True,
            disabled=bool(image_errors),
        )

    if analyze_clicked:
        if not prompt.strip() and not images:
            st.warning("Enter written requirements, upload at least one image, or do both.")
        else:
            request_prompt = prompt.strip() or "Analyze the uploaded circuit images."
            try:
                with st.spinner(
                    "Analyzing your input, running engineering checks, and preparing reports..."
                ):
                    result = CircuitPilotOrchestrator(settings).run(
                        request_prompt,
                        images=images,
                    )
                st.session_state["circuitpilot_result"] = result
                st.session_state.pop("lab_procedure", None)
                st.success(
                    "Analysis completed. Open Red-Team, Virtual Lab, or Circuit DNA "
                    "for the review details."
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
