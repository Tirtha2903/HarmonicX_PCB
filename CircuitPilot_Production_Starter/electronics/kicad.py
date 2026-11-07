from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


class KiCadError(RuntimeError):
    pass


def locate_kicad_cli(configured_path: str = "") -> str:
    executable = configured_path.strip() or shutil.which("kicad-cli")
    if not executable:
        raise KiCadError(
            "kicad-cli was not found. Add it to PATH or configure KICAD_CLI_PATH."
        )
    return executable


def run_schematic_erc(
    schematic_path: Path,
    output_dir: Path,
    configured_cli: str = "",
) -> dict:
    schematic_path = schematic_path.expanduser().resolve()
    if not schematic_path.is_file() or schematic_path.suffix.lower() != ".kicad_sch":
        raise KiCadError("Select an existing .kicad_sch schematic file.")

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{schematic_path.stem}_erc.json"
    command = [
        locate_kicad_cli(configured_cli),
        "sch", "erc",
        "--format", "json",
        "--output", str(report_path),
        str(schematic_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise KiCadError("KiCad ERC timed out after 120 seconds.") from exc

    report = None
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            report = report_path.read_text(encoding="utf-8", errors="replace")

    return {
        "status": "passed" if result.returncode == 0 else "failed_or_violations",
        "return_code": result.returncode,
        "report_path": str(report_path),
        "report": report,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "scope": "This ERC report applies only to the supplied KiCad schematic.",
    }
