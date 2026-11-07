"""Streamlit UI sections for CircuitPilot AI."""

from __future__ import annotations

from ui.about import render_about_tab
from ui.design import render_design_tab
from ui.dna import render_dna_tab
from ui.kicad import render_kicad_tab
from ui.red_team import render_red_team_tab
from ui.virtual_lab import render_virtual_lab_tab

__all__ = [
    "render_about_tab",
    "render_design_tab",
    "render_dna_tab",
    "render_kicad_tab",
    "render_red_team_tab",
    "render_virtual_lab_tab",
]
