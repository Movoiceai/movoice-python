"""Webhooks: prove an event came from Movoice before you act on it.

::

    import movoice

    event = movoice.webhooks.verify(raw_body, request.headers, os.environ["MOVOICE_WEBHOOK_SECRET"])

How Movoice signs every delivery::

    X-Movoice-Timestamp: <unix seconds>
    X-Movoice-Signature: sha256=<hex of HMAC-SHA256(secret, f"{timestamp}.{raw_body}")>

The key is the endpoint's whole signing secret, ``whsec_`` included, exactly as the Developer
page shows it. Verification needs the body EXACTLY as it arrived: parse it after verifying,
never before, because re-serialised JSON is not the same bytes.

Needs no API key, so a webhook receiver can verify without one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any, Optional, Union

from .errors import WebhookVerificationError
from .types import CallWebhookEvent

__all__ = ["verify", "WebhookVerificationError", "DEFAULT_TOLERANCE_SECONDS"]

#: How far the timestamp may be from now, in seconds, before a delivery is refused as a replay.
DEFAULT_TOLERANCE_SECONDS = 300

_TIMESTAMP = re.compile(r"[0-9]{1,12}")
_SIGNATURE = re.compile(r"sha256=([0-9a-fA-F]{64})")

RawBody = Union[str, bytes, bytearray, memoryview]


def verify(
    raw_body: RawBody,
    headers: Any,
    secret: str,
    tolerance: int = DEFAULT_TOLERANCE_SECONDS,
    *,
    now: Optional[float] = None,
) -> CallWebhookEvent:
    """Check the signature and the timestamp of a delivery, then return the parsed event.

    :param raw_body: the request body exactly as it arrived (``str`` or bytes), not parsed JSON.
        Flask: ``request.get_data()``; FastAPI/Starlette: ``await request.body()``; Django:
        ``request.body``.
    :param headers: the request headers: a dict, or any mapping such as Flask's
        ``request.headers`` or Starlette's ``request.headers``. Names are matched case-insensitively.
    :param secret: the endpoint's signing secret, ``whsec_`` included.
    :param tolerance: seconds either side of now the timestamp may be. Default 300 (5 minutes).
    :param now: "now" in epoch seconds, for tests. Defaults to ``time.time()``.
    :raises WebhookVerificationError: a header is missing, the timestamp is outside
        ``tolerance``, or the signature does not match this secret and body.
    """
    if not isinstance(secret, str) or not secret.strip():
        raise WebhookVerificationError(
            "No signing secret. Use the endpoint's secret from the Developer page (it starts with whsec_)."
        )
    if isinstance(raw_body, str):
        body_bytes = raw_body.encode("utf-8")
    elif isinstance(raw_body, (bytes, bytearray, memoryview)):
        body_bytes = bytes(raw_body)
    else:
        raise WebhookVerificationError(
            "The body must be the raw request body (a str or bytes), not parsed JSON."
        )

    signature = _header(headers, "x-movoice-signature")
    timestamp = _header(headers, "x-movoice-timestamp")
    if not signature:
        raise WebhookVerificationError("The X-Movoice-Signature header is missing.")
    if not timestamp:
        raise WebhookVerificationError("The X-Movoice-Timestamp header is missing.")

    if not _TIMESTAMP.fullmatch(timestamp):
        raise WebhookVerificationError("The X-Movoice-Timestamp header is not a time in seconds.")
    now_seconds = int(time.time() if now is None else now)
    if abs(now_seconds - int(timestamp)) > tolerance:
        raise WebhookVerificationError(
            f"The delivery's timestamp is more than {tolerance} seconds from now, so it may be a "
            "replay. Check this server's clock if every delivery fails this way."
        )

    match = _SIGNATURE.fullmatch(signature.strip())
    if not match:
        raise WebhookVerificationError('The X-Movoice-Signature header is not "sha256=<hex>".')

    expected = hmac.new(
        secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body_bytes, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, match.group(1).lower()):
        raise WebhookVerificationError(
            "The signature does not match. Check you used this endpoint's own secret and the raw, "
            "unparsed body."
        )

    try:
        return json.loads(body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise WebhookVerificationError("The signature matched but the body is not JSON.") from None


def _header(headers: Any, name: str) -> Optional[str]:
    """Read one header case-insensitively from a dict or any mapping-like headers object."""
    if headers is None:
        return None
    items = getattr(headers, "items", None)
    if callable(items):
        for key, value in items():
            if isinstance(key, bytes):
                key = key.decode("latin-1")
            if str(key).lower() != name:
                continue
            if isinstance(value, (list, tuple)):
                value = value[0] if value else None
            if isinstance(value, bytes):
                value = value.decode("latin-1")
            return value if value is None else str(value)
        return None
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name)
        return None if value is None else str(value)
    return None
