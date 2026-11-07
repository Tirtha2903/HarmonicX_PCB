from __future__ import annotations

from collections.abc import Sequence

from agents.design_agent import DesignAgent
from config import Settings
from electronics.checks import run_structural_checks
from electronics.exports import export_design, export_review_artifacts
from electronics.red_team.engine import RedTeamEngine
from services.llm_client import OpenAICompatibleClient


class CircuitPilotOrchestrator:
    """Coordinates AI interpretation, deterministic checks, Red-Team review and artifact export."""

    def __init__(self, settings: Settings):
        client = OpenAICompatibleClient(settings)
        self.design_agent = DesignAgent(client)
        self.settings = settings

    def run(
        self,
        prompt: str,
        images: Sequence[tuple[str, bytes]] | None = None,
    ) -> dict:
        design = self.design_agent.analyze(prompt, images=images)
        checks = run_structural_checks(design)
        red_team = RedTeamEngine(
            self.settings,
            enable_ai_review=self.settings.enable_ai_red_team,
        ).review(design)
        artifact_dir = export_design(design, self.settings.output_dir)
        export_review_artifacts(design, red_team, artifact_dir)
        return {
            "design": design,
            "checks": checks,
            "red_team": red_team,
            "artifact_dir": artifact_dir,
            "design_fingerprint": red_team.design_fingerprint,
        }
