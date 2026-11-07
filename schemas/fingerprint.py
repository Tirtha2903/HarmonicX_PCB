"""Canonical design fingerprints.

A fingerprint identifies the *content* of a design snapshot. It deliberately
ignores model-confidence fields so that re-running an analysis with the same
engineering content does not look like a design change.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from schemas.circuit import CircuitDesign

_IGNORED_KEYS = {"confidence", "requires_confirmation", "overall_confidence"}


def _strip_confidence(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_confidence(item)
            for key, item in value.items()
            if key not in _IGNORED_KEYS
        }
    if isinstance(value, list):
        return [_strip_confidence(item) for item in value]
    return value


def design_fingerprint(design: CircuitDesign) -> str:
    """Return a stable 16-character SHA-256 prefix of the design content."""
    payload = _strip_confidence(design.model_dump(mode="json"))
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
