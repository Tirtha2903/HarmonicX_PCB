from __future__ import annotations

import csv
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from schemas.circuit import CircuitDesign


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
