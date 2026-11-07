"""Pydantic models for Circuit DNA."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChangeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_type: str
    description: str
    old_value: str | None = None
    new_value: str | None = None
    category: str | None = None


class ChangeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    has_changes: bool
    changes: list[ChangeRecord] = Field(default_factory=list)
    summary: str
    checks_invalidated: list[str] = Field(default_factory=list)
    human_readable: str = ""
    validation_invalidated: bool = False
    previous_review_still_applicable: bool = True
    findings_added: int = 0
    findings_resolved: int = 0


class DNAVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    created_at: str
    notes: str = ""
    design_snapshot: dict[str, Any]
    design_hash: str = ""
    checks_snapshot: dict[str, Any] | None = None
    red_team_snapshot: dict[str, Any] | None = None
    change_from_previous: ChangeReport | None = None

    @property
    def reviewed_at(self) -> str | None:
        if not self.red_team_snapshot:
            return None
        value = self.red_team_snapshot.get("reviewed_at")
        return str(value) if value else None

    @property
    def review_status(self) -> str | None:
        if not self.red_team_snapshot:
            return None
        value = self.red_team_snapshot.get("overall_status")
        return str(value) if value else None


class CircuitDNARecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    circuit_id: str
    name: str
    created_at: str
    description: str
    versions: list[DNAVersion] = Field(default_factory=list)

    @property
    def latest_version(self) -> DNAVersion | None:
        return self.versions[-1] if self.versions else None

    @property
    def version_count(self) -> int:
        return len(self.versions)

    @property
    def current_fingerprint(self) -> str | None:
        latest = self.latest_version
        return latest.design_hash or None if latest else None

    def version(self, version: str) -> DNAVersion | None:
        return next((item for item in self.versions if item.version == version), None)
