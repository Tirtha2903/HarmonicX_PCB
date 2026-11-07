"""CircuitPilot AI Streamlit entry point.

The UI sections live in the ``ui`` package. This module only configures the
page, renders the sidebar and dispatches to each tab.
"""

from __future__ import annotations

import logging

import streamlit as st

from config import get_settings
from services.logging_config import configure_logging
from ui import (
    render_about_tab,
    render_design_tab,
    render_dna_tab,
    render_kicad_tab,
    render_red_team_tab,
    render_virtual_lab_tab,
)

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
st.caption(
    "Multimodal electronics analysis • Red-Team review • Virtual Lab • Circuit DNA"
)

with st.sidebar:
    st.header("System status")
    st.write(f"Model configured: {'Yes' if settings.ai_model else 'No'}")
    st.write(f"API endpoint configured: {'Yes' if settings.ai_base_url else 'No'}")
    st.write(
        "KiCad CLI: "
        + ("Configured" if settings.kicad_cli_path else "PATH lookup")
    )
    st.write(f"DNA database: {settings.db_path.name}")
    st.write(f"AI Red-Team additions: {'Enabled' if settings.enable_ai_red_team else 'Disabled'}")
    st.write(
        "AI Virtual Lab additions: "
        + ("Enabled" if settings.enable_ai_virtual_lab else "Disabled")
    )
    st.divider()
    st.caption(
        "AI analysis is not electrical certification. Review every component, "
        "connection, rating and footprint before implementation."
    )

(
    tab_design,
    tab_red_team,
    tab_virtual_lab,
    tab_dna,
    tab_kicad,
    tab_about,
) = st.tabs(
    [
        "Circuit analysis",
        "⚔️ Red-Team",
        "🧪 Virtual Lab",
        "🧬 Circuit DNA",
        "KiCad ERC",
        "About & limitations",
    ]
)

with tab_design:
    render_design_tab(settings)

with tab_red_team:
    render_red_team_tab()

with tab_virtual_lab:
    render_virtual_lab_tab(settings)

with tab_dna:
    render_dna_tab(settings)

with tab_kicad:
    render_kicad_tab(settings)

with tab_about:
    render_about_tab()
