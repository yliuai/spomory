"""Sends the magic-link login email for the OAuth flow (cloud_api/oauth_store.py).
`EmailSender` is a `Protocol` so tests can inject a fake that captures what
would have been sent instead of actually sending it -- the same pattern
`FakeLLMProvider`/`FakeEmbeddingProvider` use elsewhere in this project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class ResendEmailSender:
    """Sends via Resend (resend.com) -- a transactional-email API rather than
    raw SMTP, since a fresh cloud VPS's outbound IP has no sending
    reputation and is commonly blocklisted by mail providers."""

    def __init__(self, api_key: str, from_address: str) -> None:
        self._api_key = api_key
        self._from_address = from_address

    def send(self, to: str, subject: str, body: str) -> None:
        import resend

        resend.api_key = self._api_key
        resend.Emails.send(
            {
                "from": self._from_address,
                "to": [to],
                "subject": subject,
                "html": body,
            }
        )


@dataclass
class FakeEmailSender:
    sent: list[tuple[str, str, str]] = field(default_factory=list)

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))
