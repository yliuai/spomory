"""Pluggable image-captioning interface (Epic 5.1).

Same abstraction pattern as ``LLMProvider``/``EmbeddingProvider``: the
product's honest positioning (per the business plan) is "text-mediated
extraction with multimodal verification," not "native cross-modal
extraction" — so this layer's only job is turning an image into a text
description that Epic 1.4's existing triple extraction can then consume
unchanged. The multimodal-specific value is entirely in
``clip_verification.py``, not here.
"""

from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod
from pathlib import Path

_CAPTION_SYSTEM_PROMPT = """\
你是一个图片描述助手。用一到两句话客观描述这张图片里明确可见的内容
（主体是什么、在做什么、在什么环境里），不要猜测看不到的信息。
"""


class ImageCaptioningProvider(ABC):
    @abstractmethod
    def caption(self, image_path: str | Path) -> str:
        """Return a short factual text description of the image's contents."""
        raise NotImplementedError


def _image_to_data_uri(image_path: str | Path) -> str:
    path = Path(image_path)
    suffix = path.suffix.lstrip(".").lower() or "jpeg"
    mime = "jpeg" if suffix == "jpg" else suffix
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/{mime};base64,{data}"


class OpenAICompatibleVisionProvider(ImageCaptioningProvider):
    """Any OpenAI-compatible vision-capable chat model (GPT-4o family,
    DeepSeek's vision variant, etc.), configured independently of the
    text-only ``LLM_MODEL`` since not every provider's default model
    supports images.

        VISION_API_KEY / VISION_BASE_URL / VISION_MODEL
    (each falls back to the LLM_* equivalent if unset, since it's often the
    same account/endpoint with a different model name.)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        from openai import OpenAI

        self.api_key = api_key or os.environ.get("VISION_API_KEY") or os.environ["LLM_API_KEY"]
        self.base_url = base_url or os.environ.get("VISION_BASE_URL") or os.environ.get(
            "LLM_BASE_URL"
        )
        self.model = model or os.environ.get("VISION_MODEL", "gpt-4o-mini")
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def caption(self, image_path: str | Path) -> str:
        data_uri = _image_to_data_uri(image_path)
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _CAPTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": "描述这张图片。"},
                    ],
                },
            ],
            temperature=0,
        )
        return response.choices[0].message.content or ""
