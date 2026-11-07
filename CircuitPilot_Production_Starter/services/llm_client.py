from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any

from openai import OpenAI

from config import Settings

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    """Raised when the OpenAI-compatible provider is not configured."""


class LLMRequestError(RuntimeError):
    """Raised when the model request fails or returns unusable content."""


class OpenAICompatibleClient:
    """Small provider adapter for Chat Completions-compatible endpoints.

    This uses the Chat Completions API, not the Responses API. The provider
    must support the selected endpoint and image input if images are supplied.
    """

    def __init__(self, settings: Settings):
        missing = [
            name
            for name, value in (
                ("AI_BASE_URL", settings.ai_base_url),
                ("AI_API_KEY", settings.ai_api_key),
                ("AI_MODEL", settings.ai_model),
            )
            if not value
        ]
        if missing:
            raise LLMConfigurationError(
                "Missing configuration: " + ", ".join(missing)
            )

        self.model = settings.ai_model
        self.client = OpenAI(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            timeout=60.0,
            max_retries=1,
        )

    @staticmethod
    def _image_data_url(image_bytes: bytes, filename: str) -> str:
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("Only PNG, JPEG and WEBP images are supported.")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        image: tuple[str, bytes] | None = None,
    ) -> str:
        if image:
            filename, image_bytes = image
            content: list[dict[str, Any]] = [
                {"type": "text", "text": user_prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": self._image_data_url(image_bytes, filename),
                        "detail": "high",
                    },
                },
            ]
            user_content: str | list[dict[str, Any]] = content
        else:
            user_content = user_prompt

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            result = response.choices[0].message.content
            if not result or not result.strip():
                raise LLMRequestError("Provider returned an empty response.")
            return result.strip()
        except LLMRequestError:
            raise
        except Exception as exc:
            logger.exception("LLM request failed")
            raise LLMRequestError(
                "The AI provider request failed. Check endpoint, model, key, "
                "provider compatibility and network access."
            ) from exc
