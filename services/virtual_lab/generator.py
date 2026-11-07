"""Virtual Lab Assistant.

A deterministic, circuit-specific testing procedure is always built first.
The LLM is used only to *add* contextual suggestions; it can never replace a
calculated value, and every AI-suggested value is labelled unverified.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from config import Settings
from electronics.calculations import find_voltage_dividers
from electronics.netinfo import (
    build_net_index,
    find_series_resistor,
    is_capacitor,
    is_diode,
    is_ic_like,
    is_led,
    is_resistor,
)
from electronics.red_team.models import RedTeamReport
from electronics.values import parse_resistance, resistance_label
from schemas.circuit import CircuitDesign
from schemas.fingerprint import design_fingerprint
from services.virtual_lab.models import (
    EquipmentItem,
    LabProcedure,
    MeasurementPoint,
    PrePowerCheck,
    TestStep,
    TroubleshootingEntry,
)
from services.virtual_lab.safety import get_safety_notes

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a practical electronics lab instructor. You receive a structured circuit
design and a deterministic testing procedure that is already complete.

Add ONLY circuit-specific clarifications that a lab instructor would usefully
contribute. Do not repeat existing items, do not invent component ratings or
measurement values, and do not claim that anything was simulated or measured.

Return one raw JSON object (no markdown fences):
{
  "equipment": [
    {"name": "...", "specification": "...", "reason": "...", "required": false}
  ],
  "pre_power_checks": [
    {"description": "...", "how_to_verify": "...", "critical": false}
  ],
  "measurement_points": [
    {
      "description": "...",
      "measurement_location": "...",
      "reference_ground": "...",
      "instrument": "Multimeter|Oscilloscope|Current Probe|Power Supply|Frequency Counter",
      "measurement_mode": "...",
      "expected_result": "Requires calculation or datasheet confirmation",
      "abnormal_indication": "...",
      "reason": "...",
      "safety_note": null
    }
  ],
  "troubleshooting": [
    {"symptom": "...", "possible_causes": ["..."], "diagnostic_actions": ["..."]}
  ],
  "notes": ["..."]
}

If a value cannot be calculated from supplied data, write exactly:
"Requires calculation or datasheet confirmation".
"""


def _requires_oscilloscope(design: CircuitDesign) -> bool:
    if design.target_frequency_hz is not None:
        return True
    text = " ".join(
        [
            design.project_name,
            design.project_description,
            *design.design_notes,
            *design.assumptions,
            *(component.name for component in design.components),
        ]
    ).lower()
    return any(
        keyword in text
        for keyword in (
            "oscillator",
            "timer",
            "555",
            "crystal",
            "resonator",
            "pwm",
            "waveform",
            "frequency",
            "microcontroller",
            "mcu",
        )
    )


def _required_components(design: CircuitDesign) -> list[str]:
    items = []
    for component in design.components:
        value = f" — {component.value}" if component.value else ""
        quantity = f" ×{component.quantity}" if component.quantity != 1 else ""
        items.append(f"{component.reference}: {component.name}{value}{quantity}")
    return items


def _ground_reference(design: CircuitDesign) -> str:
    index = build_net_index(design)
    grounds = sorted(index.ground_nets)
    return grounds[0] if grounds else "GND (common return)"


def _supply_reference(design: CircuitDesign) -> str:
    index = build_net_index(design)
    supplies = sorted(index.power_nets)
    return supplies[0] if supplies else "VCC / positive supply"


def _equipment(design: CircuitDesign, needs_scope: bool) -> list[EquipmentItem]:
    has_caps = any(is_capacitor(component) for component in design.components)
    has_ics = any(is_ic_like(component) for component in design.components)
    supply = design.supply_voltage_v

    items = [
        EquipmentItem(
            name="Regulated DC power supply",
            specification=(
                f"Adjustable 0–{max(supply * 2, supply + 2):g} V, adjustable current limit"
                if supply
                else "Adjustable voltage with current limit"
            ),
            reason="Provides a controlled, current-limited supply for first power-on.",
            required=True,
        ),
        EquipmentItem(
            name="Digital multimeter",
            specification=(
                "DC voltage, DC current, resistance and continuity; probe rating "
                "suitable for the declared voltage"
            ),
            reason="Used for rail, node, current and continuity measurements.",
            required=True,
        ),
    ]

    if len(design.components) > 1:
        items.extend(
            [
                EquipmentItem(
                    name="Breadboard",
                    specification="Solderless breadboard with separate power rails",
                    reason="Prototype assembly without soldering.",
                    required=True,
                ),
                EquipmentItem(
                    name="Jumper wires",
                    specification="Insulated, colour-coded, appropriate current rating",
                    reason="Connect components and make temporary test connections.",
                    required=True,
                ),
            ]
        )

    if has_caps or any(is_resistor(component) for component in design.components):
        items.append(
            EquipmentItem(
                name="LCR meter or component tester (optional)",
                specification="Resistance/capacitance measurement",
                reason="Verify declared passive values before assembly.",
                required=False,
            )
        )

    if has_ics:
        items.append(
            EquipmentItem(
                name="Anti-static wrist strap (optional)",
                reason="Reduce ESD risk while handling integrated circuits.",
                required=False,
            )
        )

    if needs_scope:
        items.append(
            EquipmentItem(
                name="Oscilloscope",
                specification="Bandwidth and probe rating adequate for the expected signal",
                reason=(
                    "Observe waveform shape and measure frequency; a multimeter is not "
                    "sufficient for an oscillator or PWM output."
                ),
                required=design.target_frequency_hz is not None,
            )
        )

    items.append(
        EquipmentItem(
            name="Manufacturer datasheets",
            reason=(
                "Required to confirm pinouts, absolute maximum ratings, LED forward "
                "voltage and capacitor polarity. The design data alone is not enough."
            ),
            required=True,
        )
    )
    return items


def _pre_power_checks(
    design: CircuitDesign,
    red_team_report: RedTeamReport | None,
) -> list[PrePowerCheck]:
    supply = design.supply_voltage_v
    ground = _ground_reference(design)
    supply_net = _supply_reference(design)

    values = [
        f"{component.reference}={component.value}"
        for component in design.components
        if component.value and (is_resistor(component) or is_capacitor(component))
    ]
    polarized = [
        f"{component.reference} ({component.name})"
        for component in design.components
        if is_diode(component) or is_led(component) or "electrolytic" in component.name.lower()
    ]
    ics = [
        f"{component.reference} ({component.name})"
        for component in design.components
        if is_ic_like(component)
    ]

    checks = [
        PrePowerCheck(
            step_number=1,
            description="Inspect the assembly against the declared component list and nets.",
            how_to_verify=(
                "Place every component on the breadboard, confirm each reference "
                "designator and trace every declared net. Do not add connections that "
                "are not in the design."
            ),
            critical=True,
        ),
        PrePowerCheck(
            step_number=2,
            description=(
                "Verify the power supply is set correctly before connecting the circuit."
            ),
            how_to_verify=(
                (f"Set the supply to {supply:g} V DC. " if supply else "")
                + "Set a low current limit. Measure the supply output with the multimeter "
                "before connecting it to the circuit."
            ),
            critical=True,
        ),
        PrePowerCheck(
            step_number=3,
            description="Check for a short between the positive supply and ground.",
            how_to_verify=(
                f"With the circuit unpowered, measure resistance between {supply_net} and "
                f"{ground}. A near-zero reading indicates a short or a very low-resistance "
                "path; stop and inspect before applying power. Do not assume a threshold "
                "without knowing the designed load."
            ),
            critical=True,
        ),
    ]

    if values:
        checks.append(
            PrePowerCheck(
                step_number=len(checks) + 1,
                description="Verify declared passive component values.",
                how_to_verify=(
                    "Measure resistors and capacitors with a meter where practical and "
                    "compare with: " + ", ".join(values) + ". Confirm tolerances."
                ),
                critical=False,
            )
        )

    if polarized:
        checks.append(
            PrePowerCheck(
                step_number=len(checks) + 1,
                description="Verify polarity and orientation of every polarized part.",
                how_to_verify=(
                    "Check the datasheet and package marking for: "
                    + ", ".join(polarized)
                    + ". LEDs: anode/cathode. Diodes: stripe/cathode. Electrolytic "
                    "capacitors: polarity stripe and negative marking."
                ),
                critical=True,
            )
        )

    if ics:
        checks.append(
            PrePowerCheck(
                step_number=len(checks) + 1,
                description="Verify IC orientation, pin 1 and package pin numbering.",
                how_to_verify=(
                    "Confirm the notch/dot and pin-1 marking for: "
                    + ", ".join(ics)
                    + ". Compare against the manufacturer datasheet, not only the "
                    "reference designator."
                ),
                critical=True,
            )
        )

    checks.append(
        PrePowerCheck(
            step_number=len(checks) + 1,
            description="Inspect for loose wires, solder bridges and incomplete connections.",
            how_to_verify=(
                "Gently tug each jumper, inspect adjacent breadboard rows, and confirm "
                "that no component leg is shorting to a neighbouring row."
            ),
            critical=False,
        )
    )

    if red_team_report and red_team_report.findings:
        high = [
            finding
            for finding in red_team_report.findings
            if finding.severity.value in {"CRITICAL", "HIGH"}
        ]
        if high:
            checks.append(
                PrePowerCheck(
                    step_number=len(checks) + 1,
                    description="Resolve Red-Team CRITICAL/HIGH findings before power-on.",
                    how_to_verify=(
                        "Review the Red-Team tab and resolve: "
                        + "; ".join(finding.description for finding in high[:5])
                        + (" ..." if len(high) > 5 else "")
                        + ". Do not power a circuit with an unresolved critical finding."
                    ),
                    critical=True,
                )
            )

    return checks


def _measurement_points(
    design: CircuitDesign,
    needs_scope: bool,
) -> list[MeasurementPoint]:
    index = build_net_index(design)
    ground = _ground_reference(design)
    supply_net = _supply_reference(design)
    points: list[MeasurementPoint] = []
    counter = 1

    def add(**kwargs: Any) -> None:
        nonlocal counter
        points.append(
            MeasurementPoint(point_id=f"M{counter}", **kwargs)
        )
        counter += 1

    if design.supply_voltage_v is not None:
        add(
            description="Positive supply rail voltage",
            measurement_location=f"{supply_net} relative to {ground}",
            reference_ground=ground,
            instrument="Multimeter",
            measurement_mode="DC voltage",
            expected_result=(
                f"{design.supply_voltage_v:g} V ± the supply's specified tolerance "
                "(declared design target, not a measured result)"
            ),
            expected_result_basis="design_target",
            is_calculated=False,
            abnormal_indication=(
                "0 V indicates no supply, a blown fuse, an open connection or a reversed "
                "probe. A value well above the set voltage indicates a supply fault. "
                "A sagging rail may indicate excessive load or a current limit."
            ),
            reason="Confirms that the correct rail reaches the circuit before probing signals.",
        )

    add(
        description="Ground continuity",
        measurement_location=(
            f"Between the supply return and each declared {ground} point"
        ),
        reference_ground=ground,
        instrument="Multimeter",
        measurement_mode="Continuity / resistance",
        expected_result=(
            "Continuity with a low resistance (verify against the designed current path); "
            "0 V between ground points when powered"
        ),
        expected_result_basis="requires_verification",
        is_calculated=False,
        abnormal_indication=(
            "No continuity indicates a broken return path. Continuity where the design "
            "does not call for it may indicate an unintended short."
        ),
        reason="Verifies that the common return is complete before power is applied.",
        safety_note="Perform this measurement with the circuit unpowered.",
    )

    add(
        description="Total supply current",
        measurement_location=(
            f"Power supply current display, or a multimeter in series with the {supply_net} feed"
        ),
        reference_ground=ground,
        instrument="Multimeter",
        measurement_mode="DC current (series only)",
        expected_result="Requires calculation or datasheet confirmation",
        expected_result_basis="requires_verification",
        is_calculated=False,
        abnormal_indication=(
            "Current at or above the set limit, rapidly rising current, or heating "
            "indicates a wiring fault, reversed polarity or a damaged component. "
            "Switch off immediately."
        ),
        reason=(
            "Establishes whether the circuit draws a plausible current before signal "
            "measurements. The expected current is not known until component operating "
            "currents are calculated or measured."
        ),
        safety_note=(
            "Never connect the meter in current mode across a component. Break the "
            "circuit with the power off, connect the ammeter in series, then power up."
        ),
    )

    # Unambiguous two-resistor divider outputs are calculated.
    for divider in find_voltage_dividers(design):
        add(
            description=(
                f"Divider output on net '{divider.output_net}' "
                f"({divider.top_reference}/{divider.bottom_reference})"
            ),
            measurement_location=(
                f"{divider.output_net} relative to {divider.ground_net}"
            ),
            reference_ground=divider.ground_net,
            instrument="Multimeter",
            measurement_mode="DC voltage",
            expected_result=(
                f"≈ {divider.output_voltage_v:.3f} V unloaded, calculated from "
                f"{resistance_label(divider.top_ohms)} and "
                f"{resistance_label(divider.bottom_ohms)}. Loading, tolerance and "
                "supply tolerance will change this value."
            ),
            expected_result_basis="calculated",
            is_calculated=True,
            abnormal_indication=(
                "A large deviation indicates wrong resistor values, a missing connection, "
                "an unintended load, or a supply-voltage error."
            ),
            reason=(
                "Checks the only node voltage that can be calculated unambiguously from "
                "the declared resistor values."
            ),
        )

    # LED current can only be calculated when the forward voltage is declared.
    resistor_refs = {
        component.reference for component in design.components if is_resistor(component)
    }
    for led in (component for component in design.components if is_led(component)):
        resistor_ref = find_series_resistor(index, led.reference, resistor_refs)
        if resistor_ref:
            resistor = next(
                component
                for component in design.components
                if component.reference == resistor_ref
            )
            resistance = parse_resistance(resistor.value)
            calculated_current: float | None = None
            if (
                resistance
                and resistance > 0
                and design.supply_voltage_v is not None
                and led.forward_voltage_v is not None
                and led.forward_voltage_v < design.supply_voltage_v
            ):
                calculated_current = (
                    design.supply_voltage_v - led.forward_voltage_v
                ) / resistance

            if calculated_current is not None:
                expected = (
                    f"≈ {calculated_current * 1000:.2f} mA, calculated from the "
                    f"declared supply ({design.supply_voltage_v:g} V), declared LED "
                    f"forward voltage ({led.forward_voltage_v:g} V) and "
                    f"{resistor_ref} ({resistance_label(resistance)}). Real current "
                    "changes with LED forward-voltage spread, resistor tolerance and "
                    "supply tolerance."
                )
                basis = "calculated"
                is_calculated = True
            else:
                missing = []
                if not resistance:
                    missing.append(f"{resistor_ref} resistance value")
                if led.forward_voltage_v is None:
                    missing.append(f"{led.reference} forward voltage")
                detail = (
                    " Missing: " + ", ".join(missing) + "."
                    if missing
                    else " The declared forward voltage is not below the supply."
                )
                expected = (
                    "Requires calculation or datasheet confirmation: "
                    "I = (Vsupply − Vf) / R." + detail
                )
                basis = "requires_verification"
                is_calculated = False

            add(
                description=f"Current through {led.reference}",
                measurement_location=(
                    f"Voltage across {resistor_ref}, or LED branch current in series"
                ),
                reference_ground=ground,
                instrument="Multimeter",
                measurement_mode=(
                    "DC voltage across resistor (preferred) or DC current in series"
                ),
                expected_result=expected,
                expected_result_basis=basis,
                is_calculated=is_calculated,
                abnormal_indication=(
                    "No current indicates an open path or reversed LED. Excessive current "
                    "or a hot resistor indicates the resistance is too low for the LED."
                ),
                reason="Confirms the LED is biased at a safe, intended current.",
                safety_note=(
                    "Do not use current mode across the resistor. Measure voltage and "
                    "calculate current, or break the circuit and use series current mode."
                ),
            )
        else:
            add(
                description=f"Current through {led.reference}",
                measurement_location=f"{led.reference} branch",
                reference_ground=ground,
                instrument="Multimeter",
                measurement_mode="DC current (series only)",
                expected_result=(
                    "Requires calculation or datasheet confirmation. No series resistor "
                    "was identified; do not power the circuit until this is resolved."
                ),
                expected_result_basis="requires_verification",
                is_calculated=False,
                abnormal_indication=(
                    "Any significant current without a series resistor indicates the LED "
                    "is being over-driven."
                ),
                reason="The LED current path is incomplete or unprotected in the design data.",
                safety_note="Resolve the missing current-limiting resistor before power-on.",
            )

    if needs_scope and design.target_frequency_hz is not None:
        add(
            description="Oscillator / timing output",
            measurement_location=(
                "Declared output or timing net (identify from the schematic; do not "
                "guess an unconnected pin)"
            ),
            reference_ground=ground,
            instrument="Oscilloscope",
            measurement_mode="Time domain, DC or AC coupling as appropriate",
            expected_result=(
                f"Design target: {design.target_frequency_hz:g} Hz. The frequency was "
                "not simulated. Confirm amplitude and waveform against the intended "
                "output specification."
            ),
            expected_result_basis="design_target",
            is_calculated=False,
            abnormal_indication=(
                "No oscillation, wrong frequency, unstable period, clipping or excessive "
                "distortion indicates incorrect timing values, supply problems, a missing "
                "connection or a damaged IC."
            ),
            reason="Verifies the requested timing behavior on the bench.",
            safety_note=(
                "Connect the scope ground clip only to the circuit ground. Never clip it "
                "to a live node."
            ),
        )

    # Remaining named nets get an explicitly uncalculated connectivity check.
    skip_nets = {ground, supply_net}
    divider_nets = {
        divider.output_net for divider in find_voltage_dividers(design)
    }
    signal_nets = [
        name
        for name in sorted(index.net_to_pins)
        if name not in skip_nets and name not in divider_nets
    ]
    for net_name in signal_nets[:4]:
        if any(
            point.measurement_location.startswith(f"{net_name} ")
            or point.measurement_location == net_name
            for point in points
        ):
            continue
        add(
            description=f"Node voltage on net '{net_name}'",
            measurement_location=f"{net_name} relative to {ground}",
            reference_ground=ground,
            instrument="Multimeter",
            measurement_mode="DC voltage",
            expected_result="Requires calculation or datasheet confirmation",
            expected_result_basis="requires_verification",
            is_calculated=False,
            abnormal_indication=(
                "An unexpected value indicates a wiring error, missing connection, wrong "
                "component value, or a circuit condition not represented in the design data."
            ),
            reason=(
                "Confirms connectivity and bias for a declared net. The expected voltage "
                "cannot be calculated from the available design data."
            ),
        )

    if not points:
        add(
            description="Supply and ground presence",
            measurement_location="Supply input relative to the common return",
            reference_ground=ground,
            instrument="Multimeter",
            measurement_mode="DC voltage",
            expected_result="Requires calculation or datasheet confirmation",
            expected_result_basis="requires_verification",
            is_calculated=False,
            abnormal_indication="Any unexpected voltage requires investigation before use.",
            reason="The design does not declare enough information for a specific measurement.",
        )
    return points


def _test_sequence(
    design: CircuitDesign,
    needs_scope: bool,
) -> list[TestStep]:
    supply = design.supply_voltage_v
    ground = _ground_reference(design)
    supply_net = _supply_reference(design)
    steps = [
        TestStep(
            step_number=1,
            title="Inspect the unpowered assembly",
            description=(
                "Compare the physical build with the declared components and nets. "
                "Confirm every reference designator, pin connection and polarity marking."
            ),
            expected_outcome="The build matches the structured design and no connection is improvised.",
            safety_precaution="Keep the supply disconnected throughout this step.",
        ),
        TestStep(
            step_number=2,
            title="Verify component values and ratings",
            description=(
                "Measure passive values where practical and confirm IC, LED and capacitor "
                "markings against datasheets. Confirm voltage ratings exceed the supply."
            ),
            expected_outcome="Measured values match the BOM within the stated tolerance.",
        ),
        TestStep(
            step_number=3,
            title="Set the supply and current limit",
            description=(
                (f"Set the supply to {supply:g} V DC. " if supply else "")
                + "Start with a low current limit. Measure the supply output before "
                "connecting it to the circuit."
            ),
            expected_outcome="The supply output matches the intended voltage before connection.",
            safety_precaution="Do not connect an unverified supply directly to the circuit.",
        ),
        TestStep(
            step_number=4,
            title="Perform unpowered checks",
            description=(
                f"Check continuity and resistance between {supply_net} and {ground}, "
                "and confirm that each declared net is continuous. Investigate any "
                "unexpected near-zero path."
            ),
            expected_outcome="No unintended short is found; declared nets are continuous.",
            safety_precaution="The circuit must be unpowered and capacitors discharged.",
        ),
        TestStep(
            step_number=5,
            title="Apply power with current limiting",
            description=(
                "Connect the supply and observe the current reading before touching "
                "the circuit. If the supply enters current limit, switch off immediately."
            ),
            expected_outcome="Current is stable and below the set limit; no heating, smell or smoke.",
            safety_precaution=(
                "Switch off immediately on excessive current, smell, smoke or heat. "
                "Do not touch the circuit while it is powered."
            ),
        ),
        TestStep(
            step_number=6,
            title="Measure the supply and ground rails",
            description=(
                f"Measure {supply_net} to {ground}, then verify the ground reference "
                "at more than one point. Record the measured value."
            ),
            expected_outcome=(
                f"{supply:g} V on the supply rail and 0 V on the ground reference, "
                "within the supply's tolerance."
                if supply
                else "The measured rail matches the intended supply."
            ),
        ),
        TestStep(
            step_number=7,
            title="Measure the declared signal nodes",
            description=(
                "Work through the measurement points in order. Record every measured "
                "value and note whether it is calculated, a design target, or unknown."
            ),
            expected_outcome="Every measurement is recorded; deviations are investigated.",
            safety_precaution="Power off before changing probe placement on exposed wiring.",
        ),
    ]

    if any(is_led(component) for component in design.components):
        steps.append(
            TestStep(
                step_number=len(steps) + 1,
                title="Verify LED operating current",
                description=(
                    "Measure the voltage across the series resistor and calculate "
                    "I = V_R / R, or use a series ammeter. Compare with the LED datasheet."
                ),
                expected_outcome="LED illuminates at a current within its datasheet rating.",
                safety_precaution="Do not exceed the LED's rated forward current.",
            )
        )

    if needs_scope and design.target_frequency_hz is not None:
        steps.append(
            TestStep(
                step_number=len(steps) + 1,
                title="Verify timing behavior",
                description=(
                    "Connect the oscilloscope to the declared output/timing node. "
                    "Measure frequency, amplitude and waveform shape."
                ),
                expected_outcome=(
                    f"Output is close to the {design.target_frequency_hz:g} Hz design target "
                    "and has the intended waveform; this is a bench measurement, not a simulation."
                ),
                safety_precaution="Scope ground clip to circuit ground only.",
            )
        )

    if find_voltage_dividers(design):
        steps.append(
            TestStep(
                step_number=len(steps) + 1,
                title="Verify divider output",
                description=(
                    "Measure the calculated divider output before connecting a load. "
                    "Record the unloaded and loaded values separately."
                ),
                expected_outcome="Unloaded output is close to the calculated value; loading effects are documented.",
            )
        )

    steps.append(
        TestStep(
            step_number=len(steps) + 1,
            title="Record results and power down",
            description=(
                "Record measured values, instrument settings and any deviation from the "
                "predicted/declared values. Power off, disconnect the supply and discharge "
                "capacitors before changing wiring."
            ),
            expected_outcome="A complete measurement record exists and the circuit is safely powered down.",
            safety_precaution="Power off and discharge stored energy before touching the circuit.",
        )
    )
    return steps


def _troubleshooting(
    design: CircuitDesign,
    needs_scope: bool,
) -> list[TroubleshootingEntry]:
    entries: list[TroubleshootingEntry] = []
    has_led = any(is_led(component) for component in design.components)
    has_oscillator = any(
        any(
            keyword in component.name.lower()
            for keyword in ("oscillator", "timer", "555", "crystal", "resonator")
        )
        for component in design.components
    ) or design.target_frequency_hz is not None
    has_divider = bool(find_voltage_dividers(design))
    has_ics = any(is_ic_like(component) for component in design.components)

    entries.append(
        TroubleshootingEntry(
            symptom="No output / circuit does not function",
            possible_causes=[
                "Supply not connected, reversed or below the required voltage",
                "Missing ground/return connection",
                "Component inserted in the wrong breadboard row",
                "Wrong or missing component value",
                "Damaged component or reversed polarity",
                "Red-Team finding not resolved before power-on",
            ],
            diagnostic_actions=[
                "Power off and inspect the supply and ground rails.",
                "Measure the supply at the circuit input, not only at the supply terminals.",
                "Compare the physical build with the declared nets, pin by pin.",
                "Verify component values and orientation against datasheets.",
                "Review the Red-Team findings for unresolved critical/high issues.",
            ],
        )
    )

    if has_led:
        entries.append(
            TroubleshootingEntry(
                symptom="LED does not illuminate",
                possible_causes=[
                    "LED reversed (anode/cathode swapped)",
                    "No series resistor or an open resistor connection",
                    "Insufficient supply voltage for the LED forward voltage",
                    "LED damaged by previous over-current",
                    "Driver output not switching",
                ],
                diagnostic_actions=[
                    "Power off and confirm LED orientation against the datasheet.",
                    "Measure the voltage across the series resistor; calculate current.",
                    "Measure the voltage at both LED pins relative to ground.",
                    "If the LED is suspect, test it with a known current-limited source.",
                ],
            )
        )

    if has_oscillator:
        entries.append(
            TroubleshootingEntry(
                symptom="Oscillator does not oscillate or frequency is wrong",
                possible_causes=[
                    "Timing resistor/capacitor value incorrect",
                    "Wrong IC variant or pinout",
                    "Missing supply, ground or discharge connection",
                    "Load capacitance or probe loading affecting the oscillator",
                    "Damaged IC or counterfeit part",
                ],
                diagnostic_actions=[
                    "Confirm the timing component values and the oscillator topology.",
                    "Verify the IC marking, pin 1 and pin functions against the datasheet.",
                    "Measure supply and ground at the IC pins, not at the breadboard rail.",
                    "Measure the output with a scope and compare with the design target.",
                ],
            )
        )

    entries.extend(
        [
            TroubleshootingEntry(
                symptom="Unexpected supply voltage",
                possible_causes=[
                    "Supply set incorrectly or current limit active",
                    "Reversed probe polarity",
                    "High-resistance connection or breadboard contact",
                    "Excessive load pulling the rail down",
                ],
                diagnostic_actions=[
                    "Measure the supply directly at its output terminals.",
                    "Measure the rail at the circuit input and at the IC power pin.",
                    "Power off and inspect the supply path for loose wires.",
                    "Confirm supply polarity before reconnecting.",
                ],
            ),
            TroubleshootingEntry(
                symptom="Excessive current consumption / supply current limit",
                possible_causes=[
                    "Supply-to-ground short",
                    "Reversed polarized component",
                    "LED without a current-limiting resistor",
                    "Wrong component value or incorrect pinout",
                    "Damaged component",
                ],
                diagnostic_actions=[
                    "Switch off immediately and disconnect the supply.",
                    "Measure resistance between supply and ground with the circuit unpowered.",
                    "Inspect polarized components and the LED current path.",
                    "Remove components section by section only with the power off, then re-check.",
                ],
            ),
        ]
    )

    if has_ics:
        entries.append(
            TroubleshootingEntry(
                symptom="IC becomes hot or behaves erratically",
                possible_causes=[
                    "Supply reversed or connected to the wrong pin",
                    "Output shorted to ground or supply",
                    "Missing ground or decoupling",
                    "Input voltage outside the allowed range",
                    "Damaged or counterfeit IC",
                ],
                diagnostic_actions=[
                    "Switch off and allow the part to cool before touching it.",
                    "Verify pin 1, supply and ground against the datasheet.",
                    "Check for shorts on output and input pins with the power off.",
                    "Replace the IC only after confirming the surrounding circuit is correct.",
                ],
            )
        )

    if needs_scope:
        entries.append(
            TroubleshootingEntry(
                symptom="Output waveform is distorted or unstable",
                possible_causes=[
                    "Scope probe compensation or grounding problem",
                    "Insufficient supply decoupling",
                    "Timing component tolerance or wrong value",
                    "Load too heavy for the output stage",
                    "Breadboard parasitic capacitance/inductance",
                ],
                diagnostic_actions=[
                    "Compensate the probe and use the shortest possible ground lead.",
                    "Measure the supply rail at the IC with the scope on AC coupling.",
                    "Confirm timing values and supply voltage.",
                    "Test with the intended load and record the difference.",
                ],
            )
        )

    if has_divider:
        entries.append(
            TroubleshootingEntry(
                symptom="Divider output differs from the calculated value",
                possible_causes=[
                    "Wrong resistor value or tolerance",
                    "Unintended load on the divider output",
                    "Supply voltage different from the declared value",
                    "Missing ground or open connection",
                ],
                diagnostic_actions=[
                    "Power off and measure both resistors.",
                    "Measure the supply rail and the divider output unloaded.",
                    "Confirm the load and re-calculate with the actual supply voltage.",
                ],
            )
        )
    return entries


def build_deterministic_procedure(
    design: CircuitDesign,
    red_team_report: RedTeamReport | None = None,
) -> LabProcedure:
    """Build a complete procedure without any LLM involvement."""
    needs_scope = _requires_oscilloscope(design)
    return LabProcedure(
        circuit_name=design.project_name,
        supply_voltage_v=design.supply_voltage_v,
        required_components=_required_components(design),
        equipment=_equipment(design, needs_scope),
        pre_power_checks=_pre_power_checks(design, red_team_report),
        measurement_points=_measurement_points(design, needs_scope),
        test_sequence=_test_sequence(design, needs_scope),
        troubleshooting=_troubleshooting(design, needs_scope),
        safety_notes=get_safety_notes(design, needs_oscilloscope=needs_scope),
        generation_mode="deterministic",
        ai_assisted=False,
        design_fingerprint=design_fingerprint(design),
        generation_notes=[
            "Procedure derived deterministically from the structured design.",
            "No simulation, ERC or physical measurement was performed.",
            "Values marked 'Requires calculation or datasheet confirmation' were not "
            "calculated because the required data was not supplied.",
        ],
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n\s*```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("No JSON object found in AI response.")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI response was not a JSON object.")
    return payload


class VirtualLabGenerator:
    """Generates a LabProcedure from a CircuitDesign."""

    def __init__(
        self,
        settings: Settings | None = None,
        enable_ai: bool | None = None,
    ):
        self.settings = settings
        if enable_ai is None:
            enable_ai = bool(settings and settings.enable_ai_virtual_lab)
        self.enable_ai = enable_ai
        self._client = None

    def _get_client(self):
        if self._client is None:
            if self.settings is None:
                raise RuntimeError("No provider settings are available.")
            from services.llm_client import OpenAICompatibleClient

            self._client = OpenAICompatibleClient(self.settings)
        return self._client

    def _merge_ai(
        self,
        base: LabProcedure,
        design: CircuitDesign,
        red_team_report: RedTeamReport | None,
    ) -> LabProcedure:
        try:
            client = self._get_client()
            user_prompt = (
                "Circuit design:\n"
                + json.dumps(design.model_dump(mode="json"), indent=2)
                + "\n\nExisting deterministic procedure (do not repeat):\n"
                + json.dumps(
                    {
                        "equipment": [item.name for item in base.equipment],
                        "pre_power_checks": [
                            check.description for check in base.pre_power_checks
                        ],
                        "measurement_points": [
                            point.description for point in base.measurement_points
                        ],
                        "troubleshooting": [
                            entry.symptom for entry in base.troubleshooting
                        ],
                    },
                    indent=2,
                )
            )
            if red_team_report:
                user_prompt += (
                    "\n\nOpen Red-Team findings:\n"
                    + json.dumps(
                        [
                            {
                                "severity": finding.severity.value,
                                "description": finding.description,
                            }
                            for finding in red_team_report.findings[:12]
                        ],
                        indent=2,
                    )
                )
            response = client.complete(_SYSTEM_PROMPT, user_prompt)
            payload = _extract_json_object(response)
        except Exception as exc:
            logger.warning("Virtual Lab AI enhancement failed: %s", exc)
            base.generation_notes.append(f"AI enhancement unavailable: {str(exc)[:200]}")
            return base

        existing_equipment = {item.name.lower() for item in base.equipment}
        for item in payload.get("equipment", [])[:6]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name or name.lower() in existing_equipment:
                continue
            base.equipment.append(
                EquipmentItem(
                    name=name[:120],
                    specification=(
                        str(item.get("specification"))[:200]
                        if item.get("specification")
                        else None
                    ),
                    reason=str(item.get("reason", "AI-suggested item"))[:400],
                    required=False,
                    is_ai_generated=True,
                )
            )
            existing_equipment.add(name.lower())

        for item in payload.get("pre_power_checks", [])[:6]:
            if not isinstance(item, dict) or not item.get("description"):
                continue
            base.pre_power_checks.append(
                PrePowerCheck(
                    step_number=len(base.pre_power_checks) + 1,
                    description=str(item["description"])[:400],
                    how_to_verify=str(item.get("how_to_verify", ""))[:600],
                    critical=False,
                    is_ai_generated=True,
                )
            )

        allowed_instruments = {
            "Multimeter",
            "Oscilloscope",
            "Current Probe",
            "Power Supply",
            "Frequency Counter",
        }
        for index, item in enumerate(payload.get("measurement_points", [])[:6], start=1):
            if not isinstance(item, dict) or not item.get("description"):
                continue
            instrument = str(item.get("instrument", "Multimeter"))
            if instrument not in allowed_instruments:
                instrument = "Multimeter"
            raw_expected = str(item.get("expected_result", "")).strip()
            if not raw_expected or "requires calculation" in raw_expected.lower():
                expected = "Requires calculation or datasheet confirmation"
            else:
                expected = (
                    f"AI-suggested, UNVERIFIED: {raw_expected} — confirm by calculation, "
                    "datasheet and measurement"
                )
            base.measurement_points.append(
                MeasurementPoint(
                    point_id=f"AI-{index:02d}",
                    description=str(item["description"])[:300],
                    measurement_location=str(
                        item.get("measurement_location", "Identify from the schematic")
                    )[:300],
                    reference_ground=str(
                        item.get("reference_ground", _ground_reference(design))
                    )[:120],
                    instrument=instrument,
                    measurement_mode=str(item.get("measurement_mode", "As appropriate"))[:200],
                    expected_result=expected[:600],
                    expected_result_basis="ai_suggested",
                    is_calculated=False,
                    is_ai_generated=True,
                    abnormal_indication=str(
                        item.get("abnormal_indication", "Investigate any unexpected reading.")
                    )[:600],
                    reason=str(item.get("reason", "AI-suggested measurement"))[:600],
                    safety_note=(
                        str(item["safety_note"])[:400]
                        if item.get("safety_note")
                        else None
                    ),
                )
            )

        existing_symptoms = {entry.symptom.lower() for entry in base.troubleshooting}
        for item in payload.get("troubleshooting", [])[:6]:
            if not isinstance(item, dict) or not item.get("symptom"):
                continue
            symptom = str(item["symptom"]).strip()
            if not symptom or symptom.lower() in existing_symptoms:
                continue
            causes = [str(value)[:300] for value in item.get("possible_causes", [])][:8]
            actions = [str(value)[:300] for value in item.get("diagnostic_actions", [])][:8]
            if not causes or not actions:
                continue
            base.troubleshooting.append(
                TroubleshootingEntry(
                    symptom=symptom[:200],
                    possible_causes=causes,
                    diagnostic_actions=actions,
                    is_ai_generated=True,
                )
            )
            existing_symptoms.add(symptom.lower())

        for note in payload.get("notes", [])[:6]:
            text = str(note).strip()
            if text:
                base.generation_notes.append(f"AI contextual note: {text[:400]}")

        base.generation_mode = "ai_assisted"
        base.ai_assisted = True
        base.generation_notes.append(
            "AI contextual items are marked 'AI' and are unverified. Calculated and "
            "requirement-derived values were retained from the deterministic procedure."
        )
        return base

    def generate(
        self,
        design: CircuitDesign,
        red_team_report: RedTeamReport | None = None,
        use_ai: bool | None = None,
    ) -> LabProcedure:
        """Generate a procedure. Deterministic by default when AI is unavailable."""
        base = build_deterministic_procedure(design, red_team_report)
        if use_ai is None:
            use_ai = self.enable_ai
        if not use_ai:
            return base
        return self._merge_ai(base, design, red_team_report)
