"""Epic 8.3: subscription tiers + Stripe webhook handling.

No real Stripe account is configured in this environment, so nothing here
has been exercised against Stripe's live/test API (creating an actual
checkout session, etc.) — but webhook signature verification itself needs
no network call (it's HMAC over the payload), so that part is really
tested, using stripe's own `generate_signature_header` test helper rather
than a hand-rolled fake.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Smooth, low-threshold ladder pricing (per the business plan's explicit
# goal of avoiding Mem0's 19->249 USD, 13x jump between tiers — criticized
# in industry reviews as a real adoption blocker).
TIERS: dict[str, dict[str, int]] = {
    "free": {"monthly_quota": 100, "price_cents": 0},
    "weekly": {"monthly_quota": 1_000, "price_cents": 500},  # ~$5/week
    "monthly": {"monthly_quota": 5_000, "price_cents": 1_500},  # $15/month
    "annual": {"monthly_quota": 20_000, "price_cents": 12_000},  # $120/year ($10/mo equiv.)
}


class WebhookVerificationError(Exception):
    pass


def verify_webhook(payload: bytes, sig_header: str, webhook_secret: str) -> dict:
    """Verify and parse a Stripe webhook payload. Raises WebhookVerificationError
    on a bad/missing signature (a forged or replayed request)."""
    import stripe

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (stripe.error.SignatureVerificationError, ValueError) as exc:
        raise WebhookVerificationError(str(exc)) from exc
    return event


_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id TEXT PRIMARY KEY,
    tier TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class BillingStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def set_tier(self, user_id: str, tier: str) -> None:
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}; must be one of {sorted(TIERS)}")
        self._conn.execute(
            "INSERT INTO subscriptions (user_id, tier) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET tier = excluded.tier, updated_at = datetime('now')",
            (user_id, tier),
        )
        self._conn.commit()

    def get_tier(self, user_id: str) -> str:
        row = self._conn.execute(
            "SELECT tier FROM subscriptions WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row[0] if row else "free"

    def monthly_quota(self, user_id: str) -> int:
        return TIERS[self.get_tier(user_id)]["monthly_quota"]


def apply_webhook_event(billing_store: BillingStore, event: dict) -> None:
    """Update a user's subscription tier in response to a verified Stripe event.

    Expects `event["data"]["object"]["metadata"]` to carry `user_id` and
    `tier` — set when creating the Checkout Session/Subscription, matching
    how Stripe recommends passing your own identifiers through.
    """
    event_type = event.get("type", "")
    if event_type not in {"checkout.session.completed", "customer.subscription.updated"}:
        return

    obj = event["data"]["object"]
    metadata = obj.get("metadata", {})
    user_id = metadata.get("user_id")
    tier = metadata.get("tier")
    if user_id and tier:
        billing_store.set_tier(user_id, tier)
