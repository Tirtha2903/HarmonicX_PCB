"""SQLite persistence layer for Circuit DNA.

The store is append-only: a version row is inserted once and is never updated or
deleted. Each version keeps the full design snapshot, the deterministic check
snapshot, the Red-Team review snapshot and the change report against the
previous version.

Only engineering data is stored. API keys, provider settings and other secrets
are never written to the database.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from schemas.circuit import CircuitDesign
from schemas.fingerprint import design_fingerprint
from services.dna.diff import detect_changes
from services.dna.identity import generate_circuit_id, is_valid_circuit_id
from services.dna.models import ChangeReport, CircuitDNARecord, DNAVersion

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS circuits (
    circuit_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    circuit_id       TEXT NOT NULL,
    version          TEXT NOT NULL,
    design_json      TEXT NOT NULL,
    design_hash      TEXT NOT NULL DEFAULT '',
    checks_json      TEXT,
    red_team_json    TEXT,
    change_json      TEXT,
    notes            TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    FOREIGN KEY (circuit_id) REFERENCES circuits(circuit_id)
);

CREATE INDEX IF NOT EXISTS idx_versions_circuit
    ON versions(circuit_id, id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _version_bump(current: str) -> str:
    """Increment the last numeric component: ``1.0`` -> ``1.1``."""
    parts = current.split(".")
    if not parts:
        return "1.0"
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except ValueError:
        return f"{current}.1"
    return ".".join(parts)


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        logger.warning("Ignoring unreadable Circuit DNA JSON column")
        return None


class DNAStorage:
    """SQLite-backed append-only store for Circuit DNA records."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Open a connection and always close it, even on error."""
        connection = sqlite3.connect(str(self.db_path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connection() as connection:
            connection.executescript(_SCHEMA)
            # Migrate databases created by earlier builds that had no hash
            # column. Existing rows keep an empty hash and it is computed on read.
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(versions)").fetchall()
            }
            if "design_hash" not in columns:
                connection.execute(
                    "ALTER TABLE versions ADD COLUMN design_hash TEXT NOT NULL DEFAULT ''"
                )
            if "red_team_json" not in columns:
                connection.execute("ALTER TABLE versions ADD COLUMN red_team_json TEXT")

    # ------------------------------------------------------------------
    # Circuit creation and listing
    # ------------------------------------------------------------------

    def list_circuits(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.circuit_id,
                       c.name,
                       c.description,
                       c.created_at,
                       COUNT(v.id) AS version_count
                FROM circuits AS c
                LEFT JOIN versions AS v ON v.circuit_id = c.circuit_id
                GROUP BY c.circuit_id
                ORDER BY c.created_at DESC, c.circuit_id DESC
                """
            ).fetchall()
            return [
                {
                    "circuit_id": row["circuit_id"],
                    "name": row["name"],
                    "description": row["description"],
                    "created_at": row["created_at"],
                    "version_count": int(row["version_count"]),
                }
                for row in rows
            ]

    def circuit_exists(self, circuit_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM circuits WHERE circuit_id = ?", (circuit_id,)
            ).fetchone()
            return row is not None

    def _next_circuit_id(
        self,
        connection: sqlite3.Connection,
        design: CircuitDesign,
    ) -> str:
        slug_base = generate_circuit_id(design, 1).rsplit("-", 1)[0]
        rows = connection.execute(
            "SELECT circuit_id FROM circuits WHERE circuit_id LIKE ?",
            (f"{slug_base}-%",),
        ).fetchall()
        sequences: list[int] = []
        for row in rows:
            try:
                sequences.append(int(row["circuit_id"].rsplit("-", 1)[1]))
            except (ValueError, IndexError):
                continue
        sequence = max(sequences) + 1 if sequences else 1
        return generate_circuit_id(design, sequence)

    # ------------------------------------------------------------------
    # Saving versions
    # ------------------------------------------------------------------

    def save_version(
        self,
        design: CircuitDesign,
        checks: dict | None = None,
        red_team: Any = None,
        notes: str = "",
        circuit_id: str | None = None,
    ) -> tuple[str, str]:
        """Append a new version and return ``(circuit_id, version)``.

        ``circuit_id`` is optional. When supplied it must be a valid identifier
        that already exists; this method never silently creates a new circuit
        under an unknown ID.
        """
        if not isinstance(design, CircuitDesign):
            raise TypeError("design must be a CircuitDesign instance.")

        requested_id = circuit_id.strip() if circuit_id else None
        if requested_id is not None and not is_valid_circuit_id(requested_id):
            raise ValueError(
                f"Invalid circuit ID {requested_id!r}. Expected a value such as "
                "CP-NE555-0001."
            )

        notes = (notes or "").strip()[:2000]
        design_json = design.model_dump_json()
        design_hash = design_fingerprint(design)
        checks_json = _json_text(checks)
        red_team_json = _json_text(red_team)

        with self._connection() as connection:
            if requested_id is None:
                new_id = self._next_circuit_id(connection, design)
                connection.execute(
                    "INSERT INTO circuits (circuit_id, name, description, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        new_id,
                        design.project_name,
                        design.project_description,
                        _now_iso(),
                    ),
                )
                circuit_id = new_id
                version = "1.0"
                change_json = None
            else:
                existing = connection.execute(
                    "SELECT 1 FROM circuits WHERE circuit_id = ?", (requested_id,)
                ).fetchone()
                if existing is None:
                    raise ValueError(
                        f"Circuit ID {requested_id!r} does not exist. Omit "
                        "circuit_id to create a new circuit."
                    )
                circuit_id = requested_id
                last_row = connection.execute(
                    "SELECT version, design_json, red_team_json FROM versions "
                    "WHERE circuit_id = ? ORDER BY id DESC LIMIT 1",
                    (circuit_id,),
                ).fetchone()
                if last_row is None:
                    version = "1.0"
                    change_json = None
                else:
                    version = _version_bump(str(last_row["version"]))
                    try:
                        old_design = CircuitDesign.model_validate_json(
                            last_row["design_json"]
                        )
                    except Exception as exc:
                        logger.warning(
                            "Previous Circuit DNA design snapshot is unreadable: %s", exc
                        )
                        old_design = None
                    if old_design is not None:
                        change_report = detect_changes(
                            old_design,
                            design,
                            old_red_team=_load_json(last_row["red_team_json"]),
                            new_red_team=red_team,
                        )
                        change_json = change_report.model_dump_json()
                    else:
                        change_json = None
                connection.execute(
                    "UPDATE circuits SET name = ?, description = ? WHERE circuit_id = ?",
                    (design.project_name, design.project_description, circuit_id),
                )

            duplicate = connection.execute(
                "SELECT 1 FROM versions WHERE circuit_id = ? AND version = ?",
                (circuit_id, version),
            ).fetchone()
            if duplicate is not None:
                raise RuntimeError(
                    f"Version {version} already exists for {circuit_id}; refusing to overwrite."
                )

            connection.execute(
                "INSERT INTO versions "
                "(circuit_id, version, design_json, design_hash, checks_json, "
                "red_team_json, change_json, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    circuit_id,
                    version,
                    design_json,
                    design_hash,
                    checks_json,
                    red_team_json,
                    change_json,
                    notes,
                    _now_iso(),
                ),
            )
            return circuit_id, version

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_record(self, circuit_id: str) -> CircuitDNARecord | None:
        with self._connection() as connection:
            circuit_row = connection.execute(
                "SELECT * FROM circuits WHERE circuit_id = ?", (circuit_id,)
            ).fetchone()
            if circuit_row is None:
                return None

            version_rows = connection.execute(
                "SELECT * FROM versions WHERE circuit_id = ? ORDER BY id ASC",
                (circuit_id,),
            ).fetchall()

        versions: list[DNAVersion] = []
        for row in version_rows:
            design_snapshot = _load_json(row["design_json"]) or {}
            stored_hash = row["design_hash"] if "design_hash" in row.keys() else ""
            design_hash = stored_hash or ""
            if not design_hash and design_snapshot:
                try:
                    design_hash = design_fingerprint(
                        CircuitDesign.model_validate(design_snapshot)
                    )
                except Exception:
                    design_hash = ""

            change_report: ChangeReport | None = None
            change_snapshot = _load_json(row["change_json"])
            if change_snapshot:
                try:
                    change_report = ChangeReport.model_validate(change_snapshot)
                except Exception as exc:
                    logger.warning("Unreadable change report in Circuit DNA: %s", exc)

            versions.append(
                DNAVersion(
                    version=str(row["version"]),
                    created_at=str(row["created_at"]),
                    notes=str(row["notes"] or ""),
                    design_snapshot=design_snapshot,
                    design_hash=design_hash,
                    checks_snapshot=_load_json(row["checks_json"]),
                    red_team_snapshot=_load_json(row["red_team_json"]),
                    change_from_previous=change_report,
                )
            )

        return CircuitDNARecord(
            circuit_id=str(circuit_row["circuit_id"]),
            name=str(circuit_row["name"]),
            created_at=str(circuit_row["created_at"]),
            description=str(circuit_row["description"] or ""),
            versions=versions,
        )

    def get_version(self, circuit_id: str, version: str) -> DNAVersion | None:
        record = self.get_record(circuit_id)
        if record is None:
            return None
        return record.version(version)

    def get_version_design(
        self, circuit_id: str, version: str
    ) -> CircuitDesign | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT design_json FROM versions "
                "WHERE circuit_id = ? AND version = ? LIMIT 1",
                (circuit_id, version),
            ).fetchone()
        if row is None:
            return None
        try:
            return CircuitDesign.model_validate_json(row["design_json"])
        except Exception as exc:
            logger.warning("Unreadable Circuit DNA design snapshot: %s", exc)
            return None
