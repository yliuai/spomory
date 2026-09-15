from memory_core.llm.redact import redact_secrets


def test_redacts_openai_style_key():
    text = "the key is sk-" + "a" * 40
    assert "sk-" + "a" * 40 not in redact_secrets(text)
    assert "REDACTED" in redact_secrets(text)


def test_redacts_anthropic_style_key():
    text = "ANTHROPIC_API_KEY=sk-ant-api03-" + "b" * 40
    result = redact_secrets(text)
    assert "sk-ant-api03-" + "b" * 40 not in result
    assert "REDACTED_ANTHROPIC_API_KEY" in result


def test_redacts_github_token():
    text = "token: ghp_" + "c" * 36
    assert "ghp_" + "c" * 36 not in redact_secrets(text)


def test_redacts_google_api_key():
    text = "AIza" + "d" * 35
    assert text not in redact_secrets(text)


def test_redacts_aws_access_key_id():
    text = "AKIA" + "E" * 16
    assert text not in redact_secrets(text)


def test_redacts_jwt():
    text = "Authorization header: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    result = redact_secrets(text)
    assert "eyJhbGciOiJIUzI1NiJ9" not in result
    assert "REDACTED_JWT" in result


def test_redacts_bearer_token():
    text = "curl -H 'Authorization: Bearer " + "z" * 30 + "'"
    result = redact_secrets(text)
    assert "z" * 30 not in result


def test_preserves_surrounding_text():
    """The whole point is to redact only the token, not swallow the fact
    it's embedded in -- a downstream extraction call should still see
    "the key is used in auth.ts", just not the key itself."""
    secret = "sk-ant-api03-" + "x" * 40
    text = f"本项目密钥用的是 jose 中间件，密钥是 {secret}，写在 src/middleware/auth.ts 里"

    result = redact_secrets(text)

    assert secret not in result
    assert "src/middleware/auth.ts" in result
    assert "jose 中间件" in result


def test_does_not_touch_ordinary_text():
    """Conservative-over-clever: a sentence with no recognizable secret
    format must come back byte-for-byte unchanged, not have some unrelated
    substring mangled by an overeager pattern."""
    text = "张三任职于某公司，工号 A1234567，commit hash 是 abc1234。"
    assert redact_secrets(text) == text
