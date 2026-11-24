"""Messaging: SMS and WhatsApp. These spend your balance."""

from __future__ import annotations

from typing import Optional, cast

from ..errors import MovoiceError
from ..types import MessageResult
from ._base import Resource


class Messages(Resource):
    def send(self, *, to: str, body: str, timeout: Optional[float] = None) -> MessageResult:
        """Send an SMS. Capped at 500 messages per key per 24 hours.

        Never retried on a 5xx or timeout (it may already have been sent). A recipient who
        replied STOP raises ``InvalidRequestError`` with the reason.
        """
        result = self._http.request("POST", "/messages", body={"to": to, "body": body}, timeout=timeout)
        return _assert_actually_sent(result, "SMS")

    def send_whatsapp(self, *, to: str, body: str, timeout: Optional[float] = None) -> MessageResult:
        """Send a WhatsApp message. Capped at 500 messages per key per 24 hours.

        Meta's own rules (approved templates, the 24-hour window) are enforced by Meta at
        delivery, not here.
        """
        result = self._http.request("POST", "/whatsapp", body={"to": to, "body": body}, timeout=timeout)
        return _assert_actually_sent(result, "WhatsApp message")


def _assert_actually_sent(result: object, what: str) -> MessageResult:
    """``status`` is always "sent"; no carrier id means nothing went out, so raise."""
    if not isinstance(result, dict) or not result.get("providerMessageId"):
        raise MovoiceError(
            f"The {what} was accepted but no carrier id came back, which means it was not sent. "
            "Check the recipient's opt-out status and your sender configuration.",
            code="NOT_SENT",
            body=result,
        )
    return cast(MessageResult, result)
