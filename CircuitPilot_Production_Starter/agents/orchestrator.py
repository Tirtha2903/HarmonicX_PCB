from __future__ import annotations

from agents.design_agent import DesignAgent
from config import Settings
from electronics.checks import run_structural_checks
from electronics.exports import export_design
from services.llm_client import OpenAICompatibleClient


class CircuitPilotOrchestrator:
    """Coordinates AI interpretation, deterministic checks and artifact export."""

    def __init__(self, settings: Settings):
        client = OpenAICompatibleClient(settings)
        self.design_agent = DesignAgent(client)
        self.settings = settings

    def run(self, prompt: str, image: tuple[str, bytes] | None = None) -> dict:
        design = self.design_agent.analyze(prompt, image=image)
        checks = run_structural_checks(design)
        artifact_dir = export_design(design, self.settings.output_dir)
        return {
            "design": design,
            "checks": checks,
            "artifact_dir": artifact_dir,
        }
