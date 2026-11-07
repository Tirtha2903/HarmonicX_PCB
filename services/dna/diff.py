"""Circuit DNA change detection.

Compares two ``CircuitDesign`` snapshots and produces a structured,
human-readable :class:`ChangeReport`. The diff is deterministic and never calls
an LLM. It also compares the Red-Team reports captured with each version so
that new and resolved findings are visible without losing the previous review.
"""

from __future__ import annotations

from typing import Any

from electronics.red_team.models import RedTeamFinding, RedTeamReport
from schemas.circuit import CircuitDesign
from schemas.fingerprint import design_fingerprint
from services.dna.models import ChangeRecord, ChangeReport

_COMPONENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "name"),
    ("value", "value"),
    ("quantity", "quantity"),
    ("description", "description"),
    ("footprint", "footprint"),
    ("voltage_rating_v", "voltage rating"),
    ("current_rating_a", "current rating"),
    ("power_rating_w", "power rating"),
    ("forward_voltage_v", "forward voltage"),
    ("manufacturer_part_number", "manufacturer part number"),
    ("datasheet_url", "datasheet URL"),
    ("evidence_status", "evidence status"),
)


def _component_map(design: CircuitDesign) -> dict[str, dict[str, Any]]:
    return {
        component.reference: component.model_dump(mode="json")
        for component in design.components
    }


def _net_map(design: CircuitDesign) -> dict[str, set[str]]:
    """Merge connections that share a net name into one global net."""
    nets: dict[str, set[str]] = {}
    for connection in design.connections:
        nets.setdefault(connection.net_name, set()).update(connection.pins)
    return nets


def _format_value(value: Any) -> str:
    if value is None or value == "":
        return "none"
    return repr(value)


def _finding_signatures(report: Any) -> set[str]:
    """Return stable finding signatures from a report or a stored snapshot."""
    if report is None:
        return set()
    if isinstance(report, RedTeamReport):
        return {finding.signature() for finding in report.findings}
    if isinstance(report, dict):
        findings = report.get("findings", [])
        signatures: set[str] = set()
        for item in findings:
            if isinstance(item, dict):
                try:
                    signatures.add(RedTeamFinding.model_validate(item).signature())
                except Exception:
                    # Fall back to a stable description-based key.
                    signatures.add(str(item.get("description", "")).strip().lower())
            elif isinstance(item, RedTeamFinding):
                signatures.add(item.signature())
        return signatures
    return set()


def _finding_index(report: Any) -> dict[str, dict[str, Any]]:
    if report is None:
        return {}
    if isinstance(report, RedTeamReport):
        return {
            finding.signature(): finding.model_dump(mode="json")
            for finding in report.findings
        }
    if isinstance(report, dict):
        index: dict[str, dict[str, Any]] = {}
        for item in report.get("findings", []):
            if isinstance(item, dict):
                try:
                    finding = RedTeamFinding.model_validate(item)
                    index[finding.signature()] = finding.model_dump(mode="json")
                except Exception:
                    key = str(item.get("description", "")).strip().lower()
                    index[key] = item
        return index
    return {}


def _add_component_changes(
    old: CircuitDesign,
    new: CircuitDesign,
    changes: list[ChangeRecord],
    checks_invalidated: list[str],
) -> None:
    old_components = _component_map(old)
    new_components = _component_map(new)

    for reference in sorted(set(new_components) - set(old_components)):
        component = new_components[reference]
        changes.append(
            ChangeRecord(
                change_type="component_added",
                category="components",
                description=(
                    f"Component {reference} ({component.get('name', 'unknown')}) added"
                    + (
                        f" with value {component['value']}."
                        if component.get("value")
                        else "."
                    )
                ),
                new_value=str(component),
            )
        )
        checks_invalidated.append(
            f"Re-run voltage, current and protection checks for {reference}"
        )

    for reference in sorted(set(old_components) - set(new_components)):
        component = old_components[reference]
        changes.append(
            ChangeRecord(
                change_type="component_removed",
                category="components",
                description=(
                    f"Component {reference} ({component.get('name', 'unknown')}) removed."
                ),
                old_value=str(component),
            )
        )
        checks_invalidated.append(
            f"Re-run connectivity, BOM and net checks for nets that referenced {reference}"
        )

    for reference in sorted(set(old_components) & set(new_components)):
        old_component = old_components[reference]
        new_component = new_components[reference]
        for field, label in _COMPONENT_FIELDS:
            old_value = old_component.get(field)
            new_value = new_component.get(field)
            if old_value == new_value:
                continue
            changes.append(
                ChangeRecord(
                    change_type="component_changed",
                    category="components",
                    description=(
                        f"{reference} {label} changed from {_format_value(old_value)} "
                        f"to {_format_value(new_value)}."
                    ),
                    old_value=None if old_value is None else str(old_value),
                    new_value=None if new_value is None else str(new_value),
                )
            )
            if field in {"value", "forward_voltage_v"}:
                checks_invalidated.append(
                    f"Re-run value-dependent calculations and protection checks for {reference}"
                )
            if field in {"voltage_rating_v", "current_rating_a", "power_rating_w"}:
                checks_invalidated.append(f"Re-run rating checks for {reference}")


def _add_connection_changes(
    old: CircuitDesign,
    new: CircuitDesign,
    changes: list[ChangeRecord],
    checks_invalidated: list[str],
) -> None:
    old_nets = _net_map(old)
    new_nets = _net_map(new)

    for net_name in sorted(set(new_nets) - set(old_nets)):
        pins = sorted(new_nets[net_name])
        changes.append(
            ChangeRecord(
                change_type="connection_added",
                category="connections",
                description=f"Net '{net_name}' added with pins {pins}.",
                new_value=", ".join(pins),
            )
        )
        checks_invalidated.append(
            f"Re-run connectivity and ERC checks for net '{net_name}'"
        )

    for net_name in sorted(set(old_nets) - set(new_nets)):
        pins = sorted(old_nets[net_name])
        changes.append(
            ChangeRecord(
                change_type="connection_removed",
                category="connections",
                description=f"Net '{net_name}' removed (had pins {pins}).",
                old_value=", ".join(pins),
            )
        )
        checks_invalidated.append(
            f"Re-run connectivity and ERC checks for net '{net_name}'"
        )

    for net_name in sorted(set(old_nets) & set(new_nets)):
        old_pins = old_nets[net_name]
        new_pins = new_nets[net_name]
        if old_pins == new_pins:
            continue
        added = sorted(new_pins - old_pins)
        removed = sorted(old_pins - new_pins)
        parts: list[str] = []
        if added:
            parts.append("added " + ", ".join(added))
        if removed:
            parts.append("removed " + ", ".join(removed))
        changes.append(
            ChangeRecord(
                change_type="connection_pins_changed",
                category="connections",
                description=f"Net '{net_name}' pins changed: " + "; ".join(parts) + ".",
                old_value=", ".join(sorted(old_pins)),
                new_value=", ".join(sorted(new_pins)),
            )
        )
        checks_invalidated.append(
            f"Re-run connectivity and ERC checks for net '{net_name}'"
        )


def _add_requirement_changes(
    old: CircuitDesign,
    new: CircuitDesign,
    changes: list[ChangeRecord],
    checks_invalidated: list[str],
) -> None:
    old_fingerprint = design_fingerprint(old)
    new_fingerprint = design_fingerprint(new)
    if old_fingerprint != new_fingerprint:
        changes.append(
            ChangeRecord(
                change_type="design_fingerprint_changed",
                category="requirements",
                description=(
                    f"Design fingerprint changed from {old_fingerprint} to "
                    f"{new_fingerprint}."
                ),
                old_value=old_fingerprint,
                new_value=new_fingerprint,
            )
        )

    scalar_requirements = [
        ("project_name", "Project name"),
        ("project_description", "Project description"),
        ("supply_voltage_v", "Supply voltage"),
        ("target_frequency_hz", "Target frequency"),
    ]
    for field, label in scalar_requirements:
        old_value = getattr(old, field)
        new_value = getattr(new, field)
        if old_value == new_value:
            continue
        changes.append(
            ChangeRecord(
                change_type="requirement_changed",
                category="requirements",
                description=f"{label} changed from {_format_value(old_value)} to {_format_value(new_value)}.",
                old_value=None if old_value is None else str(old_value),
                new_value=None if new_value is None else str(new_value),
            )
        )
        if field == "supply_voltage_v":
            checks_invalidated.append(
                "Re-run ALL voltage rating checks (supply voltage changed)"
            )
        elif field == "target_frequency_hz":
            checks_invalidated.append(
                "Re-run timing, oscillator and frequency-related checks"
            )

    old_missing = set(old.missing_information)
    new_missing = set(new.missing_information)
    for item in sorted(new_missing - old_missing):
        changes.append(
            ChangeRecord(
                change_type="missing_information_added",
                category="requirements",
                description=f"Missing information added: {item}",
                new_value=item,
            )
        )
        checks_invalidated.append("Re-run checks affected by newly missing information")
    for item in sorted(old_missing - new_missing):
        changes.append(
            ChangeRecord(
                change_type="missing_information_resolved",
                category="requirements",
                description=f"Missing information resolved: {item}",
                old_value=item,
            )
        )

    old_assumptions = set(old.assumptions)
    new_assumptions = set(new.assumptions)
    for item in sorted(new_assumptions - old_assumptions):
        changes.append(
            ChangeRecord(
                change_type="assumption_added",
                category="requirements",
                description=f"Assumption added: {item}",
                new_value=item,
            )
        )
    for item in sorted(old_assumptions - new_assumptions):
        changes.append(
            ChangeRecord(
                change_type="assumption_removed",
                category="requirements",
                description=f"Assumption removed: {item}",
                old_value=item,
            )
        )

    old_notes = set(old.design_notes)
    new_notes = set(new.design_notes)
    for item in sorted(new_notes - old_notes):
        changes.append(
            ChangeRecord(
                change_type="design_note_added",
                category="requirements",
                description=f"Design note added: {item}",
                new_value=item,
            )
        )
    for item in sorted(old_notes - new_notes):
        changes.append(
            ChangeRecord(
                change_type="design_note_removed",
                category="requirements",
                description=f"Design note removed: {item}",
                old_value=item,
            )
        )

    old_board = old.board.model_dump(mode="json")
    new_board = new.board.model_dump(mode="json")
    if old_board != new_board:
        changed_fields = sorted(
            key
            for key in set(old_board) | set(new_board)
            if old_board.get(key) != new_board.get(key)
        )
        changes.append(
            ChangeRecord(
                change_type="board_specification_changed",
                category="requirements",
                description="Board specification changed: " + ", ".join(changed_fields) + ".",
                old_value=str(old_board),
                new_value=str(new_board),
            )
        )


def _add_finding_changes(
    old_red_team: Any,
    new_red_team: Any,
    changes: list[ChangeRecord],
) -> tuple[int, int]:
    old_index = _finding_index(old_red_team)
    new_index = _finding_index(new_red_team)
    old_signatures = set(old_index)
    new_signatures = set(new_index)

    added = sorted(new_signatures - old_signatures)
    for signature in added:
        finding = new_index[signature]
        component = finding.get("component_reference")
        prefix = f"{component}: " if component else ""
        changes.append(
            ChangeRecord(
                change_type="finding_added",
                category="red_team",
                description=(
                    f"New {finding.get('severity', 'UNKNOWN')} Red-Team finding — "
                    f"{prefix}{finding.get('description', '')}"
                ),
                new_value=str(finding),
            )
        )

    resolved = sorted(old_signatures - new_signatures)
    for signature in resolved:
        finding = old_index[signature]
        component = finding.get("component_reference")
        prefix = f"{component}: " if component else ""
        changes.append(
            ChangeRecord(
                change_type="finding_resolved",
                category="red_team",
                description=(
                    f"Resolved {finding.get('severity', 'UNKNOWN')} Red-Team finding — "
                    f"{prefix}{finding.get('description', '')}"
                ),
                old_value=str(finding),
            )
        )

    return len(added), len(resolved)


def _build_human_readable(
    changes: list[ChangeRecord],
    checks_invalidated: list[str],
    validation_invalidated: bool,
    previous_review_still_applicable: bool,
    findings_added: int,
    findings_resolved: int,
) -> tuple[str, str]:
    if not changes:
        return "No changes detected.", (
            "No changes were detected between this version and the previous "
            "version. The previous Red-Team review remains applicable."
        )

    groups: list[tuple[str, str]] = [
        ("component_added", "Components added"),
        ("component_removed", "Components removed"),
        ("component_changed", "Components modified"),
        ("connection_added", "Connections added"),
        ("connection_removed", "Connections removed"),
        ("connection_pins_changed", "Connection pins changed"),
        ("requirement_changed", "Requirements changed"),
        ("missing_information_added", "Missing information added"),
        ("missing_information_resolved", "Missing information resolved"),
        ("assumption_added", "Assumptions added"),
        ("assumption_removed", "Assumptions removed"),
        ("design_note_added", "Design notes added"),
        ("design_note_removed", "Design notes removed"),
        ("board_specification_changed", "Board specification changed"),
        ("design_fingerprint_changed", "Design fingerprint changed"),
        ("finding_added", "Red-Team findings added"),
        ("finding_resolved", "Red-Team findings resolved"),
    ]

    lines = [
        f"Design changed: {len(changes)} modification(s) detected.",
        "",
    ]
    for change_type, label in groups:
        group = [change for change in changes if change.change_type == change_type]
        if not group:
            continue
        lines.append(f"{label}:")
        lines.extend(f"  • {change.description}" for change in group)

    if findings_added or findings_resolved:
        lines.extend(
            [
                "",
                f"Red-Team delta: {findings_added} new finding(s), "
                f"{findings_resolved} resolved finding(s).",
            ]
        )

    if validation_invalidated:
        lines.extend(
            [
                "",
                "Validation invalidated: the design content changed. Re-run the "
                "structural checks, Red-Team review and Virtual Lab procedure.",
            ]
        )
    elif previous_review_still_applicable:
        lines.extend(
            [
                "",
                "The design content is unchanged; the previous review remains applicable.",
            ]
        )

    if checks_invalidated:
        lines.extend(["", "Checks that should be re-run:"])
        lines.extend(f"  ⚠ {item}" for item in sorted(set(checks_invalidated)))

    summary = f"{len(changes)} change(s) detected."
    if findings_added or findings_resolved:
        summary += (
            f" {findings_added} finding(s) added, {findings_resolved} resolved."
        )
    if validation_invalidated:
        summary += " Validation must be re-run."
    return summary, "\n".join(lines)


def detect_changes(
    old: CircuitDesign,
    new: CircuitDesign,
    *,
    old_red_team: Any = None,
    new_red_team: Any = None,
) -> ChangeReport:
    """Compare two designs and return a structured :class:`ChangeReport`.

    ``old_red_team`` and ``new_red_team`` may be :class:`RedTeamReport` objects
    or the JSON snapshots stored by Circuit DNA. They are optional so callers
    can diff designs before any review exists.
    """
    if not isinstance(old, CircuitDesign) or not isinstance(new, CircuitDesign):
        raise TypeError("detect_changes expects two CircuitDesign instances.")

    changes: list[ChangeRecord] = []
    checks_invalidated: list[str] = []

    _add_component_changes(old, new, changes, checks_invalidated)
    _add_connection_changes(old, new, changes, checks_invalidated)
    _add_requirement_changes(old, new, changes, checks_invalidated)
    findings_added, findings_resolved = _add_finding_changes(
        old_red_team, new_red_team, changes
    )

    design_changes = [
        change for change in changes if change.category != "red_team"
    ]
    validation_invalidated = bool(design_changes)
    previous_review_still_applicable = not validation_invalidated

    summary, human_readable = _build_human_readable(
        changes,
        checks_invalidated,
        validation_invalidated,
        previous_review_still_applicable,
        findings_added,
        findings_resolved,
    )

    return ChangeReport(
        has_changes=bool(changes),
        changes=changes,
        summary=summary,
        checks_invalidated=sorted(set(checks_invalidated)),
        human_readable=human_readable,
        validation_invalidated=validation_invalidated,
        previous_review_still_applicable=previous_review_still_applicable,
        findings_added=findings_added,
        findings_resolved=findings_resolved,
    )
