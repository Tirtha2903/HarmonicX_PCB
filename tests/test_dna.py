from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from electronics.red_team.models import (
    FindingCategory,
    FindingSeverity,
    RedTeamFinding,
    RedTeamReport,
)
from schemas.circuit import BoardSpecifications, CircuitDesign, Component, Connection
from schemas.fingerprint import design_fingerprint
from services.dna.diff import detect_changes
from services.dna.identity import generate_circuit_id
from services.dna.storage import DNAStorage


def _make_design(name="Test Circuit", supply=5.0, **kwargs) -> CircuitDesign:
    defaults = dict(
        project_name=name,
        project_description="A test circuit",
        supply_voltage_v=supply,
        components=[
            Component(reference="R1", name="Resistor", value="220 Ohm", evidence_status="unverified"),
            Component(reference="D1", name="LED", value="Red LED", evidence_status="unverified"),
        ],
        connections=[
            Connection(net_name="GND", pins=["R1.2", "D1.2"], confidence=0.9),
            Connection(net_name="VCC", pins=["R1.1", "D1.1"], confidence=0.9),
        ],
    )
    defaults.update(kwargs)
    return CircuitDesign(**defaults)


# ---------------------------------------------------------------------------
# Identity tests
# ---------------------------------------------------------------------------

class TestGenerateCircuitId:
    def test_generates_cp_prefix(self):
        design = _make_design(name="NE555 Timer")
        cid = generate_circuit_id(design, 1)
        assert cid.startswith("CP-")

    def test_padded_sequence(self):
        design = _make_design(name="NE555 Timer")
        cid = generate_circuit_id(design, 1)
        assert cid.endswith("-0001")

    def test_different_sequence_numbers(self):
        design = _make_design()
        id1 = generate_circuit_id(design, 1)
        id2 = generate_circuit_id(design, 2)
        assert id1 != id2
        assert id1.endswith("-0001")
        assert id2.endswith("-0002")

    def test_stable_for_same_input(self):
        design = _make_design(name="Stable Test")
        id1 = generate_circuit_id(design, 1)
        id2 = generate_circuit_id(design, 1)
        assert id1 == id2


# ---------------------------------------------------------------------------
# Diff / change detection tests
# ---------------------------------------------------------------------------

class TestDetectChanges:
    def test_no_changes_for_identical_designs(self):
        design = _make_design()
        report = detect_changes(design, design)
        assert not report.has_changes
        assert report.changes == []

    def test_detects_component_added(self):
        old = _make_design()
        new = CircuitDesign(
            project_name="Test Circuit",
            project_description="A test circuit",
            supply_voltage_v=5.0,
            components=[
                Component(reference="R1", name="Resistor", value="220 Ohm", evidence_status="unverified"),
                Component(reference="D1", name="LED", value="Red LED", evidence_status="unverified"),
                Component(reference="C1", name="Capacitor", value="100nF", evidence_status="unverified"),
            ],
            connections=[
                Connection(net_name="GND", pins=["R1.2", "D1.2"], confidence=0.9),
                Connection(net_name="VCC", pins=["R1.1", "D1.1"], confidence=0.9),
            ],
        )
        report = detect_changes(old, new)
        assert report.has_changes
        added = [c for c in report.changes if c.change_type == "component_added"]
        assert any("C1" in c.description for c in added)

    def test_detects_component_value_change(self):
        old = _make_design()
        new = CircuitDesign(
            project_name="Test Circuit",
            project_description="A test circuit",
            supply_voltage_v=5.0,
            components=[
                Component(reference="R1", name="Resistor", value="470 Ohm", evidence_status="unverified"),
                Component(reference="D1", name="LED", value="Red LED", evidence_status="unverified"),
            ],
            connections=[
                Connection(net_name="GND", pins=["R1.2", "D1.2"], confidence=0.9),
                Connection(net_name="VCC", pins=["R1.1", "D1.1"], confidence=0.9),
            ],
        )
        report = detect_changes(old, new)
        assert report.has_changes
        changed = [c for c in report.changes if c.change_type == "component_changed"]
        assert any("R1" in c.description for c in changed)
        assert any("470" in (c.new_value or "") for c in changed)

    def test_detects_supply_voltage_change(self):
        old = _make_design(supply=5.0)
        new = _make_design(supply=12.0)
        report = detect_changes(old, new)
        assert report.has_changes
        req_changes = [c for c in report.changes if c.change_type == "requirement_changed"]
        assert len(req_changes) >= 1
        assert "voltage" in req_changes[0].description.lower()
        assert "Re-run ALL voltage rating checks" in " ".join(report.checks_invalidated)

    def test_human_readable_summary_present(self):
        old = _make_design()
        new = _make_design(supply=12.0)
        report = detect_changes(old, new)
        assert report.human_readable != ""


# ---------------------------------------------------------------------------
# Storage tests
# ---------------------------------------------------------------------------

class TestDNAStorage:
    def _get_db(self) -> DNAStorage:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "test_dna.db"
        return DNAStorage(db_path)

    def test_empty_db_has_no_circuits(self):
        db = self._get_db()
        assert db.list_circuits() == []

    def test_save_creates_new_circuit(self):
        db = self._get_db()
        design = _make_design()
        cid, ver = db.save_version(design)
        assert cid.startswith("CP-")
        assert ver == "1.0"

    def test_save_second_version_increments(self):
        db = self._get_db()
        design = _make_design()
        cid, ver1 = db.save_version(design)
        _, ver2 = db.save_version(design, circuit_id=cid)
        assert ver1 == "1.0"
        assert ver2 == "1.1"

    def test_versions_are_preserved(self):
        db = self._get_db()
        design1 = _make_design()
        design2 = _make_design(supply=12.0)
        cid, _ = db.save_version(design1)
        db.save_version(design2, circuit_id=cid)
        record = db.get_record(cid)
        assert record is not None
        assert len(record.versions) == 2

    def test_get_record_returns_correct_data(self):
        db = self._get_db()
        design = _make_design(name="DNA Test Circuit")
        cid, _ = db.save_version(design, notes="Initial version")
        record = db.get_record(cid)
        assert record is not None
        assert record.circuit_id == cid
        assert record.name == "DNA Test Circuit"
        assert len(record.versions) == 1
        assert record.versions[0].notes == "Initial version"

    def test_change_detected_between_versions(self):
        db = self._get_db()
        design1 = _make_design(supply=5.0)
        design2 = _make_design(supply=12.0)
        cid, _ = db.save_version(design1)
        db.save_version(design2, circuit_id=cid)
        record = db.get_record(cid)
        v2 = record.versions[1]
        assert v2.change_from_previous is not None
        assert v2.change_from_previous.has_changes

    def test_list_circuits_shows_saved_circuit(self):
        db = self._get_db()
        design = _make_design()
        cid, _ = db.save_version(design)
        circuits = db.list_circuits()
        assert len(circuits) == 1
        assert circuits[0]["circuit_id"] == cid

    def test_get_version_design(self):
        db = self._get_db()
        design = _make_design()
        cid, ver = db.save_version(design)
        retrieved = db.get_version_design(cid, ver)
        assert retrieved is not None
        assert retrieved.project_name == design.project_name


def _finding(description: str = "No series resistor declared.") -> RedTeamFinding:
    return RedTeamFinding(
        finding_id="finding-1",
        rule_code="PRT-02",
        category=FindingCategory.COMPONENT_PROTECTION,
        severity=FindingSeverity.HIGH,
        component_reference="D1",
        description=description,
        engineering_reason="LED current is uncontrolled.",
        evidence="No series resistor was found.",
        recommended_action="Add a series current-limiting resistor.",
        confidence=0.8,
        verification_status="DETERMINISTIC",
        data_provenance="user_supplied",
    )


def _report(*findings: RedTeamFinding) -> RedTeamReport:
    return RedTeamReport(
        overall_status="NEEDS_REVIEW" if findings else "PASS",
        findings=list(findings),
        summary=f"{len(findings)} finding(s).",
        deterministic_checks_run=["led_current_limiting"],
    )


class TestDetectChangesExtended:
    def test_connection_pin_change_is_detected(self):
        old = _make_design()
        new = _make_design(
            connections=[
                Connection(net_name="GND", pins=["R1.2", "D1.2"], confidence=0.9),
                Connection(net_name="VCC", pins=["R1.1", "D1.2"], confidence=0.9),
            ]
        )
        report = detect_changes(old, new)
        pin_changes = [
            change for change in report.changes
            if change.change_type == "connection_pins_changed"
        ]
        assert pin_changes
        assert any("D1.1" in (change.old_value or "") for change in pin_changes)
        assert report.validation_invalidated is True
        assert any(
            "connectivity" in item.lower()
            for item in report.checks_invalidated
        )

    def test_missing_information_added_and_resolved(self):
        added = detect_changes(
            _make_design(),
            _make_design(missing_information=["Supply current is unknown"]),
        )
        assert any(
            change.change_type == "missing_information_added"
            for change in added.changes
        )

        resolved = detect_changes(
            _make_design(missing_information=["Supply current is unknown"]),
            _make_design(),
        )
        assert any(
            change.change_type == "missing_information_resolved"
            for change in resolved.changes
        )

    def test_assumptions_are_diffed(self):
        added = detect_changes(
            _make_design(),
            _make_design(assumptions=["The supply is regulated."]),
        )
        assert any(
            change.change_type == "assumption_added" for change in added.changes
        )

        removed = detect_changes(
            _make_design(assumptions=["The supply is regulated."]),
            _make_design(),
        )
        assert any(
            change.change_type == "assumption_removed" for change in removed.changes
        )

    def test_board_specification_change_is_detected(self):
        report = detect_changes(
            _make_design(),
            _make_design(board=BoardSpecifications(layers=4)),
        )
        board_changes = [
            change for change in report.changes
            if change.change_type == "board_specification_changed"
        ]
        assert len(board_changes) == 1
        assert "layers" in board_changes[0].description
        assert report.validation_invalidated is True

    def test_findings_added_and_resolved_are_counted(self):
        old_report = _report(_finding("No series resistor declared."))
        new_report = _report(
            _finding("No series resistor declared."),
            _finding("Resistor power rating is unknown."),
        )
        report = detect_changes(
            _make_design(),
            _make_design(),
            old_red_team=old_report,
            new_red_team=new_report,
        )
        assert report.findings_added == 1
        assert report.findings_resolved == 0
        assert report.validation_invalidated is False
        assert report.previous_review_still_applicable is True
        assert any(
            change.change_type == "finding_added" for change in report.changes
        )

        resolved_report = _report()
        resolved = detect_changes(
            _make_design(),
            _make_design(),
            old_red_team=old_report,
            new_red_team=resolved_report,
        )
        assert resolved.findings_added == 0
        assert resolved.findings_resolved == 1
        assert any(
            change.change_type == "finding_resolved"
            for change in resolved.changes
        )

    def test_unchanged_design_and_review_has_no_changes(self):
        report = detect_changes(
            _make_design(),
            _make_design(),
            old_red_team=_report(_finding()),
            new_red_team=_report(_finding()),
        )
        assert report.has_changes is False
        assert report.validation_invalidated is False
        assert report.previous_review_still_applicable is True
        assert "No changes were detected" in report.human_readable
        assert report.summary == "No changes detected."

    def test_confidence_only_change_is_not_a_design_change(self):
        old = _make_design()
        new = old.model_copy(deep=True)
        for component in new.components:
            component.confidence = 0.1
        for connection in new.connections:
            connection.confidence = 0.1
        new.overall_confidence = 0.1
        report = detect_changes(old, new)
        assert report.has_changes is False

    def test_non_design_type_is_rejected(self):
        with pytest.raises(TypeError):
            detect_changes(_make_design(), {"project_name": "not a design"})


class TestDNAStorageExtended:
    def _get_db(self) -> DNAStorage:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "test_dna.db"
        return DNAStorage(db_path)

    def test_invalid_circuit_id_is_rejected(self):
        db = self._get_db()
        import pytest

        with pytest.raises(ValueError):
            db.save_version(_make_design(), circuit_id="not-a-circuit-id")

    def test_unknown_circuit_id_is_rejected_without_creating_a_record(self):
        db = self._get_db()
        import pytest

        with pytest.raises(ValueError):
            db.save_version(_make_design(), circuit_id="CP-UNKNOWN-0001")
        assert db.list_circuits() == []

    def test_design_hash_is_persisted(self):
        db = self._get_db()
        design = _make_design()
        cid, _ = db.save_version(design)
        record = db.get_record(cid)
        assert record is not None
        assert record.latest_version is not None
        assert record.latest_version.design_hash == design_fingerprint(design)
        assert record.current_fingerprint == design_fingerprint(design)

    def test_snapshots_round_trip(self):
        db = self._get_db()
        design = _make_design()
        checks = {"status": "needs_review", "electrical_erc_performed": False}
        red_team = _report(_finding())
        cid, version = db.save_version(
            design, checks=checks, red_team=red_team, notes="Initial review"
        )
        stored = db.get_version(cid, version)
        assert stored is not None
        assert stored.checks_snapshot == checks
        assert stored.red_team_snapshot is not None
        assert stored.red_team_snapshot["overall_status"] == "NEEDS_REVIEW"
        assert stored.review_status == "NEEDS_REVIEW"
        assert stored.reviewed_at is not None
        assert stored.design_snapshot["project_name"] == design.project_name

    def test_previous_versions_are_preserved_append_only(self):
        db = self._get_db()
        original = _make_design(supply=5.0)
        updated = _make_design(supply=12.0)
        cid, first = db.save_version(original)
        _, second = db.save_version(updated, circuit_id=cid)
        assert first == "1.0"
        assert second == "1.1"
        assert db.get_version_design(cid, first) == original
        assert db.get_version_design(cid, second) == updated
        record = db.get_record(cid)
        assert record is not None
        assert record.version_count == 2

    def test_same_design_twice_appends_without_invalidating_review(self):
        db = self._get_db()
        design = _make_design()
        cid, _ = db.save_version(design, red_team=_report(_finding()))
        _, second = db.save_version(
            design, circuit_id=cid, red_team=_report(_finding())
        )
        stored = db.get_version(cid, second)
        assert stored is not None
        change = stored.change_from_previous
        assert change is not None
        assert change.has_changes is False
        assert change.validation_invalidated is False
        assert change.previous_review_still_applicable is True

    def test_design_change_invalidates_validation_and_reports_findings(self):
        db = self._get_db()
        cid, _ = db.save_version(
            _make_design(supply=5.0), red_team=_report(_finding())
        )
        _, second = db.save_version(
            _make_design(supply=12.0),
            circuit_id=cid,
            red_team=_report(),
        )
        stored = db.get_version(cid, second)
        assert stored is not None
        change = stored.change_from_previous
        assert change is not None
        assert change.validation_invalidated is True
        assert change.findings_resolved == 1
        assert any(
            "voltage" in item.lower() for item in change.checks_invalidated
        )

    def test_get_version_design_and_version_return_none_when_missing(self):
        db = self._get_db()
        cid, _ = db.save_version(_make_design())
        assert db.get_version_design(cid, "9.9") is None
        assert db.get_version(cid, "9.9") is None
        assert db.get_record("CP-MISSING-0001") is None

    def test_circuit_metadata_updates_with_latest_version(self):
        db = self._get_db()
        cid, _ = db.save_version(_make_design(name="Old Name"))
        db.save_version(_make_design(name="New Name"), circuit_id=cid)
        record = db.get_record(cid)
        assert record is not None
        assert record.name == "New Name"
        assert len(db.list_circuits()) == 1
