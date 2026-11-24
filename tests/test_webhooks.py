"""webhooks.verify against signatures made the way the Movoice server makes them.

The server (movoice-ai/lib/call-webhook-dispatcher.ts ``signWith``) signs HMAC-SHA256 over
``f"{timestamp}.{raw_body}"`` with the endpoint's whole whsec_ secret and sends
``X-Movoice-Signature: sha256=<hex>`` beside ``X-Movoice-Timestamp``. The signer below is
written here from that description, not taken from the package, so a wrong package cannot
sign its own way to a pass.

The same 14-case table as the TypeScript package (movoice-sdk/test/webhooks.test.mjs).
Every time is computed from now: nothing here ages.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import httpx
import pytest

import movoice
from movoice import MovoiceError, WebhookVerificationError, webhooks

SECRET = "whsec_" + "k" * 40
OTHER_SECRET = "whsec_" + "x" * 40
BODY = json.dumps(
    {
        "event_id": "evt_1",
        "event": "call.completed",
        "id": "j57abc",
        "context_data": {"leadId": "L-889", "name": "Rahul"},
        "agent": {"id": "k17agent"},
        "call_id": "engine-call-1",
        "agent_id": "engine-agent-1",
        "agent_name": "Front desk",
        "caller_phone": "+14155550123",
        "direction": "outbound",
        "duration_seconds": 42,
        "summary": "Booked a visit for Thursday.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
)


def sign(secret: str, body: str, ts: int) -> str:
    """Exactly the server's signWith."""
    return "sha256=" + hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()


def now_seconds() -> int:
    return int(time.time())


def plain_headers(sig, ts):
    """Lower-case plain dict, the way a WSGI/ASGI framework's raw headers often arrive."""
    h = {"content-type": "application/json"}
    if sig is not None:
        h["x-movoice-signature"] = sig
    if ts is not None:
        h["x-movoice-timestamp"] = str(ts)
    return h


def mapping_headers(sig, ts):
    """A case-insensitive headers object (httpx.Headers, like Starlette's request.headers)."""
    return httpx.Headers({"Content-Type": "application/json", "X-Movoice-Signature": sig, "X-Movoice-Timestamp": str(ts)})


# One table: every case the founder named (valid, wrong secret, old timestamp, tampered body,
# header missing), plus the shapes a real receiver hands in (headers object vs dict, str vs bytes).
CASES = [
    (
        "valid: str body, case-insensitive headers object",
        lambda ts: (BODY, mapping_headers(sign(SECRET, BODY, ts), ts), SECRET),
        None,
    ),
    (
        "valid: bytes body, plain dict with mixed-case names",
        lambda ts: (
            BODY.encode("utf-8"),
            {"X-Movoice-Signature": sign(SECRET, BODY, ts), "X-Movoice-Timestamp": str(ts)},
            SECRET,
        ),
        None,
    ),
    (
        "valid: 4 minutes old, inside the 5-minute window",
        lambda ts: (BODY, plain_headers(sign(SECRET, BODY, ts - 240), ts - 240), SECRET),
        None,
    ),
    (
        "wrong secret",
        lambda ts: (BODY, plain_headers(sign(OTHER_SECRET, BODY, ts), ts), SECRET),
        "does not match",
    ),
    (
        "the secret without its whsec_ prefix is a different key",
        lambda ts: (BODY, plain_headers(sign(SECRET, BODY, ts), ts), SECRET[len("whsec_"):]),
        "does not match",
    ),
    (
        "old timestamp (6 minutes), correctly signed",
        lambda ts: (BODY, plain_headers(sign(SECRET, BODY, ts - 360), ts - 360), SECRET),
        "more than 300 seconds",
    ),
    (
        "timestamp 6 minutes in the future, correctly signed",
        lambda ts: (BODY, plain_headers(sign(SECRET, BODY, ts + 360), ts + 360), SECRET),
        "more than 300 seconds",
    ),
    (
        "tampered body (one field changed after signing)",
        lambda ts: (BODY.replace('"L-889"', '"L-890"'), plain_headers(sign(SECRET, BODY, ts), ts), SECRET),
        "does not match",
    ),
    (
        "timestamp swapped for another (signature replayed with a fresh timestamp)",
        lambda ts: (BODY, plain_headers(sign(SECRET, BODY, ts - 120), ts), SECRET),
        "does not match",
    ),
    (
        "signature header missing",
        lambda ts: (BODY, plain_headers(None, ts), SECRET),
        "X-Movoice-Signature header is missing",
    ),
    (
        "timestamp header missing",
        lambda ts: (BODY, plain_headers(sign(SECRET, BODY, ts), None), SECRET),
        "X-Movoice-Timestamp header is missing",
    ),
    (
        "signature without the sha256= prefix",
        lambda ts: (BODY, plain_headers(sign(SECRET, BODY, ts)[len("sha256="):], ts), SECRET),
        'not "sha256=<hex>"',
    ),
    (
        "empty secret",
        lambda ts: (BODY, plain_headers(sign(SECRET, BODY, ts), ts), ""),
        "No signing secret",
    ),
    (
        "parsed JSON passed instead of the raw body",
        lambda ts: (json.loads(BODY), plain_headers(sign(SECRET, BODY, ts), ts), SECRET),
        "raw request body",
    ),
]


@pytest.mark.parametrize("make,error", [(m, e) for _, m, e in CASES], ids=[n for n, _, _ in CASES])
def test_verify_table(make, error):
    body, headers, secret = make(now_seconds())
    if error is None:
        event = webhooks.verify(body, headers, secret)
        assert event["event"] == "call.completed"
        assert event["id"] == "j57abc"
        assert event["context_data"] == {"leadId": "L-889", "name": "Rahul"}
        assert event["agent"]["id"] == "k17agent"
    else:
        with pytest.raises(WebhookVerificationError) as info:
            webhooks.verify(body, headers, secret)
        err = info.value
        assert isinstance(err, MovoiceError)
        assert err.code == "WEBHOOK_SIGNATURE_INVALID"
        assert error in str(err)


def test_the_table_has_the_same_14_cases_as_the_typescript_package():
    assert len(CASES) == 14


def test_the_tolerance_can_be_narrowed():
    ts = now_seconds() - 90
    with pytest.raises(WebhookVerificationError, match="more than 60 seconds"):
        webhooks.verify(BODY, plain_headers(sign(SECRET, BODY, ts), ts), SECRET, tolerance=60)


def test_a_frozen_now_decides_the_window_not_the_machine_clock():
    ts = now_seconds() - 3600
    event = webhooks.verify(BODY, plain_headers(sign(SECRET, BODY, ts), ts), SECRET, now=ts + 1)
    assert event["event_id"] == "evt_1"


def test_client_webhooks_is_the_same_verifier_and_makes_no_request():
    requests = []
    transport = httpx.MockTransport(lambda r: requests.append(r) or httpx.Response(200, json={}))
    client = movoice.Movoice("mv_live_" + "a" * 32, http_client=httpx.Client(transport=transport))
    ts = now_seconds()
    event = client.webhooks.verify(BODY, plain_headers(sign(SECRET, BODY, ts), ts), SECRET)
    assert event["id"] == "j57abc"
    assert client.webhooks.verify is movoice.webhooks.verify
    assert requests == []
