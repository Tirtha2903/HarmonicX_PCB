from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from schemas.circuit import CircuitDesign
from services.llm_client import OpenAICompatibleClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are CircuitPilot, a cautious electronics design-analysis assistant.
Analyze the user's natural-language requirements and optional circuit image.
Return exactly one JSON object matching the CircuitDesign schema described below.
Do not return Markdown fences, commentary, or additional keys.

Schema:
{
  "project_name": "short name",
  "project_description": "concise functional description",
  "supply_voltage_v": number or null,
  "target_frequency_hz": number or null,
  "components": [{
    "reference": "R1",
    "name": "resistor",
    "quantity": 1,
    "value": "10 kOhm",
    "description": "purpose",
    "footprint": null,
    "voltage_rating_v": null,
    "current_rating_a": null,
    "manufacturer_part_number": null,
    "datasheet_url": null,
    "evidence_status": "unverified",
    "confidence": 0.0
  }],
  "connections": [{
    "net_name": "GND",
    "pins": ["U1.1", "C1.2"],
    "confidence": 0.0,
    "evidence": "why this connection is supported"
  }],
  "board": {
    "layers": 2,
    "board_width_mm": null,
    "board_height_mm": null,
    "board_material": "FR4",
    "copper_weight_oz": null,
    "manufacturing_notes": []
  },
  "missing_information": [],
  "assumptions": [],
  "requires_confirmation": true,
  "design_notes": [],
  "overall_confidence": 0.0
}

Engineering rules:
1. Never invent pin numbers or electrical connections. Include a connection only
   when explicitly specified or clearly identifiable from the supplied image.
2. If a pin label, wire junction, component identity or value is unclear, state
   the ambiguity in missing_information and lower confidence.
3. Never invent manufacturer part numbers, datasheet URLs or verified evidence.
   Use null and evidence_status="unverified" unless the user supplies evidence.
4. Use unique reference designators (R1, C1, U1, D1, J1, etc.).
5. Connections use REF.PIN strings, for example U1.2. Do not infer a pin map
   from a generic part name if the exact part/package is unknown.
6. Distinguish user-specified facts from assumptions.
7. Set requires_confirmation=true whenever important electrical details are
   missing, ambiguous or unverified.
8. Do not claim ERC, DRC, simulation, safety, thermal, signal-integrity or
   manufacturing verification. Those require separate engineering tools.
9. Never provide hidden chain-of-thought. Give concise design_notes and
   assumptions, not private reasoning.
10. If the request is insufficient to identify a real circuit, return a useful
    partial analysis and list the information needed.
"""


class DesignAgent:
    def __init__(self, client: OpenAICompatibleClient):
        self.client = client

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        # Strip Markdown code fences, tolerating optional language tag and trailing
        # newlines before the closing fence (e.g. ```json\n{...}\n```).
        fence_match = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n\s*```", cleaned)
        if fence_match:
            cleaned = fence_match.group(1).strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("AI response did not contain a JSON object.")
        return json.loads(cleaned[start : end + 1])

    def analyze(
        self,
        prompt: str,
        image: tuple[str, bytes] | None = None,
    ) -> CircuitDesign:
        response = self.client.complete(
            SYSTEM_PROMPT,
            "Analyze this electronics/PCB request:\n\n" + prompt,
            image=image,
        )
        try:
            payload = self._extract_json(response)
            return CircuitDesign.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            logger.warning("AI response failed schema validation: %s", exc)
            raise ValueError(
                "The model response could not be validated against the circuit schema. "
                "Try clarifying the requirements or retrying."
            ) from exc
