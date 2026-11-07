from __future__ import annotations

import csv
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from schemas.circuit import CircuitDesign
from schemas.fingerprint import design_fingerprint


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-_").lower()
    return (slug[:48] or "circuit-design")


def export_design(design: CircuitDesign, output_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Append a short random suffix to avoid collisions when two requests land
    # within the same second (e.g. rapid testing or multi-tab use).
    unique_suffix = uuid.uuid4().hex[:6]
    project_dir = output_root / f"{safe_slug(design.project_name)}_{timestamp}_{unique_suffix}"
    project_dir.mkdir(parents=True, exist_ok=True)

    payload = design.model_dump(mode="json")
    (project_dir / "circuit_design.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    with (project_dir / "bom.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "reference", "name", "quantity", "value", "footprint",
                "manufacturer_part_number", "datasheet_url", "evidence_status",
                "confidence",
            ],
        )
        writer.writeheader()
        for component in design.components:
            writer.writerow({
                "reference": component.reference,
                "name": component.name,
                "quantity": component.quantity,
                "value": component.value or "",
                "footprint": component.footprint or "",
                "manufacturer_part_number": component.manufacturer_part_number or "",
                "datasheet_url": component.datasheet_url or "",
                "evidence_status": component.evidence_status,
                "confidence": component.confidence,
            })

    with (project_dir / "connections.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["net_name", "pins", "confidence", "evidence"],
        )
        writer.writeheader()
        for connection in design.connections:
            writer.writerow({
                "net_name": connection.net_name,
                "pins": " | ".join(connection.pins),
                "confidence": connection.confidence,
                "evidence": connection.evidence or "",
            })

    return project_dir


def export_review_artifacts(
    design: CircuitDesign,
    red_team,
    project_dir: Path,
) -> dict[str, Path]:
    """Write Red-Team artifacts next to the existing design exports.

    The original ``circuit_design.json``, ``bom.csv`` and ``connections.csv``
    contract is untouched. These files are additive.
    """
    if not project_dir.exists():
        raise FileNotFoundError(f"Artifact directory does not exist: {project_dir}")

    review_json = project_dir / "red_team_review.json"
    review_md = project_dir / "red_team_review.md"
    review_json.write_text(
        json.dumps(red_team.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    from electronics.red_team.report import report_to_markdown

    review_md.write_text(report_to_markdown(red_team, design), encoding="utf-8")

    manifest = project_dir / "analysis_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "project_name": design.project_name,
                "design_fingerprint": design_fingerprint(design),
                "reviewed_at": red_team.reviewed_at,
                "overall_status": red_team.overall_status,
                "artifact_contract": [
                    "circuit_design.json",
                    "bom.csv",
                    "connections.csv",
                ],
                "additive_artifacts": [
                    "red_team_review.json",
                    "red_team_review.md",
                    "analysis_manifest.json",
                ],
                "simulation_performed": False,
                "erc_performed": False,
                "safety_certified": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "red_team_review_json": review_json,
        "red_team_review_md": review_md,
        "analysis_manifest": manifest,
    }
