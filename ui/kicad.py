"""KiCad ERC tab."""

from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

from config import Settings
from electronics.kicad import KiCadError, run_schematic_erc

logger = logging.getLogger(__name__)


def render_kicad_tab(settings: Settings) -> None:
    st.subheader("Run ERC on an existing KiCad schematic")
    st.info(
        "This action checks the uploaded KiCad schematic only. It does not validate "
        "the AI-generated JSON, and ERC passing does not prove the circuit is "
        "functionally safe."
    )
    schematic_file = st.file_uploader(
        "Upload .kicad_sch",
        type=["kicad_sch"],
        key="kicad_schematic_upload",
    )
    if st.button("Run KiCad ERC", use_container_width=True):
        if schematic_file is None:
            st.warning("Upload a .kicad_sch file first.")
            return

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
            if isinstance(report["report"], (dict, list)):
                st.json(report["report"])
            elif report["report"]:
                st.code(str(report["report"]))
            else:
                st.json(
                    {
                        "stdout": report["stdout"],
                        "stderr": report["stderr"],
                    }
                )
            report_path = Path(report["report_path"])
            if report_path.exists():
                st.download_button(
                    "Download ERC report",
                    data=report_path.read_bytes(),
                    file_name=report_path.name,
                    mime="application/json",
                )
        except KiCadError as exc:
            st.error(str(exc))
        except Exception as exc:
            logger.exception("KiCad ERC failed")
            st.error(f"KiCad ERC failed: {exc}")
