"""Deterministic safety rules for the Virtual Lab Assistant.

These rules depend only on the declared design and produce explicit safety
notes. They do not replace a laboratory risk assessment.
"""

from __future__ import annotations

from schemas.circuit import CircuitDesign
from services.virtual_lab.models import SafetyNote

_DANGEROUS_VOLTAGE_V = 30.0  # Common ELV boundary used for lab guidance.
_LETHAL_VOLTAGE_V = 50.0


def get_safety_notes(
    design: CircuitDesign,
    needs_oscilloscope: bool = False,
) -> list[SafetyNote]:
    notes: list[SafetyNote] = []
    supply = design.supply_voltage_v

    notes.append(
        SafetyNote(
            severity="INFO",
            note=(
                "Power off the circuit and disconnect the supply before changing any "
                "wiring or component. Measure stored capacitor voltage and discharge "
                "through an appropriate resistor before touching the circuit."
            ),
        )
    )

    if supply is not None:
        if supply >= _LETHAL_VOLTAGE_V:
            notes.append(
                SafetyNote(
                    severity="WARNING",
                    note=(
                        f"Declared supply is {supply:g} V. Voltages at or above 50 V AC "
                        "or 120 V DC can be lethal. This procedure must not be attempted "
                        "without qualified supervision, appropriately rated probes and "
                        "personal protective equipment. Treat all conductors as live."
                    ),
                )
            )
        elif supply >= _DANGEROUS_VOLTAGE_V:
            notes.append(
                SafetyNote(
                    severity="WARNING",
                    note=(
                        f"Declared supply is {supply:g} V, above the {_DANGEROUS_VOLTAGE_V:g} V "
                        "extra-low-voltage boundary used here. Electric shock is possible. "
                        "Use insulated tools and rated probes, and never rewire a powered circuit."
                    ),
                )
            )
        else:
            notes.append(
                SafetyNote(
                    severity="INFO",
                    note=(
                        f"Declared supply ({supply:g} V) is within the extra-low-voltage "
                        "range used by this guide. Standard laboratory precautions still apply."
                    ),
                )
            )

        notes.append(
            SafetyNote(
                severity="INFO",
                note=(
                    "Use a regulated supply with an adjustable current limit. If the "
                    "expected current is unknown, start with a low limit (for example "
                    "50–100 mA) and increase only after confirming the rails. The correct "
                    "limit depends on the design and must be calculated or measured."
                ),
            )
        )

    if any(
        any(
            keyword in component.name.lower()
            for keyword in ("capacitor", "electrolytic", "tantalum")
        )
        for component in design.components
    ):
        notes.append(
            SafetyNote(
                severity="CAUTION",
                note=(
                    "Capacitors can retain charge after power-off. Measure their voltage "
                    "before touching the board and discharge them through an appropriate "
                    "resistor. Never short a capacitor with a screwdriver."
                ),
            )
        )

    if any(
        any(
            keyword in component.name.lower()
            for keyword in ("led", "diode", "electrolytic", "tantalum")
        )
        for component in design.components
    ):
        notes.append(
            SafetyNote(
                severity="CAUTION",
                note=(
                    "Polarity-sensitive parts are present (LEDs, diodes or polarized "
                    "capacitors). Reversed polarity can destroy the part, cause venting "
                    "or create a fire risk. Verify orientation before applying power."
                ),
            )
        )

    notes.append(
        SafetyNote(
            severity="CAUTION",
            note=(
                "Never connect a multimeter in current mode across a component or between "
                "supply and ground. An ammeter is a near-short and must be connected in "
                "series only, with the circuit unpowered while the connection is changed."
            ),
        )
    )

    if needs_oscilloscope:
        notes.append(
            SafetyNote(
                severity="WARNING",
                note=(
                    "Oscilloscope ground clips are connected to protective earth. Never "
                    "clip the scope ground to a non-ground circuit node: doing so can "
                    "short that node to earth through the instrument. Use a differential "
                    "probe or an isolation transformer only with qualified supervision."
                ),
            )
        )

    notes.append(
        SafetyNote(
            severity="INFO",
            note=(
                "This procedure covers only the declared low-voltage circuit. Do not "
                "probe unknown high-voltage, mains-powered or battery-bank circuits "
                "without appropriate equipment, training and a documented risk assessment."
            ),
        )
    )
    return notes
