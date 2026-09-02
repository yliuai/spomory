"""Default LLM provider: any OpenAI-compatible chat completions API."""

from __future__ import annotations

import json
import os

from .base import LLMProvider, TripleCandidate

_EXTRACTION_SYSTEM_PROMPT = """\
你是一个信息抽取助手。从用户给出的文本中抽取事实性的 (主体, 关系, 客体) 三元组。
只抽取文本中明确表达的事实，不要编造。为每个三元组附上支撑它的原文片段。
必须只输出 JSON，格式为：
{"triples": [{"subject": "...", "predicate": "...", "object": "...", "source_span": "..."}]}
"""


class OpenAICompatibleProvider(LLMProvider):
    """Talks to any OpenAI-compatible endpoint (OpenAI, vLLM, most domestic model APIs).

    Configured via environment variables so no vendor-specific code is needed
    to switch providers:
        LLM_API_KEY   - API key (required)
        LLM_BASE_URL  - API base URL (default: OpenAI's)
        LLM_MODEL     - model name (default: gpt-4o-mini)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        from openai import OpenAI

        self.api_key = api_key or os.environ["LLM_API_KEY"]
        self.base_url = base_url or os.environ.get("LLM_BASE_URL")
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def extract_triples(self, text: str) -> list[TripleCandidate]:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        return [TripleCandidate(**t) for t in data.get("triples", [])]

    def generate(self, prompt: str, **kwargs: object) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        return response.choices[0].message.content or ""
