"""Default LLM provider: any OpenAI-compatible chat completions API."""

from __future__ import annotations

import json
import os

from .base import LLMProvider, TripleCandidate

_EXTRACTION_SYSTEM_PROMPT = """\
你是一个信息抽取助手。从用户给出的文本中抽取事实性的 (主体, 关系, 客体) 三元组。
只抽取文本中明确表达的事实，不要编造。为每个三元组附上支撑它的原文片段。
问候、感谢、寒暄、单纯的语气/情绪表达（比如"Thanks!"、"Wow, that's
great!"、"你好"）不构成可复用的事实，不要为这类内容生成三元组——哪怕原文
带日期前缀也不例外，这类内容本身没有值得记录的信息，日期无处可折。
抽取出的 subject/predicate/object 请保持和原文一致的语言，不要翻译
（原文是中文就用中文表达，是英文就用英文表达）。
如果原文开头带有形如 [日期/时间] 的前缀，且某条三元组描述的是一个具体事件
（发生了什么、做了什么），必须把这个日期折叠进该三元组的谓语里，
这样之后即使脱离原文单独看这条三元组，时间信息也不会丢失。例如：
中文谓语写成"在2023年5月7日去了"而不是"去了"；
英文谓语写成"went to on 2023-05-07"而不是"went to"。
不确定具体日期、或者是泛泛的事实/偏好（不是某次具体事件）时，不要编造日期。
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
