"""Deterministic net and component classification helpers.

The structured CircuitDesign only declares reference designators, pins and net
names. These helpers infer the *structural role* of a net from its name and
the *type* of a component from its declared name. They do not infer electrical
values and they never consult a datasheet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from schemas.circuit import CircuitDesign, Component

_GROUND_TOKENS = {
    "gnd",
    "ground",
    "vss",
    "0v",
    "agnd",
    "dgnd",
    "earth",
    "chassis",
}
_POWER_TOKENS = {
    "vcc",
    "vdd",
    "vddio",
    "vbat",
    "vbus",
    "vin",
    "vsup",
    "vsupply",
    "pwr",
    "power",
    "v+",
    "vpos",
    "5v",
    "3v3",
    "12v",
    "9v",
    "3v",
}
_VOLTAGE_HINT = re.compile(r"(?<![A-Za-z0-9])\+?(\d+)[vV](\d+)?(?![A-Za-z0-9])")

_IC_KEYWORDS = (
    " ic",
    "ic ",
    "timer",
    "regulator",
    "op-amp",
    "opamp",
    "operational amplifier",
    "microcontroller",
    "micro-controller",
    "mcu",
    "mpu",
    "cpu",
    "logic",
    "gate",
    "driver",
    "adc",
    "dac",
    "555",
    "comparator",
    "oscillator",
    "ne555",
    "lm358",
    "lm741",
    "78l",
    "78m",
    "79l",
)
_LED_KEYWORDS = ("led", "light emitting", "light-emitting")
_RESISTOR_KEYWORDS = ("resistor", "resistance")
_CAPACITOR_KEYWORDS = ("capacitor", "capacitance", "electrolytic", "ceramic cap", "film cap")
_DIODE_KEYWORDS = ("diode", "rectifier", "schottky", "zener", "tvs")
_INDUCTIVE_KEYWORDS = ("motor", "relay", "solenoid", "inductor", "coil", "buzzer", "speaker")
_POLARIZED_CAP_KEYWORDS = ("electrolytic", "tantalum", "polarized")


def _tokens(name: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9+]+", name.lower()) if token}


def is_ground_net(name: str) -> bool:
    lowered = name.strip().lower()
    tokens = _tokens(lowered)
    if tokens & _GROUND_TOKENS:
        return True
    return lowered.startswith(("gnd", "vss")) or lowered.endswith(("_gnd", "-gnd"))


def is_power_net(name: str) -> bool:
    lowered = name.strip().lower()
    tokens = _tokens(lowered)
    if tokens & _POWER_TOKENS:
        return True
    if re.fullmatch(r"\+?\d+v\d*", lowered):
        return True
    return any(
        marker in lowered
        for marker in ("vcc", "vdd", "vbus", "vbat", "vin", "vsup")
    )


def net_voltage_hint(name: str) -> float | None:
    """Extract a voltage from a net name such as ``+3V3`` or ``VCC_5V``."""
    match = _VOLTAGE_HINT.search(name.upper())
    if not match:
        match = re.search(r"(\d+)[Vv](\d+)", name)
    if not match:
        return None
    whole, fraction = match.groups()
    return float(whole + ("." + fraction if fraction else ""))


def _contains(name: str, keywords: tuple[str, ...]) -> bool:
    lowered = name.lower()
    padded = f" {lowered} "
    return any(keyword in padded for keyword in keywords)


def is_ic_like(component: Component) -> bool:
    if component.reference.startswith(("U", "Q", "IC")):
        return True
    return _contains(component.name, _IC_KEYWORDS)


def is_led(component: Component) -> bool:
    return _contains(component.name, _LED_KEYWORDS) or _contains(
        component.description or "", _LED_KEYWORDS
    )


def is_resistor(component: Component) -> bool:
    return _contains(component.name, _RESISTOR_KEYWORDS) or component.reference.startswith("R")


def is_capacitor(component: Component) -> bool:
    return _contains(component.name, _CAPACITOR_KEYWORDS) or component.reference.startswith("C")


def is_diode(component: Component) -> bool:
    return _contains(component.name, _DIODE_KEYWORDS) or component.reference.startswith("D")


def is_inductive_load(component: Component) -> bool:
    return _contains(component.name, _INDUCTIVE_KEYWORDS)


def is_polarized_capacitor(component: Component) -> bool:
    return is_capacitor(component) and _contains(
        component.name + " " + (component.description or ""),
        _POLARIZED_CAP_KEYWORDS,
    )


def is_passive(component: Component) -> bool:
    return (
        is_resistor(component)
        or is_capacitor(component)
        or is_led(component)
        or is_diode(component)
    )


@dataclass
class NetIndex:
    """Lookup tables for pins, components and nets declared by a design."""

    pin_to_nets: dict[str, set[str]] = field(default_factory=dict)
    ref_to_pins: dict[str, set[str]] = field(default_factory=dict)
    ref_to_nets: dict[str, set[str]] = field(default_factory=dict)
    net_to_pins: dict[str, list[str]] = field(default_factory=dict)
    net_to_refs: dict[str, set[str]] = field(default_factory=dict)
    repeated_net_names: dict[str, int] = field(default_factory=dict)

    @property
    def ground_nets(self) -> set[str]:
        return {name for name in self.net_to_pins if is_ground_net(name)}

    @property
    def power_nets(self) -> set[str]:
        return {
            name
            for name in self.net_to_pins
            if is_power_net(name) and not is_ground_net(name)
        }

    def pins_on_net(self, net_name: str) -> list[str]:
        return list(self.net_to_pins.get(net_name, []))

    def refs_on_net(self, net_name: str) -> set[str]:
        return set(self.net_to_refs.get(net_name, set()))

    def nets_for_ref(self, reference: str) -> set[str]:
        return set(self.ref_to_nets.get(reference, set()))

    def nets_for_pin(self, pin: str) -> set[str]:
        return set(self.pin_to_nets.get(pin, set()))

    def refs_on_same_net(self, reference: str) -> set[str]:
        result: set[str] = set()
        for net in self.nets_for_ref(reference):
            result |= self.refs_on_net(net)
        result.discard(reference)
        return result

    def conflicting_pins(self) -> dict[str, set[str]]:
        return {
            pin: nets
            for pin, nets in self.pin_to_nets.items()
            if len(nets) > 1
        }


def build_net_index(design: CircuitDesign) -> NetIndex:
    index = NetIndex()
    counts: dict[str, int] = {}
    for component in design.components:
        index.ref_to_pins.setdefault(component.reference, set())
        index.ref_to_nets.setdefault(component.reference, set())

    for connection in design.connections:
        net = connection.net_name
        counts[net] = counts.get(net, 0) + 1
        index.net_to_pins.setdefault(net, [])
        index.net_to_refs.setdefault(net, set())
        for pin in connection.pins:
            reference = pin.split(".", 1)[0]
            index.pin_to_nets.setdefault(pin, set()).add(net)
            index.ref_to_pins.setdefault(reference, set()).add(pin)
            index.ref_to_nets.setdefault(reference, set()).add(net)
            index.net_to_pins[net].append(pin)
            index.net_to_refs[net].add(reference)

    index.repeated_net_names = {
        name: count for name, count in counts.items() if count > 1
    }
    return index


def find_series_resistor(
    index: NetIndex,
    led_reference: str,
    resistor_references: set[str],
) -> str | None:
    """Return a resistor that is *in series* with the LED, if one is declared.

    Series means the two components share exactly one net and the resistor has
    a second net that the LED is not on. A resistor merely sharing a net with
    the LED (for example both connected across the supply) is not accepted.
    """
    led_nets = index.nets_for_ref(led_reference)
    if len(led_nets) < 2:
        return None
    for resistor in sorted(resistor_references):
        resistor_nets = index.nets_for_ref(resistor)
        if len(resistor_nets) < 2:
            continue
        shared = led_nets & resistor_nets
        if len(shared) == 1 and (resistor_nets - led_nets):
            return resistor
    return None
