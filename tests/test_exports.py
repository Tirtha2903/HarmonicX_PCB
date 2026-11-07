"""Tests for the artifact export contract."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from electronics.exports import export_design, export_review_artifacts, safe_slug
from electronics.red_team.models import (
    FindingCategory,
    FindingSeverity,
    RedTeamFinding,
    RedTeamReport,
)
from schemas.circuit import CircuitDesign, Component, Connection
from schemas.fingerprint import design_fingerprint


def _design() -> CircuitDesign:
    return CircuitDesign(
        project_name="Export Test / LED",
        project_description="Artifact contract test",
        supply_voltage_v=5.0,
        components=[
            Component(reference="J1", name="Power connector"),
            Component(reference="R1", name="Resistor", value="220 Ohm"),
            Component(reference="D1", name="LED", value="Red LED"),
        ],
        connections=[
            Connection(net_name="VCC", pins=["J1.1", "R1.1"]),
            Connection(net_name="LED_A", pins=["R1.2", "D1.1"]),
            Connection(net_name="GND", pins=["D1.2", "J1.2"]),
        ],
    )


def _report() -> RedTeamReport:
    finding = RedTeamFinding(
        finding_id="f-1",
        rule_code="PRT-02",
        category=FindingCategory.COMPONENT_PROTECTION,
        severity=FindingSeverity.HIGH,
        component_reference="D1",
        description="No series resistor declared.",
        engineering_reason="LED current is uncontrolled.",
        evidence="No series resistor found.",
        recommended_action="Add a series resistor.",
        confidence=0.8,
        verification_status="DETERMINISTIC",
        data_provenance="user_supplied",
    )
    return RedTeamReport(
        overall_status="NEEDS_REVIEW",
        findings=[finding],
        summary="One high finding.",
        deterministic_checks_run=["led_current_limiting"],
    )


class TestDesignExport:
    def test_creates_the_three_contract_files(self, tmp_path: Path):
        project_dir = export_design(_design(), tmp_path)
        assert project_dir.is_dir()
        assert (project_dir / "circuit_design.json").is_file()
        assert (project_dir / "bom.csv").is_file()
        assert (project_dir / "connections.csv").is_file()

    def test_design_json_round_trips(self, tmp_path: Path):
        design = _design()
        project_dir = export_design(design, tmp_path)
        payload = json.loads(
            (project_dir / "circuit_design.json").read_text(encoding="utf-8")
        )
        assert CircuitDesign.model_validate(payload) == design

    def test_bom_csv_contains_every_component(self, tmp_path: Path):
        project_dir = export_design(_design(), tmp_path)
        with (project_dir / "bom.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        assert [row["reference"] for row in rows] == ["J1", "R1", "D1"]
        assert rows[1]["value"] == "220 Ohm"

    def test_connections_csv_contains_every_net(self, tmp_path: Path):
        project_dir = export_design(_design(), tmp_path)
        with (project_dir / "connections.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        assert {row["net_name"] for row in rows} == {"VCC", "LED_A", "GND"}
        vcc = next(row for row in rows if row["net_name"] == "VCC")
        assert vcc["pins"] == "J1.1 | R1.1"

    def test_project_directory_slug_is_filesystem_safe(self, tmp_path: Path):
        project_dir = export_design(_design(), tmp_path)
        assert " " not in project_dir.name
        assert "/" not in project_dir.name
        assert project_dir.name.startswith("export-test-led_")
        assert safe_slug("  ") == "circuit-design"


class TestReviewArtifacts:
    def test_adds_review_files_without_touching_contract(self, tmp_path: Path):
        design = _design()
        project_dir = export_design(design, tmp_path)
        contract_before = {
            name: (project_dir / name).read_bytes()
            for name in ("circuit_design.json", "bom.csv", "connections.csv")
        }

        paths = export_review_artifacts(design, _report(), project_dir)

        assert paths["red_team_review_json"] == project_dir / "red_team_review.json"
        assert paths["red_team_review_md"] == project_dir / "red_team_review.md"
        assert paths["analysis_manifest"] == project_dir / "analysis_manifest.json"
        for name, content in contract_before.items():
            assert (project_dir / name).read_bytes() == content

    def test_review_json_round_trips(self, tmp_path: Path):
        design = _design()
        project_dir = export_design(design, tmp_path)
        export_review_artifacts(design, _report(), project_dir)
        payload = json.loads(
            (project_dir / "red_team_review.json").read_text(encoding="utf-8")
        )
        restored = RedTeamReport.model_validate(payload)
        assert restored.overall_status == "NEEDS_REVIEW"
        assert len(restored.findings) == 1

    def test_markdown_report_is_written(self, tmp_path: Path):
        design = _design()
        project_dir = export_design(design, tmp_path)
        export_review_artifacts(design, _report(), project_dir)
        markdown = (project_dir / "red_team_review.md").read_text(encoding="utf-8")
        assert "No series resistor declared." in markdown

    def test_manifest_records_fingerprint_and_limits(self, tmp_path: Path):
        design = _design()
        project_dir = export_design(design, tmp_path)
        export_review_artifacts(design, _report(), project_dir)
        manifest = json.loads(
            (project_dir / "analysis_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["design_fingerprint"] == design_fingerprint(design)
        assert manifest["overall_status"] == "NEEDS_REVIEW"
        assert manifest["artifact_contract"] == [
            "circuit_design.json",
            "bom.csv",
            "connections.csv",
        ]
        assert manifest["simulation_performed"] is False
        assert manifest["erc_performed"] is False
        assert manifest["safety_certified"] is False

    def test_missing_directory_is_rejected(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            export_review_artifacts(
                _design(), _report(), tmp_path / "does-not-exist"
            )
