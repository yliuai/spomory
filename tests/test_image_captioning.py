import base64

import pytest

from memory_core.multimodal.image_captioning import _image_to_data_uri


def test_image_to_data_uri_round_trips(tmp_path):
    raw = b"\xff\xd8\xff\xe0not a real jpeg but bytes are bytes"
    path = tmp_path / "pic.jpg"
    path.write_bytes(raw)

    uri = _image_to_data_uri(path)

    assert uri.startswith("data:image/jpeg;base64,")
    encoded = uri.split(",", 1)[1]
    assert base64.b64decode(encoded) == raw


def test_openai_compatible_vision_requires_api_key(monkeypatch):
    pytest.importorskip("openai")
    from memory_core.multimodal.image_captioning import OpenAICompatibleVisionProvider

    monkeypatch.delenv("VISION_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(KeyError):
        OpenAICompatibleVisionProvider()
