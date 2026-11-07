from types import SimpleNamespace
from unittest.mock import patch

from config import Settings
from services.llm_client import OpenAICompatibleClient


def _settings(tmp_path):
    return Settings(
        ai_base_url="https://api.openai.com/v1",
        ai_api_key="test-key",
        ai_model="gpt-4o-mini",
        kicad_cli_path="",
        max_image_mb=8,
        max_prompt_chars=12000,
        output_dir=tmp_path,
        log_level="INFO",
        db_path=tmp_path / "dna.db",
    )


def test_complete_includes_written_prompt_and_multiple_images(tmp_path):
    client = OpenAICompatibleClient(_settings(tmp_path))
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="analysis"))]
    )

    with patch.object(
        client.client.chat.completions,
        "create",
        return_value=response,
    ) as create:
        result = client.complete(
            "system",
            "Review this circuit",
            images=[
                ("top.png", b"first image"),
                ("detail.jpg", b"second image"),
            ],
        )

    assert result == "analysis"
    content = create.call_args.kwargs["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "Review this circuit"}
    assert len(content) == 3
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
