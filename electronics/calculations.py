"""Deterministic electrical calculations used by review and lab guidance.

Every function here is pure: it operates on declared design data and returns
either a calculated value or ``None``. It never fills a missing datasheet
parameter with a guessed number.
"""

from __future__ import annotations

from dataclasses import dataclass

from electronics.netinfo import (
    NetIndex,
    build_net_index,
    is_ground_net,
    is_power_net,
    is_resistor,
)
from electronics.values import parse_capacitance, parse_resistance
from schemas.circuit import CircuitDesign, Component


@dataclass(frozen=True)
class DividerResult:
    top_reference: str
    bottom_reference: str
    output_net: str
    supply_net: str
    ground_net: str
    top_ohms: float
    bottom_ohms: float
    output_voltage_v: float
    quiescent_current_a: float


def component_resistance(component: Component) -> float | None:
    return parse_resistance(component.value)


def component_capacitance(component: Component) -> float | None:
    return parse_capacitance(component.value)


def direct_supply_power(design: CircuitDesign, component: Component) -> float | None:
    """Power in a resistor connected directly between a supply and ground net."""
    if design.supply_voltage_v is None:
        return None
    resistance = component_resistance(component)
    if not resistance or resistance <= 0:
        return None
    index = build_net_index(design)
    nets = index.nets_for_ref(component.reference)
    has_power = any(is_power_net(net) and not is_ground_net(net) for net in nets)
    has_ground = any(is_ground_net(net) for net in nets)
    if not (has_power and has_ground):
        return None
    return (design.supply_voltage_v**2) / resistance


def direct_supply_current(design: CircuitDesign, component: Component) -> float | None:
    if design.supply_voltage_v is None:
        return None
    resistance = component_resistance(component)
    if not resistance or resistance <= 0:
        return None
    index = build_net_index(design)
    nets = index.nets_for_ref(component.reference)
    has_power = any(is_power_net(net) and not is_ground_net(net) for net in nets)
    has_ground = any(is_ground_net(net) for net in nets)
    if not (has_power and has_ground):
        return None
    return design.supply_voltage_v / resistance


def find_voltage_dividers(design: CircuitDesign) -> list[DividerResult]:
    """Find two-resistor dividers between a declared supply net and ground.

    The calculation is only performed when the net structure is unambiguous:
    one resistor connects supply to a common net, another connects that same
    common net to ground. No assumption is made about the load on the centre
    net; the reported value is the unloaded divider output.
    """
    if design.supply_voltage_v is None or design.supply_voltage_v <= 0:
        return []
    index: NetIndex = build_net_index(design)
    resistors = {
        component.reference: component
        for component in design.components
        if is_resistor(component) and component_resistance(component)
    }
    supply_nets = index.power_nets
    ground_nets = index.ground_nets
    if not supply_nets or not ground_nets:
        return []

    results: list[DividerResult] = []
    seen: set[tuple[str, str]] = set()

    for top_ref, top in resistors.items():
        top_nets = index.nets_for_ref(top_ref)
        top_supply = top_nets & supply_nets
        middle_nets = {
            net
            for net in top_nets - supply_nets
            if not is_ground_net(net)
        }
        for middle in sorted(middle_nets):
            for bottom_ref, bottom in resistors.items():
                if bottom_ref == top_ref:
                    continue
                bottom_nets = index.nets_for_ref(bottom_ref)
                if middle not in bottom_nets:
                    continue
                bottom_ground = bottom_nets & ground_nets
                if len(top_supply) != 1 or len(bottom_ground) != 1:
                    continue
                key = tuple(sorted((top_ref, bottom_ref)))
                if key in seen:
                    continue
                top_ohms = component_resistance(top)
                bottom_ohms = component_resistance(bottom)
                if not top_ohms or not bottom_ohms:
                    continue
                total = top_ohms + bottom_ohms
                results.append(
                    DividerResult(
                        top_reference=top_ref,
                        bottom_reference=bottom_ref,
                        output_net=middle,
                        supply_net=next(iter(top_supply)),
                        ground_net=next(iter(bottom_ground)),
                        top_ohms=top_ohms,
                        bottom_ohms=bottom_ohms,
                        output_voltage_v=design.supply_voltage_v * bottom_ohms / total,
                        quiescent_current_a=design.supply_voltage_v / total,
                    )
                )
                seen.add(key)
    return results


def led_worst_case_current(design: CircuitDesign, resistor: Component) -> float | None:
    """Upper-bound current if the LED forward drop were zero.

    The real current is lower. This is an explicitly labelled worst case, not
    a prediction, and is used only for rating checks.
    """
    resistance = component_resistance(resistor)
    if design.supply_voltage_v is None or not resistance or resistance <= 0:
        return None
    return design.supply_voltage_v / resistance


def led_worst_case_resistor_power(
    design: CircuitDesign,
    resistor: Component,
) -> float | None:
    resistance = component_resistance(resistor)
    if design.supply_voltage_v is None or not resistance or resistance <= 0:
        return None
    return (design.supply_voltage_v**2) / resistance
