"""Epic 5.1's actual differentiator: use the image's own raw visual features
(via CLIP) to double-check a candidate triple, rather than trusting the
text-mediated caption -> extraction pipeline blindly. This is a real,
narrow capability — not a claim of native cross-modal extraction.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_CLIP_MODEL = "openai/clip-vit-base-patch32"


def triple_to_text(subject: str, predicate: str, obj: str) -> str:
    return f"{subject} {predicate} {obj}"


class ClipVerifier:
    """Scores how well a text description matches an image's actual content,
    using CLIP's shared image/text embedding space (cosine similarity).
    """

    def __init__(self, model_name: str = DEFAULT_CLIP_MODEL) -> None:
        from transformers import CLIPModel, CLIPProcessor

        self.model = CLIPModel.from_pretrained(model_name)
        self.processor = CLIPProcessor.from_pretrained(model_name)

    def score(self, image_path: str | Path, text: str) -> float:
        """Cosine similarity in [-1, 1] between the image and the text, in
        CLIP's joint embedding space — higher means the text more plausibly
        describes what's actually in the image."""
        import torch
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        inputs = self.processor(text=[text], images=image, return_tensors="pt", padding=True)
        with torch.no_grad():
            outputs = self.model(**inputs)
        image_embeds = outputs.image_embeds / outputs.image_embeds.norm(dim=-1, keepdim=True)
        text_embeds = outputs.text_embeds / outputs.text_embeds.norm(dim=-1, keepdim=True)
        return float((image_embeds @ text_embeds.T).item())

    def rank(self, image_path: str | Path, texts: list[str]) -> list[tuple[str, float]]:
        """Score multiple candidate texts against one image, best first."""
        scored = [(text, self.score(image_path, text)) for text in texts]
        return sorted(scored, key=lambda item: item[1], reverse=True)
