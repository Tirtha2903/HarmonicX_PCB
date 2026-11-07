"""Parsing and formatting helpers for engineering values.

These helpers never guess a unit that is not present in the source text unless
the caller explicitly asks for a default unit. They are used by deterministic
checks and by the Virtual Lab Assistant.
"""

from __future__ import annotations

import math
import re

_MULTIPLIERS = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "G": 1e9,
}

_PREFIXED = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*([pnuµmkKMG])(\d+)?\s*([A-Za-zΩ]+)?\s*$"
)
_PLAIN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([A-Za-zΩ]+)?\s*$")


def _parse(
    text: str | None,
    units: set[str],
    allowed_prefixes: set[str] | None = None,
) -> float | None:
    if text is None:
        return None
    cleaned = text.strip().replace("Ω", "ohm").replace("ω", "ohm")
    if not cleaned:
        return None

    match = _PREFIXED.match(cleaned)
    if match:
        major, prefix, fraction, unit = match.groups()
        unit_key = (unit or "").lower()
        # A unit, when present, must be one of the units this parser understands.
        # Prefixes can be restricted per quantity (capacitance has no kilo prefix).
        if allowed_prefixes is not None and prefix not in allowed_prefixes:
            return None
        if unit_key and unit_key not in units:
            return None
        value = float(major + ("." + fraction if fraction else "")) * _MULTIPLIERS[prefix]
        return value

    match = _PLAIN.match(cleaned)
    if not match:
        return None
    number, unit = match.groups()
    unit_key = (unit or "").lower()
    if unit_key and unit_key not in units:
        return None
    return float(number)


def parse_resistance(text: str | None) -> float | None:
    """Parse values such as ``220``, ``220R``, ``1k``, ``4k7`` or ``1MΩ``."""
    if text is None:
        return None
    normalized = text.strip().replace("Ω", "ohm").replace("ω", "ohm")
    # "220R" and "4R7" are common resistor notations.
    r_match = re.fullmatch(r"\s*(\d+)(?:[rR](\d+))?\s*(?:ohm|ohms)?\s*", normalized, re.I)
    if r_match and any(ch.isdigit() for ch in normalized):
        whole, fraction = r_match.groups()
        return float(whole + ("." + fraction if fraction else ""))
    return _parse(normalized, {"ohm", "ohms", "r"})


def parse_capacitance(text: str | None) -> float | None:
    """Parse capacitance in farads (``100nF``, ``10uF``, ``1mF``).

    Kilo and giga prefixes are resistance/other-quantity notation, so ``10k``
    is not silently treated as 10 kF. A bare ``100n`` is still accepted as the
    common shorthand for 100 nF.
    """
    return _parse(
        text,
        {"f", "farad", "farads"},
        allowed_prefixes={"p", "n", "u", "µ", "m"},
    )


def parse_voltage(text: str | None) -> float | None:
    return _parse(text, {"v", "volt", "volts", "vdc"})


def parse_power(text: str | None) -> float | None:
    return _parse(text, {"w", "watt", "watts"})


def format_si(value: float | None, unit: str, digits: int = 3) -> str:
    """Format a value with an engineering prefix, for example ``4.7 kΩ``."""
    if value is None or not math.isfinite(value):
        return "unknown"
    if value == 0:
        return f"0 {unit}"
    prefixes = [
        (1e9, "G"),
        (1e6, "M"),
        (1e3, "k"),
        (1.0, ""),
        (1e-3, "m"),
        (1e-6, "µ"),
        (1e-9, "n"),
        (1e-12, "p"),
    ]
    magnitude = abs(value)
    for scale, prefix in prefixes:
        if magnitude >= scale:
            scaled = value / scale
            text = f"{scaled:.{digits}g}"
            return f"{text} {prefix}{unit}"
    return f"{value:.{digits}g} {unit}"


def resistance_label(value: float | None) -> str:
    return format_si(value, "Ω")


def capacitance_label(value: float | None) -> str:
    return format_si(value, "F")


def voltage_label(value: float | None) -> str:
    return format_si(value, "V")


def power_label(value: float | None) -> str:
    return format_si(value, "W")
