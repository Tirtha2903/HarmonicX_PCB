from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    ai_base_url: str
    ai_api_key: str
    ai_model: str
    kicad_cli_path: str
    max_image_mb: int
    max_prompt_chars: int
    output_dir: Path
    log_level: str


def get_settings() -> Settings:
    output_raw = os.getenv("OUTPUT_DIR", "projects")
    output_path = Path(output_raw)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path

    return Settings(
        ai_base_url=os.getenv(
            "AI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ).strip(),
        ai_api_key=os.getenv("AI_API_KEY", "").strip(),
        ai_model=os.getenv("AI_MODEL", "gemini-3-flash-preview").strip(),
        kicad_cli_path=os.getenv("KICAD_CLI_PATH", "").strip(),
        max_image_mb=max(1, int(os.getenv("MAX_IMAGE_MB", "8"))),
        max_prompt_chars=max(500, int(os.getenv("MAX_PROMPT_CHARS", "12000"))),
        output_dir=output_path,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
