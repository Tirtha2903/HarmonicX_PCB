from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Component(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=1, ge=1, le=1000)
    value: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    footprint: str | None = Field(default=None, max_length=120)
    voltage_rating_v: float | None = Field(default=None, gt=0)
    current_rating_a: float | None = Field(default=None, gt=0)
    manufacturer_part_number: str | None = Field(default=None, max_length=120)
    datasheet_url: str | None = Field(default=None, max_length=500)
    evidence_status: Literal["verified", "unverified", "user_supplied"] = "unverified"
    confidence: float = Field(default=0.5, ge=0, le=1)

    @field_validator("reference")
    @classmethod
    def reference_format(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,19}", value):
            raise ValueError("Reference must be a short designator such as R1, C1 or U1.")
        return value


class Connection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    net_name: str = Field(min_length=1, max_length=80)
    pins: list[str] = Field(min_length=2, max_length=100)
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence: str | None = Field(default=None, max_length=500)

    @field_validator("pins")
    @classmethod
    def pin_format(cls, pins: list[str]) -> list[str]:
        cleaned = [pin.strip().upper() for pin in pins]
        for pin in cleaned:
            if not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,19}\.[A-Z0-9_-]{1,20}", pin):
                raise ValueError(
                    f"Pin '{pin}' must use REF.PIN format, for example U1.2."
                )
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("A connection cannot contain duplicate pin references.")
        return cleaned


class BoardSpecifications(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layers: int = Field(default=2, ge=1, le=16)
    board_width_mm: float | None = Field(default=None, gt=0, le=1000)
    board_height_mm: float | None = Field(default=None, gt=0, le=1000)
    board_material: str = Field(default="FR4", max_length=80)
    copper_weight_oz: float | None = Field(default=None, gt=0, le=10)
    manufacturing_notes: list[str] = Field(default_factory=list)


class CircuitDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(min_length=1, max_length=100)
    project_description: str = Field(min_length=1, max_length=2000)
    supply_voltage_v: float | None = Field(default=None, gt=0)
    target_frequency_hz: float | None = Field(default=None, gt=0)
    components: list[Component] = Field(default_factory=list, max_length=250)
    connections: list[Connection] = Field(default_factory=list, max_length=1000)
    board: BoardSpecifications = Field(default_factory=BoardSpecifications)
    missing_information: list[str] = Field(default_factory=list, max_length=100)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    requires_confirmation: bool = True
    design_notes: list[str] = Field(default_factory=list, max_length=100)
    overall_confidence: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def check_references_and_confirmation(self):
        refs = [component.reference for component in self.components]
        if len(refs) != len(set(refs)):
            raise ValueError("Component reference designators must be unique.")

        known_refs = set(refs)
        unknown = sorted({
            pin.split(".", 1)[0]
            for connection in self.connections
            for pin in connection.pins
            if pin.split(".", 1)[0] not in known_refs
        })
        if unknown:
            raise ValueError(
                "Connections refer to undeclared components: " + ", ".join(unknown)
            )

        uncertain_components = any(
            component.evidence_status == "unverified"
            or component.confidence < 0.85
            for component in self.components
        )
        uncertain_connections = any(
            connection.confidence < 0.85 for connection in self.connections
        )
        if (
            self.missing_information
            or uncertain_components
            or uncertain_connections
            or not self.components
            or not self.connections
        ):
            self.requires_confirmation = True

        return self
