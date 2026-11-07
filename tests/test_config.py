from config import get_settings


def test_openai_api_key_takes_precedence_over_legacy_alias(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("AI_API_KEY", "legacy-key")

    assert get_settings().ai_api_key == "openai-key"


def test_legacy_api_key_alias_remains_supported(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AI_API_KEY", "legacy-key")

    assert get_settings().ai_api_key == "legacy-key"
