"""Shared Streamlit UI helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import streamlit as st

from electronics.red_team.models import FindingSeverity

logger = logging.getLogger(__name__)

SEVERITY_ORDER: list[FindingSeverity] = [
    FindingSeverity.CRITICAL,
    FindingSeverity.HIGH,
    FindingSeverity.MEDIUM,
    FindingSeverity.LOW,
    FindingSeverity.INFORMATIONAL,
]

SEVERITY_ICONS = {
    FindingSeverity.CRITICAL: "🚨",
    FindingSeverity.HIGH: "🔴",
    FindingSeverity.MEDIUM: "🟡",
    FindingSeverity.LOW: "🔵",
    FindingSeverity.INFORMATIONAL: "ℹ️",
}

STATUS_ICONS = {
    "PASS": "✅",
    "NEEDS_REVIEW": "⚠️",
    "FAIL": "🚨",
}

BASIS_LABELS = {
    "calculated": "CALCULATED from declared data",
    "design_target": "DESIGN TARGET (not simulated)",
    "requires_verification": "REQUIRES CALCULATION / DATASHEET",
    "ai_suggested": "AI-SUGGESTED — UNVERIFIED",
}


def get_result() -> dict[str, Any] | None:
    """Return the current analysis result, if any."""
    result = st.session_state.get("circuitpilot_result")
    return result if isinstance(result, dict) else None


def require_result(message: str = "Run a circuit analysis first.") -> dict[str, Any] | None:
    result = get_result()
    if result is None:
        st.info(message)
    return result


def render_artifact_downloads(artifact_dir: Path, include_review: bool = False) -> None:
    """Render download buttons for the additive review artifacts."""
    if not include_review:
        return
    for filename, label, mime in [
        ("red_team_review.json", "Download Red-Team JSON", "application/json"),
        ("red_team_review.md", "Download Red-Team report (Markdown)", "text/markdown"),
        ("analysis_manifest.json", "Download analysis manifest", "application/json"),
    ]:
        file_path = artifact_dir / filename
        if file_path.exists():
            st.download_button(
                label,
                data=file_path.read_bytes(),
                file_name=filename,
                mime=mime,
                key=f"review_download_{filename}",
            )


def short_timestamp(value: str | None) -> str:
    if not value:
        return "unknown"
    return value[:19].replace("T", " ") + " UTC"
