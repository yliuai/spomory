import json

import pytest

pytest.importorskip("stripe")

from cloud_api.billing import (
    TIERS,
    BillingStore,
    WebhookVerificationError,
    apply_webhook_event,
    verify_webhook,
)

WEBHOOK_SECRET = "whsec_test_secret_for_local_verification_only"


def _signed_event(event: dict) -> tuple[bytes, str]:
    from stripe._webhook import WebhookSignature

    payload_str = json.dumps(event)
    sig_header = WebhookSignature.generate_signature_header(payload_str, WEBHOOK_SECRET)
    return payload_str.encode(), sig_header


def _checkout_event(user_id: str, tier: str) -> dict:
    return {
        "id": "evt_test_1",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"user_id": user_id, "tier": tier}}},
    }


def test_verify_webhook_accepts_correctly_signed_payload():
    event = _checkout_event("u1", "monthly")
    payload, sig_header = _signed_event(event)

    verified = verify_webhook(payload, sig_header, WEBHOOK_SECRET)
    assert verified["type"] == "checkout.session.completed"


def test_verify_webhook_rejects_tampered_payload():
    event = _checkout_event("u1", "monthly")
    payload, sig_header = _signed_event(event)

    tampered = payload.replace(b"monthly", b"annual ")  # same length, different content
    with pytest.raises(WebhookVerificationError):
        verify_webhook(tampered, sig_header, WEBHOOK_SECRET)


def test_verify_webhook_rejects_wrong_secret():
    event = _checkout_event("u1", "monthly")
    payload, sig_header = _signed_event(event)

    with pytest.raises(WebhookVerificationError):
        verify_webhook(payload, sig_header, "whsec_totally_different_secret")


def test_apply_webhook_event_updates_tier_and_quota():
    store = BillingStore(":memory:")
    assert store.get_tier("u1") == "free"
    assert store.monthly_quota("u1") == TIERS["free"]["monthly_quota"]

    apply_webhook_event(store, _checkout_event("u1", "monthly"))

    assert store.get_tier("u1") == "monthly"
    assert store.monthly_quota("u1") == TIERS["monthly"]["monthly_quota"]


def test_pricing_ladder_has_no_extreme_jumps():
    # The whole point (per the business plan) is avoiding Mem0's ~13x jump
    # between adjacent *same-cadence* tiers ($19->$249/mo). Tiers here have
    # different billing cadences (weekly/monthly/annual), so compare their
    # monthly-equivalent cost rather than raw price_cents directly.
    monthly_equivalents = {
        "weekly": TIERS["weekly"]["price_cents"] * 52 / 12,
        "monthly": TIERS["monthly"]["price_cents"],
        "annual": TIERS["annual"]["price_cents"] / 12,
    }
    values = list(monthly_equivalents.values())
    assert max(values) / min(values) <= 3
