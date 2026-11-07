"""Stable Circuit DNA identifiers."""

from __future__ import annotations

import re

from schemas.circuit import CircuitDesign
from schemas.fingerprint import design_fingerprint


def _slugify(text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", text.upper())
    if not tokens:
        return "CIRC"
    # Prefer a token that contains a digit (for example NE555 or 3V3);
    # otherwise use the first word. This keeps identifiers recognisable.
    candidate = next(
        (token for token in tokens if any(character.isdigit() for character in token)),
        tokens[0],
    )
    return candidate[:6] or "CIRC"


def generate_circuit_id(design: CircuitDesign, sequence: int = 1) -> str:
    """Generate an identifier such as ``CP-NE555-0001``."""
    if sequence < 1:
        raise ValueError("Sequence number must be at least 1.")
    return f"CP-{_slugify(design.project_name)}-{sequence:04d}"


def generate_stable_hash(design: CircuitDesign) -> str:
    """Return the canonical design fingerprint."""
    return design_fingerprint(design)


CIRCUIT_ID_PATTERN = re.compile(r"^CP-[A-Z0-9]{1,8}-\d{4,6}$")


def is_valid_circuit_id(circuit_id: str) -> bool:
    return bool(CIRCUIT_ID_PATTERN.fullmatch(circuit_id.strip()))
