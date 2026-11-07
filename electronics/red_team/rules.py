"""Deterministic rule functions for Circuit Red-Team.

All functions operate without an LLM. Each finding states how it was produced
(``verification_status``) and where its component data came from
(``data_provenance``). No rule claims simulation, ERC or safety certification.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from electronics.calculations import (
    component_resistance,
    direct_supply_current,
    direct_supply_power,
    find_voltage_dividers,
    led_worst_case_current,
    led_worst_case_resistor_power,
)
from electronics.netinfo import (
    build_net_index,
    find_series_resistor,
    is_capacitor,
    is_diode,
    is_ic_like,
    is_inductive_load,
    is_led,
    is_polarized_capacitor,
    is_resistor,
    net_voltage_hint,
)
from electronics.red_team.models import (
    DataProvenance,
    FindingCategory,
    FindingSeverity,
    RedTeamFinding,
)
from electronics.values import (
    parse_capacitance,
    parse_resistance,
    power_label,
    resistance_label,
)
from schemas.circuit import CircuitDesign, Component

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fid(rule_code: str, *parts: str | int | None) -> str:
    cleaned: list[str] = [rule_code]
    for part in parts:
        if part is None:
            continue
        token = re.sub(r"[^A-Z0-9]+", "-", str(part).upper()).strip("-")
        if token:
            cleaned.append(token[:20])
    return ("RT-" + "-".join(cleaned))[:72]


def _provenance(component: Component | None) -> DataProvenance:
    if component is None:
        return "not_applicable"
    if component.evidence_status in {"verified", "user_supplied"}:
        return component.evidence_status  # type: ignore[return-value]
    return "unverified"


def _finding(
    rule_code: str,
    *,
    category: FindingCategory,
    severity: FindingSeverity,
    description: str,
    engineering_reason: str,
    evidence: str,
    recommended_action: str,
    component_reference: str | None = None,
    affected_pins: list[str] | None = None,
    confidence: float = 1.0,
    verification_status: str = "DETERMINISTIC",
    data_provenance: DataProvenance = "not_applicable",
    requires_measurement: bool = False,
    identity_parts: tuple[str | int | None, ...] = (),
) -> RedTeamFinding:
    return RedTeamFinding(
        finding_id=_fid(rule_code, component_reference, *identity_parts),
        rule_code=rule_code,
        category=category,
        severity=severity,
        component_reference=component_reference,
        affected_pins=affected_pins or [],
        description=description,
        engineering_reason=engineering_reason,
        evidence=evidence,
        recommended_action=recommended_action,
        confidence=max(0.0, min(1.0, confidence)),
        verification_status=verification_status,  # type: ignore[arg-type]
        data_provenance=data_provenance,
        requires_measurement=requires_measurement,
    )


def _non_led_diode(component: Component) -> bool:
    return is_diode(component) and not is_led(component)


# ---------------------------------------------------------------------------
# A. Power integrity
# ---------------------------------------------------------------------------


def check_supply_voltage_declared(design: CircuitDesign) -> list[RedTeamFinding]:
    if design.supply_voltage_v is not None:
        return []
    return [
        _finding(
            "PWR-01",
            category=FindingCategory.POWER_INTEGRITY,
            severity=FindingSeverity.MEDIUM,
            description="No supply voltage is declared for this design.",
            engineering_reason=(
                "Without a declared supply voltage, component voltage ratings, "
                "power dissipation, net-name consistency and many lab measurements "
                "cannot be checked. Every downstream rating check is skipped."
            ),
            evidence="design.supply_voltage_v is None",
            recommended_action=(
                "Declare the intended regulated supply voltage (for example 3.3 V, "
                "5 V, 9 V or 12 V) and whether it is DC or AC before finalizing the design."
            ),
            verification_status="DETERMINISTIC",
            data_provenance="not_applicable",
        )
    ]


def check_no_ground_net(design: CircuitDesign) -> list[RedTeamFinding]:
    if not design.connections:
        return []
    index = build_net_index(design)
    if index.ground_nets:
        return []
    net_names = sorted(index.net_to_pins)
    return [
        _finding(
            "PWR-02",
            category=FindingCategory.POWER_INTEGRITY,
            severity=FindingSeverity.HIGH,
            description="No ground / return net is declared.",
            engineering_reason=(
                "Every active circuit needs a common reference and a return path for "
                "current. Without a ground net, supply and signal voltages are undefined "
                "and the declared connectivity is incomplete."
            ),
            evidence=f"Declared nets: {net_names[:12]} (none match GND/VSS/0V patterns).",
            recommended_action=(
                "Add a ground net and connect the supply return and every required "
                "component ground pin to it. Verify the connector pinout."
            ),
            confidence=0.95,
            verification_status="DETERMINISTIC",
            data_provenance="not_applicable",
        )
    ]


def check_no_power_net(design: CircuitDesign) -> list[RedTeamFinding]:
    if not design.connections or design.supply_voltage_v is None:
        return []
    index = build_net_index(design)
    if index.ground_nets == set(index.net_to_pins):
        return []
    if index.power_nets:
        return []
    net_names = sorted(index.net_to_pins)
    return [
        _finding(
            "PWR-03",
            category=FindingCategory.POWER_INTEGRITY,
            severity=FindingSeverity.MEDIUM,
            description="No recognizable supply net (VCC/VDD/VIN) is declared.",
            engineering_reason=(
                "A supply voltage is declared but no net name identifies the positive "
                "rail. Either the schematic is incomplete or the power connection is "
                "only implied, which makes the design ambiguous."
            ),
            evidence=(
                f"Supply {design.supply_voltage_v} V declared; nets: {net_names[:12]}. "
                "None match a supply-rail pattern."
            ),
            recommended_action=(
                "Add an explicit supply net (for example VCC or VDD), connect every "
                "required power pin and include the supply connector or source."
            ),
            confidence=0.85,
            verification_status="DETERMINISTIC",
            data_provenance="not_applicable",
        )
    ]


def check_ic_supply_and_ground(design: CircuitDesign) -> list[RedTeamFinding]:
    if not design.connections:
        return []
    index = build_net_index(design)
    ground_nets = index.ground_nets
    power_nets = index.power_nets
    if not ground_nets or (design.supply_voltage_v is not None and not power_nets):
        return []

    findings: list[RedTeamFinding] = []
    for component in design.components:
        if not is_ic_like(component):
            continue
        nets = index.nets_for_ref(component.reference)
        if not nets:
            continue
        if not nets & ground_nets:
            findings.append(
                _finding(
                    "PWR-04",
                    category=FindingCategory.POWER_INTEGRITY,
                    severity=FindingSeverity.HIGH,
                    description=(
                        f"{component.reference} ({component.name}) has no declared "
                        "connection to a ground net."
                    ),
                    engineering_reason=(
                        "Integrated circuits require a ground reference. An IC absent "
                        "from the ground net is either wired incorrectly in the model or "
                        "missing a required pin connection."
                    ),
                    evidence=(
                        f"{component.reference} nets: {sorted(nets)}; "
                        f"ground nets: {sorted(ground_nets)}"
                    ),
                    recommended_action=(
                        f"Connect the ground pin(s) of {component.reference} to the "
                        "common ground. Confirm the pinout from the manufacturer datasheet."
                    ),
                    component_reference=component.reference,
                    confidence=0.9,
                    data_provenance=_provenance(component),
                )
            )
        if design.supply_voltage_v is not None and power_nets and not nets & power_nets:
            findings.append(
                _finding(
                    "PWR-05",
                    category=FindingCategory.POWER_INTEGRITY,
                    severity=FindingSeverity.HIGH,
                    description=(
                        f"{component.reference} ({component.name}) has no declared "
                        "connection to a supply net."
                    ),
                    engineering_reason=(
                        "An active IC that is not connected to any declared power rail "
                        "cannot be supplied. This is either a missing connection or a "
                        "missing supply net."
                    ),
                    evidence=(
                        f"{component.reference} nets: {sorted(nets)}; "
                        f"supply nets: {sorted(power_nets)}"
                    ),
                    recommended_action=(
                        f"Connect the supply pin(s) of {component.reference} to the "
                        "correct rail, including any required local decoupling."
                    ),
                    component_reference=component.reference,
                    confidence=0.9,
                    data_provenance=_provenance(component),
                )
            )
    return findings


def check_no_components(design: CircuitDesign) -> list[RedTeamFinding]:
    if design.components:
        return []
    return [
        _finding(
            "PWR-06",
            category=FindingCategory.REQUIREMENT_CONSISTENCY,
            severity=FindingSeverity.HIGH,
            description="No components were identified in the structured design.",
            engineering_reason=(
                "A design without components cannot be reviewed for power, protection, "
                "connectivity or compatibility. The requirements may be incomplete or "
                "the source image/text may not have been interpreted."
            ),
            evidence="design.components is empty",
            recommended_action=(
                "Provide a clear requirement or schematic and confirm component "
                "identification before treating this as a design."
            ),
            verification_status="INCOMPLETE_DATA",
        )
    ]


def check_no_connections(design: CircuitDesign) -> list[RedTeamFinding]:
    if not design.components or design.connections:
        return []
    return [
        _finding(
            "PWR-07",
            category=FindingCategory.CONNECTIVITY,
            severity=FindingSeverity.HIGH,
            description="Components are declared but no electrical connections are declared.",
            engineering_reason=(
                "Without nets, the circuit topology is unknown. Connectivity, supply "
                "and protection checks cannot be performed and the design cannot be built."
            ),
            evidence=f"{len(design.components)} component(s), 0 connections",
            recommended_action=(
                "Declare every net with REF.PIN endpoints, or supply a clearer schematic. "
                "Do not infer connections that are not supported by the source."
            ),
            verification_status="INCOMPLETE_DATA",
        )
    ]


# ---------------------------------------------------------------------------
# B. Component protection
# ---------------------------------------------------------------------------


def check_led_current_limiting(design: CircuitDesign) -> list[RedTeamFinding]:
    index = build_net_index(design)
    leds = [component for component in design.components if is_led(component)]
    if not leds:
        return []
    resistor_refs = {
        component.reference for component in design.components if is_resistor(component)
    }

    findings: list[RedTeamFinding] = []
    for led in leds:
        led_nets = index.nets_for_ref(led.reference)
        if not led_nets:
            continue  # Covered by the unconnected-component rule.
        if len(led_nets) < 2:
            findings.append(
                _finding(
                    "PRT-01",
                    category=FindingCategory.COMPONENT_PROTECTION,
                    severity=FindingSeverity.MEDIUM,
                    description=(
                        f"{led.reference} ({led.name}) has fewer than two declared nets; "
                        "its current path cannot be verified."
                    ),
                    engineering_reason=(
                        "An LED needs an anode-side and cathode-side connection. With "
                        "incomplete pin data, the presence of a series current-limiting "
                        "resistor cannot be confirmed."
                    ),
                    evidence=f"LED nets: {sorted(led_nets)}",
                    recommended_action=(
                        "Declare both LED pins and the complete current path from supply "
                        "through the series resistor to ground."
                    ),
                    component_reference=led.reference,
                    confidence=0.9,
                    verification_status="INCOMPLETE_DATA",
                    data_provenance=_provenance(led),
                )
            )
            continue

        series_resistor = find_series_resistor(index, led.reference, resistor_refs)
        if series_resistor:
            continue

        shared_resistors = sorted(resistor_refs & index.refs_on_same_net(led.reference))
        parallel = [
            reference
            for reference in shared_resistors
            if index.nets_for_ref(reference) >= led_nets
        ]
        if parallel:
            description = (
                f"{led.reference} ({led.name}) shares both of its nets with "
                f"resistor(s) {', '.join(parallel)}; those resistors are in parallel "
                "with the LED, so no series current-limiting resistor is detected."
            )
            evidence = (
                f"LED nets {sorted(led_nets)}; resistor nets "
                f"{ {ref: sorted(index.nets_for_ref(ref)) for ref in parallel} }. "
                "A parallel resistor does not limit the LED current."
            )
            confidence = 0.9
        else:
            description = (
                f"{led.reference} ({led.name}) has no declared series current-limiting "
                "resistor."
            )
            evidence = (
                f"LED nets {sorted(led_nets)}; declared resistors "
                f"{sorted(resistor_refs) or 'none'}. No resistor is in series on the "
                "LED current path."
            )
            confidence = 0.8

        findings.append(
            _finding(
                "PRT-02",
                category=FindingCategory.COMPONENT_PROTECTION,
                severity=FindingSeverity.HIGH,
                description=description,
                engineering_reason=(
                    "An LED is current-controlled. Without a series resistor, current is "
                    "limited only by the supply and the LED's forward characteristic, "
                    "which can destroy the LED and stress the driver. The correct value "
                    "depends on supply voltage, LED forward voltage and the intended "
                    "forward current."
                ),
                evidence=evidence,
                recommended_action=(
                    "Add a series resistor in the LED current path. Calculate "
                    "R = (Vsupply - Vf) / If using the LED datasheet, then choose the "
                    "next standard value and verify its power rating. This review has "
                    "not calculated the value because Vf and If were not supplied."
                ),
                component_reference=led.reference,
                affected_pins=sorted(
                    {
                        pin
                        for net in led_nets
                        for pin in index.net_to_pins.get(net, [])
                        if pin.startswith(led.reference + ".")
                    }
                ),
                confidence=confidence,
                data_provenance=_provenance(led),
            )
        )
    return findings


def check_led_resistor_ratings(design: CircuitDesign) -> list[RedTeamFinding]:
    if design.supply_voltage_v is None:
        return []
    index = build_net_index(design)
    resistor_refs = {
        component.reference for component in design.components if is_resistor(component)
    }
    resistors = {component.reference: component for component in design.components}
    findings: list[RedTeamFinding] = []

    for led in (component for component in design.components if is_led(component)):
        reference = find_series_resistor(index, led.reference, resistor_refs)
        if not reference:
            continue
        resistor = resistors[reference]
        power = led_worst_case_resistor_power(design, resistor)
        current = led_worst_case_current(design, resistor)
        if power is None or current is None:
            continue
        worst = (
            f"Worst-case bound with Vf treated as 0 V: I ≤ {current * 1000:.1f} mA, "
            f"P ≤ {power_label(power)}. Real values are lower."
        )

        if resistor.power_rating_w is not None and power > resistor.power_rating_w:
            findings.append(
                _finding(
                    "PRT-03",
                    category=FindingCategory.COMPONENT_PROTECTION,
                    severity=FindingSeverity.HIGH,
                    description=(
                        f"{resistor.reference} may exceed its declared power rating in the "
                        f"{led.reference} current path."
                    ),
                    engineering_reason=(
                        "The worst-case bound assumes the LED forward drop is zero. Even "
                        "so, a resistor rated below this bound cannot be shown to survive "
                        "a shorted or mis-inserted LED."
                    ),
                    evidence=(
                        f"R={resistance_label(component_resistance(resistor))}, "
                        f"supply={design.supply_voltage_v} V, "
                        f"declared rating={power_label(resistor.power_rating_w)}. {worst}"
                    ),
                    recommended_action=(
                        "Choose a resistor with adequate power rating for the real LED "
                        "current, or increase the resistance. Confirm Vf and If from the "
                        "LED datasheet."
                    ),
                    component_reference=resistor.reference,
                    confidence=0.8,
                    data_provenance=_provenance(resistor),
                )
            )
        elif resistor.power_rating_w is None:
            findings.append(
                _finding(
                    "PRT-04",
                    category=FindingCategory.COMPONENT_PROTECTION,
                    severity=FindingSeverity.INFORMATIONAL,
                    description=(
                        f"{resistor.reference} power rating is not declared; worst-case "
                        f"dissipation is {power_label(power)}."
                    ),
                    engineering_reason=(
                        "A resistor can overheat even when its resistance value is correct. "
                        "The power rating must be checked against the real current."
                    ),
                    evidence=worst,
                    recommended_action=(
                        "Confirm the resistor package power rating at the expected ambient "
                        "temperature and apply the usual derating margin."
                    ),
                    component_reference=resistor.reference,
                    verification_status="INCOMPLETE_DATA",
                    data_provenance=_provenance(resistor),
                )
            )

        if (
            resistor.current_rating_a is not None
            and current > resistor.current_rating_a
        ):
            findings.append(
                _finding(
                    "PRT-05",
                    category=FindingCategory.COMPONENT_PROTECTION,
                    severity=FindingSeverity.HIGH,
                    description=(
                        f"{resistor.reference} worst-case current exceeds its declared "
                        "current rating."
                    ),
                    engineering_reason=(
                        "Exceeding a component's current rating can cause overheating or "
                        "permanent damage. This bound is conservative because Vf is unknown."
                    ),
                    evidence=(
                        f"I ≤ {current:.4f} A vs rating "
                        f"{resistor.current_rating_a:.4f} A. {worst}"
                    ),
                    recommended_action=(
                        "Increase the resistance or select a part with a higher current rating."
                    ),
                    component_reference=resistor.reference,
                    confidence=0.85,
                    data_provenance=_provenance(resistor),
                )
            )
    return findings


def check_resistor_dissipation(design: CircuitDesign) -> list[RedTeamFinding]:
    if design.supply_voltage_v is None:
        return []
    findings: list[RedTeamFinding] = []
    for resistor in (component for component in design.components if is_resistor(component)):
        power = direct_supply_power(design, resistor)
        current = direct_supply_current(design, resistor)
        if power is None or current is None:
            continue
        if resistor.power_rating_w is not None:
            if power > resistor.power_rating_w:
                findings.append(
                    _finding(
                        "PRT-06",
                        category=FindingCategory.COMPONENT_PROTECTION,
                        severity=FindingSeverity.HIGH,
                        description=(
                            f"{resistor.reference} is connected directly across the supply "
                            "and exceeds its declared power rating."
                        ),
                        engineering_reason=(
                            "A resistor connected directly between supply and ground "
                            "dissipates V²/R continuously. Exceeding the rating is a "
                            "component-damage and fire risk."
                        ),
                        evidence=(
                            f"P = {power_label(power)} at {design.supply_voltage_v} V, "
                            f"R = {resistance_label(component_resistance(resistor))}, "
                            f"rating = {power_label(resistor.power_rating_w)}"
                        ),
                        recommended_action=(
                            "Remove the direct supply-to-ground path, increase resistance, "
                            "or select a resistor with a sufficient power rating. Confirm "
                            "whether this connection is intentional."
                        ),
                        component_reference=resistor.reference,
                        confidence=1.0,
                        data_provenance=_provenance(resistor),
                    )
                )
            elif power > 0.8 * resistor.power_rating_w:
                findings.append(
                    _finding(
                        "PRT-07",
                        category=FindingCategory.COMPONENT_PROTECTION,
                        severity=FindingSeverity.MEDIUM,
                        description=(
                            f"{resistor.reference} operates above 80% of its declared "
                            "power rating."
                        ),
                        engineering_reason=(
                            "Operating a resistor close to its rating leaves little margin "
                            "for ambient temperature rise, tolerance and enclosure effects."
                        ),
                        evidence=(
                            f"P = {power_label(power)} vs rating "
                            f"{power_label(resistor.power_rating_w)}"
                        ),
                        recommended_action=(
                            "Apply a documented derating rule (commonly ≤50–80% of rated "
                            "power depending on the environment) or choose a larger package."
                        ),
                        component_reference=resistor.reference,
                        confidence=0.85,
                        data_provenance=_provenance(resistor),
                    )
                )
        else:
            findings.append(
                _finding(
                    "PRT-08",
                    category=FindingCategory.COMPONENT_PROTECTION,
                    severity=FindingSeverity.LOW,
                    description=(
                        f"{resistor.reference} is directly across the supply; its power "
                        "rating is not declared."
                    ),
                    engineering_reason=(
                        "The resistor dissipates power continuously. Without a declared "
                        "rating, the design cannot be shown to be within component limits."
                    ),
                    evidence=(
                        f"P = {power_label(power)} at {design.supply_voltage_v} V. "
                        "power_rating_w is None."
                    ),
                    recommended_action=(
                        "Confirm the intended function of this resistor and its power rating. "
                        "If it is not intentional, remove the direct supply-to-ground path."
                    ),
                    component_reference=resistor.reference,
                    verification_status="INCOMPLETE_DATA",
                    data_provenance=_provenance(resistor),
                )
            )

        if (
            resistor.current_rating_a is not None
            and current > resistor.current_rating_a
        ):
            findings.append(
                _finding(
                    "PRT-09",
                    category=FindingCategory.COMPONENT_PROTECTION,
                    severity=FindingSeverity.HIGH,
                    description=(
                        f"{resistor.reference} current exceeds its declared rating."
                    ),
                    engineering_reason=(
                        "Continuous current above the declared rating can overheat or "
                        "damage the component."
                    ),
                    evidence=(
                        f"I = {current:.4f} A vs rating {resistor.current_rating_a:.4f} A"
                    ),
                    recommended_action=(
                        "Increase resistance or use a component with a higher current rating."
                    ),
                    component_reference=resistor.reference,
                    confidence=1.0,
                    data_provenance=_provenance(resistor),
                )
            )
    return findings


def check_flyback_protection(design: CircuitDesign) -> list[RedTeamFinding]:
    inductive = [
        component for component in design.components if is_inductive_load(component)
    ]
    if not inductive:
        return []
    if any(_non_led_diode(component) for component in design.components):
        return []
    return [
        _finding(
            "PRT-10",
            category=FindingCategory.COMPONENT_PROTECTION,
            severity=FindingSeverity.HIGH,
            description=(
                "An inductive load is declared but no flyback diode is identified: "
                + ", ".join(component.reference for component in inductive)
            ),
            engineering_reason=(
                "Switching an inductive load interrupts current through the inductance, "
                "producing a voltage spike that can destroy the driver. A reverse-biased "
                "flyback diode across the coil is the usual protection. Topology cannot "
                "be confirmed from reference designators alone."
            ),
            evidence=(
                "Inductive components: "
                + ", ".join(f"{c.reference} ({c.name})" for c in inductive)
                + ". No non-LED diode component is declared."
            ),
            recommended_action=(
                "If the load is switched, add a flyback diode rated for the coil current "
                "and reverse voltage, connected across the coil in reverse bias. Verify "
                "the actual topology on the schematic."
            ),
            component_reference=inductive[0].reference,
            confidence=0.6,
            data_provenance=_provenance(inductive[0]),
        )
    ]


def check_reverse_polarity_protection(design: CircuitDesign) -> list[RedTeamFinding]:
    polarized = [
        component for component in design.components if is_polarized_capacitor(component)
    ]
    if not polarized:
        return []
    if any(_non_led_diode(component) for component in design.components):
        return []
    return [
        _finding(
            "PRT-11",
            category=FindingCategory.COMPONENT_PROTECTION,
            severity=FindingSeverity.LOW,
            description=(
                "Polarized capacitors are present and no reverse-polarity protection "
                "component is identified."
            ),
            engineering_reason=(
                "Reverse voltage on an electrolytic or tantalum capacitor can cause "
                "failure, venting or fire. This rule notes the absence of a declared "
                "protective diode; it does not prove the design is unprotected."
            ),
            evidence=(
                "Polarized capacitors: "
                + ", ".join(f"{c.reference} ({c.name})" for c in polarized)
                + ". No non-LED diode is declared."
            ),
            recommended_action=(
                "Verify capacitor orientation and the connector polarity. Add reverse-"
                "polarity protection if the supply can be connected incorrectly."
            ),
            component_reference=polarized[0].reference,
            confidence=0.6,
            data_provenance=_provenance(polarized[0]),
        )
    ]


# ---------------------------------------------------------------------------
# C. Connectivity
# ---------------------------------------------------------------------------


def check_conflicting_pin_nets(design: CircuitDesign) -> list[RedTeamFinding]:
    index = build_net_index(design)
    findings: list[RedTeamFinding] = []
    for pin, nets in sorted(index.conflicting_pins().items()):
        findings.append(
            _finding(
                "CON-01",
                category=FindingCategory.CONNECTIVITY,
                severity=FindingSeverity.HIGH,
                description=(
                    f"Pin {pin} is assigned to multiple nets: {', '.join(sorted(nets))}."
                ),
                engineering_reason=(
                    "One physical pin cannot be on two different nets unless they are "
                    "intended to be the same net. This is a contradictory connection and "
                    "may indicate a netlist error or an accidental short."
                ),
                evidence=f"{pin} appears on nets {sorted(nets)}",
                recommended_action=(
                    "Correct the netlist so the pin belongs to exactly one net, or merge "
                    "the nets if they were intended to be electrically identical."
                ),
                affected_pins=[pin],
                confidence=1.0,
            )
        )
    return findings


def check_isolated_nets(design: CircuitDesign) -> list[RedTeamFinding]:
    findings: list[RedTeamFinding] = []
    index = build_net_index(design)
    for net_name, pins in sorted(index.net_to_pins.items()):
        references = index.net_to_refs.get(net_name, set())
        if len(references) == 1 and len(pins) >= 2:
            findings.append(
                _finding(
                    "CON-02",
                    category=FindingCategory.CONNECTIVITY,
                    severity=FindingSeverity.MEDIUM,
                    description=(
                        f"Net '{net_name}' connects only pins of {next(iter(references))}."
                    ),
                    engineering_reason=(
                        "A net with only one component is usually an incomplete connection, "
                        "an accidental internal short, or a missing destination. It is not "
                        "useful as an external net unless it is a documented test point."
                    ),
                    evidence=f"Pins on '{net_name}': {pins}",
                    recommended_action=(
                        "Confirm whether the pins should be connected together and add the "
                        "missing destination component, or remove the net."
                    ),
                    confidence=0.8,
                )
            )
    return findings


def check_repeated_net_names(design: CircuitDesign) -> list[RedTeamFinding]:
    index = build_net_index(design)
    findings: list[RedTeamFinding] = []
    for net_name, count in sorted(index.repeated_net_names.items()):
        findings.append(
            _finding(
                "CON-03",
                category=FindingCategory.CONNECTIVITY,
                severity=FindingSeverity.LOW,
                description=(
                    f"Net name '{net_name}' is declared in {count} separate connection "
                    "entries."
                ),
                engineering_reason=(
                    "Multiple entries with the same net name are normally treated as one "
                    "global net. If that is not intended, the listeners are accidentally "
                    "shorted together; if it is intended, the design is simply fragmented."
                ),
                evidence=f"'{net_name}' appears in {count} entries",
                recommended_action=(
                    "Merge the entries for clarity or rename them if they are meant to be "
                    "separate nets."
                ),
                confidence=0.6,
            )
        )
    return findings


def check_unconnected_components(design: CircuitDesign) -> list[RedTeamFinding]:
    if not design.connections:
        return []
    index = build_net_index(design)
    findings: list[RedTeamFinding] = []
    for component in design.components:
        if index.nets_for_ref(component.reference):
            continue
        severity = FindingSeverity.HIGH if is_ic_like(component) else FindingSeverity.MEDIUM
        findings.append(
            _finding(
                "CON-04",
                category=FindingCategory.CONNECTIVITY,
                severity=severity,
                description=(
                    f"{component.reference} ({component.name}) is not connected to any net."
                ),
                engineering_reason=(
                    "A declared component with no connection is either unused or the "
                    "schematic interpretation is incomplete. Active parts cannot function "
                    "without supply and signal connections."
                ),
                evidence=(
                    f"{component.reference} has no REF.PIN entry in any connection."
                ),
                recommended_action=(
                    "Connect the component as intended, mark it as intentionally unpopulated, "
                    "or remove it from the design and BOM."
                ),
                component_reference=component.reference,
                confidence=0.95,
                verification_status="DETERMINISTIC",
                data_provenance=_provenance(component),
            )
        )
    return findings


def check_invalid_pin_references(design: CircuitDesign) -> list[RedTeamFinding]:
    """Defensive check for designs constructed without full schema validation."""
    known = {component.reference for component in design.components}
    findings: list[RedTeamFinding] = []
    for connection in design.connections:
        for pin in connection.pins:
            reference = pin.split(".", 1)[0]
            if "." not in pin or reference not in known:
                findings.append(
                    _finding(
                        "CON-05",
                        category=FindingCategory.CONNECTIVITY,
                        severity=FindingSeverity.HIGH,
                        description=(
                            f"Net '{connection.net_name}' references an invalid pin '{pin}'."
                        ),
                        engineering_reason=(
                            "A pin reference must name a declared component. Invalid "
                            "references make the netlist ambiguous and cannot be exported "
                            "as a reliable schematic."
                        ),
                        evidence=(
                            f"Known references: {sorted(known)}; offending pin: {pin!r}"
                        ),
                        recommended_action=(
                            "Correct the pin reference to REF.PIN using a declared component "
                            "reference."
                        ),
                        affected_pins=[pin],
                        confidence=1.0,
                    )
                )
    return findings


def check_supply_net_voltage_mismatch(design: CircuitDesign) -> list[RedTeamFinding]:
    if design.supply_voltage_v is None:
        return []
    index = build_net_index(design)
    regulator_present = any(
        any(
            keyword in component.name.lower()
            for keyword in ("regulator", "ldo", "buck", "boost", "converter")
        )
        for component in design.components
    )
    findings: list[RedTeamFinding] = []
    for net_name in sorted(index.power_nets):
        hint = net_voltage_hint(net_name)
        if hint is None:
            continue
        if abs(hint - design.supply_voltage_v) <= max(0.1, design.supply_voltage_v * 0.05):
            continue
        severity = FindingSeverity.LOW if regulator_present else FindingSeverity.HIGH
        findings.append(
            _finding(
                "PWR-08",
                category=FindingCategory.POWER_INTEGRITY,
                severity=severity,
                description=(
                    f"Net '{net_name}' implies {hint:g} V but the declared supply is "
                    f"{design.supply_voltage_v:g} V."
                ),
                engineering_reason=(
                    "Conflicting voltage labels are a common source of assembly errors and "
                    "component overstress. A regulator may legitimately create a second "
                    "rail, but it must be declared and reviewed."
                ),
                evidence=(
                    f"net_voltage_hint({net_name!r}) = {hint:g} V; "
                    f"supply_voltage_v = {design.supply_voltage_v:g} V; "
                    f"regulator present: {regulator_present}"
                ),
                recommended_action=(
                    "Correct the net name or supply declaration. If a regulator creates this "
                    "rail, document its input, output and current limit."
                ),
                confidence=0.85,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# D. Component compatibility
# ---------------------------------------------------------------------------


def check_component_voltage_ratings(design: CircuitDesign) -> list[RedTeamFinding]:
    if design.supply_voltage_v is None:
        return []
    supply = design.supply_voltage_v
    findings: list[RedTeamFinding] = []
    for component in design.components:
        if component.voltage_rating_v is None:
            continue
        if component.voltage_rating_v < supply:
            findings.append(
                _finding(
                    "CMP-01",
                    category=FindingCategory.COMPONENT_COMPATIBILITY,
                    severity=FindingSeverity.CRITICAL,
                    description=(
                        f"{component.reference} voltage rating "
                        f"({component.voltage_rating_v:g} V) is below the declared supply "
                        f"({supply:g} V)."
                    ),
                    engineering_reason=(
                        "The declared supply exceeds the component's declared voltage "
                        "rating. This is an absolute-maximum violation based on the data "
                        "provided and can cause immediate or latent failure."
                    ),
                    evidence=(
                        f"voltage_rating_v={component.voltage_rating_v:g}, "
                        f"supply_voltage_v={supply:g}, "
                        f"evidence_status={component.evidence_status}"
                    ),
                    recommended_action=(
                        "Select a component rated above the maximum circuit voltage with "
                        "documented derating, or reduce the supply voltage. Confirm the "
                        "rating against the manufacturer datasheet before building."
                    ),
                    component_reference=component.reference,
                    confidence=1.0,
                    data_provenance=_provenance(component),
                )
            )
        elif component.voltage_rating_v < supply * 1.25:
            findings.append(
                _finding(
                    "CMP-02",
                    category=FindingCategory.COMPONENT_COMPATIBILITY,
                    severity=FindingSeverity.HIGH,
                    description=(
                        f"{component.reference} has less than 25% voltage margin above the "
                        f"{supply:g} V supply."
                    ),
                    engineering_reason=(
                        "Operation close to an absolute maximum leaves little room for "
                        "supply tolerance, transients and temperature effects. A common "
                        "design rule is at least 25% margin, but the correct derating is "
                        "defined by the component datasheet and application standard."
                    ),
                    evidence=(
                        f"rating={component.voltage_rating_v:g} V, supply={supply:g} V, "
                        f"ratio={component.voltage_rating_v / supply:.2f}"
                    ),
                    recommended_action=(
                        "Choose a higher-rated part or document why the reduced margin is "
                        "acceptable for the controlled supply and environment."
                    ),
                    component_reference=component.reference,
                    confidence=0.9,
                    data_provenance=_provenance(component),
                )
            )
    return findings


def check_missing_voltage_ratings(design: CircuitDesign) -> list[RedTeamFinding]:
    if design.supply_voltage_v is None:
        return []
    findings: list[RedTeamFinding] = []
    for component in design.components:
        if component.voltage_rating_v is not None:
            continue
        findings.append(
            _finding(
                "CMP-03",
                category=FindingCategory.COMPONENT_COMPATIBILITY,
                severity=FindingSeverity.INFORMATIONAL,
                description=(
                    f"{component.reference} ({component.name}) has no declared voltage "
                    "rating; voltage compatibility is unknown."
                ),
                engineering_reason=(
                    "The supply voltage is known, but the component's maximum rating is "
                    "not. No voltage-compatibility conclusion can be drawn from the "
                    "available data."
                ),
                evidence="component.voltage_rating_v is None",
                recommended_action=(
                    "Obtain the datasheet and confirm the maximum voltage rating exceeds "
                    "the worst-case circuit voltage with documented derating."
                ),
                component_reference=component.reference,
                verification_status="INCOMPLETE_DATA",
                data_provenance=_provenance(component),
            )
        )
    return findings


def check_missing_component_values(design: CircuitDesign) -> list[RedTeamFinding]:
    findings: list[RedTeamFinding] = []
    for component in design.components:
        if not (is_resistor(component) or is_capacitor(component)):
            continue
        if component.value is None or not component.value.strip():
            findings.append(
                _finding(
                    "CMP-04",
                    category=FindingCategory.REQUIREMENT_CONSISTENCY,
                    severity=FindingSeverity.MEDIUM,
                    description=(
                        f"{component.reference} ({component.name}) has no declared value."
                    ),
                    engineering_reason=(
                        "A passive component without a value cannot be checked for timing, "
                        "current limiting, power dissipation or filter behavior. Any "
                        "associated calculation is unsupported."
                    ),
                    evidence="component.value is None or empty",
                    recommended_action=(
                        "Specify the intended value and tolerance, and show the calculation "
                        "or datasheet basis for it."
                    ),
                    component_reference=component.reference,
                    verification_status="INCOMPLETE_DATA",
                    data_provenance=_provenance(component),
                )
            )
            continue

        if is_resistor(component) and parse_resistance(component.value) is None:
            findings.append(
                _finding(
                    "CMP-05",
                    category=FindingCategory.REQUIREMENT_CONSISTENCY,
                    severity=FindingSeverity.LOW,
                    description=(
                        f"{component.reference} value {component.value!r} is not a "
                        "machine-readable resistance."
                    ),
                    engineering_reason=(
                        "Deterministic current, power and timing calculations were skipped "
                        "because the declared value could not be interpreted."
                    ),
                    evidence=f"parse_resistance({component.value!r}) returned None",
                    recommended_action=(
                        "Use a standard value such as '220 Ohm', '4k7' or '1 MOhm' so the "
                        "review can calculate the relevant limits."
                    ),
                    component_reference=component.reference,
                    verification_status="INCOMPLETE_DATA",
                    data_provenance=_provenance(component),
                )
            )
        if is_capacitor(component) and parse_capacitance(component.value) is None:
            findings.append(
                _finding(
                    "CMP-06",
                    category=FindingCategory.REQUIREMENT_CONSISTENCY,
                    severity=FindingSeverity.LOW,
                    description=(
                        f"{component.reference} value {component.value!r} is not a "
                        "machine-readable capacitance."
                    ),
                    engineering_reason=(
                        "Timing and filtering calculations were skipped because the declared "
                        "capacitance could not be interpreted."
                    ),
                    evidence=f"parse_capacitance({component.value!r}) returned None",
                    recommended_action=(
                        "Use a standard value such as '100 nF' or '10 uF' and state the "
                        "dielectric and voltage rating where relevant."
                    ),
                    component_reference=component.reference,
                    verification_status="INCOMPLETE_DATA",
                    data_provenance=_provenance(component),
                )
            )
    return findings


def check_pinout_uncertainty(design: CircuitDesign) -> list[RedTeamFinding]:
    index = build_net_index(design)
    findings: list[RedTeamFinding] = []
    for component in design.components:
        if not is_ic_like(component):
            continue
        if not index.nets_for_ref(component.reference):
            continue
        missing: list[str] = []
        if component.evidence_status != "verified":
            missing.append("component data is not verified")
        if not component.manufacturer_part_number:
            missing.append("no manufacturer part number")
        if not component.footprint:
            missing.append("no footprint/package")
        if not missing:
            continue
        findings.append(
            _finding(
                "CMP-07",
                category=FindingCategory.COMPONENT_COMPATIBILITY,
                severity=FindingSeverity.MEDIUM,
                description=(
                    f"{component.reference} ({component.name}) pinout/package is "
                    "uncertain: " + "; ".join(missing) + "."
                ),
                engineering_reason=(
                    "The review cannot confirm that the declared pin numbers and package "
                    "match a real part. Pin numbering differs between packages and "
                    "manufacturers, so connectivity conclusions may be wrong."
                ),
                evidence=(
                    f"evidence_status={component.evidence_status}, "
                    f"manufacturer_part_number={component.manufacturer_part_number!r}, "
                    f"footprint={component.footprint!r}"
                ),
                recommended_action=(
                    "Confirm the exact manufacturer part number, package and pin map from "
                    "the datasheet, then re-check every connection that uses this part."
                ),
                component_reference=component.reference,
                verification_status="INCOMPLETE_DATA",
                data_provenance=_provenance(component),
            )
        )
    return findings


def check_unverified_components(design: CircuitDesign) -> list[RedTeamFinding]:
    unverified = [
        component
        for component in design.components
        if component.evidence_status == "unverified"
    ]
    if not unverified:
        return []
    references = ", ".join(component.reference for component in unverified[:12])
    suffix = " ..." if len(unverified) > 12 else ""
    return [
        _finding(
            "CMP-08",
            category=FindingCategory.COMPONENT_COMPATIBILITY,
            severity=FindingSeverity.LOW,
            description=(
                f"{len(unverified)} component(s) are marked unverified: {references}{suffix}"
            ),
            engineering_reason=(
                "Unverified parts have not been checked against a manufacturer datasheet. "
                "Values, ratings, pinouts and packages may differ from the AI inference."
            ),
            evidence=f"evidence_status='unverified' for {len(unverified)} component(s)",
            recommended_action=(
                "Verify each part number, datasheet revision, rating, pin map and footprint "
                "before simulation, layout or assembly."
            ),
            confidence=1.0,
        )
    ]


# ---------------------------------------------------------------------------
# E. Requirement consistency
# ---------------------------------------------------------------------------


def _requirement_text(design: CircuitDesign) -> str:
    parts = [
        design.project_name,
        design.project_description,
        *design.design_notes,
        *design.assumptions,
    ]
    return " ".join(part for part in parts if part)


def _has_component(design: CircuitDesign, predicate) -> bool:
    return any(predicate(component) for component in design.components)


def check_requirement_component_consistency(
    design: CircuitDesign,
) -> list[RedTeamFinding]:
    text = _requirement_text(design).lower()
    checks: list[tuple[str, str, Callable[[Component], bool]]] = [
        (
            "LED",
            r"\bled\b|light[- ]emitting diode",
            is_led,
        ),
        (
            "555 timer",
            r"\b555\b",
            lambda component: "555" in component.name.lower(),
        ),
        (
            "timer IC",
            r"\btimer\b",
            lambda component: "timer" in component.name.lower()
            or "555" in component.name.lower(),
        ),
        (
            "microcontroller",
            r"\bmicrocontroller\b|\bmcu\b",
            lambda component: "microcontroller" in component.name.lower()
            or "mcu" in component.name.lower()
            or "micro-controller" in component.name.lower(),
        ),
        (
            "operational amplifier",
            r"\bop[- ]?amp\b|operational amplifier",
            lambda component: "op-amp" in component.name.lower()
            or "opamp" in component.name.lower()
            or "operational amplifier" in component.name.lower(),
        ),
        (
            "voltage regulator",
            r"\bregulator\b|\bldo\b|buck converter|boost converter",
            lambda component: any(
                word in component.name.lower()
                for word in ("regulator", "ldo", "buck", "boost")
            ),
        ),
        (
            "inductive load",
            r"\bmotor\b|\brelay\b|\bsolenoid\b",
            is_inductive_load,
        ),
        (
            "crystal/oscillator",
            r"\bcrystal\b|\boscillator\b",
            lambda component: "crystal" in component.name.lower()
            or "oscillator" in component.name.lower()
            or "resonator" in component.name.lower(),
        ),
    ]

    findings: list[RedTeamFinding] = []
    for label, pattern, predicate in checks:
        if not re.search(pattern, text):
            continue
        if _has_component(design, predicate):
            continue
        findings.append(
            _finding(
                "REQ-01",
                category=FindingCategory.REQUIREMENT_CONSISTENCY,
                severity=FindingSeverity.HIGH,
                description=(
                    f"The requirements mention a {label}, but no matching component is "
                    "declared."
                ),
                engineering_reason=(
                    "The proposed component list does not contain the part needed to "
                    "implement the requested behavior. The design cannot be assumed to "
                    "meet the requirement."
                ),
                evidence=(
                    f"Requirement text matches /{pattern}/; declared components: "
                    + ", ".join(
                        f"{c.reference} ({c.name})" for c in design.components[:15]
                    )
                    + ("" if len(design.components) <= 15 else " ...")
                ),
                recommended_action=(
                    f"Add the required {label} with a verified part number, or correct the "
                    "requirement if this function is not intended."
                ),
                confidence=0.8,
                verification_status="DETERMINISTIC",
                data_provenance="not_applicable",
            )
        )
    return findings


def check_target_frequency_support(design: CircuitDesign) -> list[RedTeamFinding]:
    target = design.target_frequency_hz
    if target is None:
        return []
    has_capacitor = _has_component(design, is_capacitor)
    has_resistor = _has_component(design, is_resistor)
    has_oscillator = _has_component(
        design,
        lambda component: any(
            word in component.name.lower()
            for word in ("oscillator", "timer", "555", "crystal", "resonator", "mcu", "microcontroller")
        ),
    )

    if not has_capacitor and not has_oscillator:
        return [
            _finding(
                "REQ-02",
                category=FindingCategory.REQUIREMENT_CONSISTENCY,
                severity=FindingSeverity.MEDIUM,
                description=(
                    f"A target frequency of {target:g} Hz is declared, but no timing "
                    "element or oscillator is identified."
                ),
                engineering_reason=(
                    "Frequency generation requires an oscillator, resonator, timer or "
                    "explicit RC/LC timing network. None is present in the component list."
                ),
                evidence=(
                    f"target_frequency_hz={target:g}; capacitors={has_capacitor}; "
                    f"resistors={has_resistor}; oscillator/timer={has_oscillator}"
                ),
                recommended_action=(
                    "Add the intended oscillator/timer and timing components, or remove the "
                    "frequency requirement if it is not applicable."
                ),
                verification_status="INCOMPLETE_DATA",
            )
        ]

    if not has_oscillator and not (has_capacitor and has_resistor):
        return [
            _finding(
                "REQ-03",
                category=FindingCategory.REQUIREMENT_CONSISTENCY,
                severity=FindingSeverity.MEDIUM,
                description=(
                    f"The {target:g} Hz target has no identifiable frequency-determining "
                    "network."
                ),
                engineering_reason=(
                    "A capacitor or resistor is present, but not the combination needed for "
                    "an identifiable RC timing network, and no oscillator/timer is declared."
                ),
                evidence=(
                    f"capacitors={has_capacitor}, resistors={has_resistor}, "
                    f"oscillator/timer={has_oscillator}"
                ),
                recommended_action=(
                    "Declare the complete oscillator topology and the components that set "
                    "the frequency, with the design equation."
                ),
                verification_status="INCOMPLETE_DATA",
            )
        ]

    return [
        _finding(
            "REQ-04",
            category=FindingCategory.REQUIREMENT_CONSISTENCY,
            severity=FindingSeverity.INFORMATIONAL,
            description=(
                f"Timing components are present for the {target:g} Hz target, but the "
                "frequency was not calculated or simulated."
            ),
            engineering_reason=(
                "The review does not know the exact oscillator topology, component "
                "tolerances or datasheet parameters. Reporting a calculated frequency "
                "without those inputs would be an unsupported claim."
            ),
            evidence=(
                f"target_frequency_hz={target:g}; timing components declared. No "
                "simulation was performed."
            ),
            recommended_action=(
                "Calculate the frequency from the confirmed topology and datasheet values, "
                "then verify it on the bench with an oscilloscope or frequency counter."
            ),
            verification_status="INCOMPLETE_DATA",
            requires_measurement=True,
        )
    ]


def check_missing_information(design: CircuitDesign) -> list[RedTeamFinding]:
    findings: list[RedTeamFinding] = []
    for index, item in enumerate(design.missing_information):
        findings.append(
            _finding(
                "REQ-05",
                category=FindingCategory.REQUIREMENT_CONSISTENCY,
                severity=FindingSeverity.MEDIUM,
                description=f"Missing design information: {item}",
                engineering_reason=(
                    "The design is explicitly incomplete. Any conclusion that depends on "
                    "this information is uncertain, and checks that require it were skipped."
                ),
                evidence=f"design.missing_information[{index}]: {item!r}",
                recommended_action=(
                    "Provide the missing information and re-run the review. Do not build "
                    "the circuit while a required design input is unknown."
                ),
                verification_status="INCOMPLETE_DATA",
                identity_parts=(index,),
            )
        )
    return findings


def check_declared_dividers(design: CircuitDesign) -> list[RedTeamFinding]:
    """Validate declared resistor dividers without claiming to simulate a load."""
    findings: list[RedTeamFinding] = []
    for divider in find_voltage_dividers(design):
        findings.append(
            _finding(
                "REQ-06",
                category=FindingCategory.REQUIREMENT_CONSISTENCY,
                severity=FindingSeverity.INFORMATIONAL,
                description=(
                    f"Unloaded divider {divider.top_reference}/{divider.bottom_reference} "
                    f"on net '{divider.output_net}' produces approximately "
                    f"{divider.output_voltage_v:.3f} V."
                ),
                engineering_reason=(
                    "The calculation is valid only for an unloaded divider using the "
                    "declared resistance values. Any load changes the output, and resistor "
                    "tolerance and supply tolerance are not included."
                ),
                evidence=(
                    f"Vout = Vs × Rbottom / (Rtop + Rbottom) = "
                    f"{design.supply_voltage_v:g} × {divider.bottom_ohms:g} / "
                    f"({divider.top_ohms:g} + {divider.bottom_ohms:g}); "
                    f"quiescent current ≈ {divider.quiescent_current_a * 1000:.3f} mA"
                ),
                recommended_action=(
                    "Confirm the load, resistor tolerances and supply tolerance. Measure the "
                    "real output before connecting a sensitive load."
                ),
                component_reference=divider.top_reference,
                affected_pins=[],
                confidence=0.8,
                verification_status="DETERMINISTIC",
                data_provenance="unverified",
                requires_measurement=True,
                identity_parts=(divider.bottom_reference, divider.output_net),
            )
        )
    return findings


def check_passive_value_plausibility(design: CircuitDesign) -> list[RedTeamFinding]:
    """Flag values that are syntactically valid but implausible for a declared supply."""
    findings: list[RedTeamFinding] = []
    for component in design.components:
        if not is_resistor(component):
            continue
        resistance = component_resistance(component)
        if resistance is None:
            continue
        if resistance <= 0:
            findings.append(
                _finding(
                    "REQ-07",
                    category=FindingCategory.REQUIREMENT_CONSISTENCY,
                    severity=FindingSeverity.HIGH,
                    description=f"{component.reference} has a non-positive resistance.",
                    engineering_reason=(
                        "Zero or negative resistance is not physically meaningful for a "
                        "normal resistor and would create an invalid current path."
                    ),
                    evidence=f"parsed resistance={resistance}",
                    recommended_action="Correct the declared value.",
                    component_reference=component.reference,
                    verification_status="DETERMINISTIC",
                    data_provenance=_provenance(component),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

Rule = tuple[str, str, Callable[[CircuitDesign], list[RedTeamFinding]]]

ALL_RULES: list[Rule] = [
    ("PWR-01", "Supply voltage declared", check_supply_voltage_declared),
    ("PWR-02", "Ground net present", check_no_ground_net),
    ("PWR-03", "Supply net present", check_no_power_net),
    ("PWR-04", "IC ground connectivity", check_ic_supply_and_ground),
    ("PWR-06", "Components present", check_no_components),
    ("PWR-07", "Connections present", check_no_connections),
    ("PWR-08", "Net-name voltage consistency", check_supply_net_voltage_mismatch),
    ("PRT-02", "LED current-limiting resistor", check_led_current_limiting),
    ("PRT-03", "LED series resistor ratings", check_led_resistor_ratings),
    ("PRT-06", "Resistor power dissipation", check_resistor_dissipation),
    ("PRT-10", "Inductive-load flyback protection", check_flyback_protection),
    ("PRT-11", "Reverse-polarity protection note", check_reverse_polarity_protection),
    ("CON-01", "Conflicting pin-to-net assignments", check_conflicting_pin_nets),
    ("CON-02", "Single-component nets", check_isolated_nets),
    ("CON-03", "Repeated net names", check_repeated_net_names),
    ("CON-04", "Unconnected components", check_unconnected_components),
    ("CON-05", "Invalid pin references", check_invalid_pin_references),
    ("CMP-01", "Component voltage ratings", check_component_voltage_ratings),
    ("CMP-03", "Missing voltage ratings", check_missing_voltage_ratings),
    ("CMP-04", "Missing passive values", check_missing_component_values),
    ("CMP-07", "Pinout and package uncertainty", check_pinout_uncertainty),
    ("CMP-08", "Unverified component data", check_unverified_components),
    ("REQ-01", "Requirement/component consistency", check_requirement_component_consistency),
    ("REQ-02", "Target-frequency support", check_target_frequency_support),
    ("REQ-05", "Missing design information", check_missing_information),
    ("REQ-06", "Declared voltage dividers", check_declared_dividers),
    ("REQ-07", "Passive value plausibility", check_passive_value_plausibility),
]


def run_all_deterministic_rules(
    design: CircuitDesign,
) -> tuple[list[RedTeamFinding], list[str]]:
    """Run every deterministic rule and return findings plus check names.

    A rule failure is logged and surfaced in the check list; it never crashes
    the entire review and it never produces a false PASS.
    """
    findings: list[RedTeamFinding] = []
    checks_run: list[str] = []
    seen: set[str] = set()
    for code, name, function in ALL_RULES:
        checks_run.append(f"{code} {name}")
        try:
            produced = function(design)
        except Exception as exc:  # Defensive: a rule bug must not hide others.
            logger.exception("Red-Team rule %s failed", code)
            checks_run[-1] = f"{code} {name} — FAILED: {exc}"
            continue
        for finding in produced:
            if finding.finding_id in seen:
                continue
            seen.add(finding.finding_id)
            findings.append(finding)
    return findings, checks_run
