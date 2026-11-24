"""One error type, whatever the API actually sent.

The API answers every failure in one shape::

    {"success": false, "error": {"code": "NOT_FOUND", "message": "..."}}

It did not always: older deployments and proxies can still send an auth variant with no
``success`` field and lower-case codes, or a bare string ``error`` that is sometimes a reason
code and sometimes a sentence. This module reads all of them and always raises the same class
hierarchy, with ``code`` upper-cased so ``forbidden`` and ``FORBIDDEN`` both arrive as
``"FORBIDDEN"``. The raw values stay on ``raw_code`` and ``body``.

Two class names match Python built-ins on purpose, to match the other Movoice clients:
``movoice.PermissionError`` and ``movoice.ConnectionError``. Import them through the package
(``movoice.PermissionError``) or catch ``movoice.MovoiceError`` to catch everything.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

__all__ = [
    "MovoiceError",
    "AuthenticationError",
    "PermissionError",
    "InvalidRequestError",
    "NotFoundError",
    "ConflictError",
    "InsufficientBalanceError",
    "RateLimitError",
    "ApiError",
    "ConnectionError",
    "InvalidResponseError",
    "WebhookVerificationError",
    "error_from_response",
]


class MovoiceError(Exception):
    """Base class for everything this library raises. Catch this to catch all of it."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: Optional[int] = None,
        raw_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        #: Normalised, upper-case code, e.g. ``"NOT_FOUND"``.
        self.code = code
        #: HTTP status, or ``None`` when the request never got a response.
        self.status = status
        #: The code exactly as the API sent it, before upper-casing.
        self.raw_code = raw_code
        self.details = details
        #: The parsed response body, for debugging.
        self.body = body

    @property
    def is_retryable(self) -> bool:
        """True when repeating the identical request could plausibly succeed.

        This is about the error, not the request: the client never retries a POST that may
        already have placed a call or sent a message, even when this is True.
        """
        if self.code in ("RATE_LIMITED", "CONNECTION_ERROR", "TIMEOUT"):
            return True
        return self.status is not None and self.status >= 500

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, status={self.status!r}, message={self.message!r})"


class AuthenticationError(MovoiceError):
    """401: the key is missing, malformed, expired or unknown."""


class PermissionError(MovoiceError):  # noqa: A001 - named like the other Movoice clients
    """403: the key is real but is not allowed to do this. Usually a missing scope."""

    @property
    def required_scopes(self) -> Optional[List[str]]:
        """The scopes the endpoint required, when the API said."""
        req = (self.details or {}).get("required")
        return list(req) if isinstance(req, list) else None


class InvalidRequestError(MovoiceError):
    """400 / 422: the request was understood and rejected."""

    @property
    def field_errors(self) -> Optional[Dict[str, List[str]]]:
        """Per-field validation messages, e.g. ``{"phoneNumber": ["Invalid phone number"]}``."""
        errs = (self.details or {}).get("errors")
        return errs if isinstance(errs, dict) else None


class NotFoundError(MovoiceError):
    """404: no such thing on this account. Also returned for another account's ids."""


class ConflictError(MovoiceError):
    """409: the request conflicts with the current state."""


class InsufficientBalanceError(MovoiceError):
    """402: plan allowance and wallet are both empty. Top up, then retry."""


class RateLimitError(MovoiceError):
    """429: too many requests for this key."""

    def __init__(self, message: str, *, retry_after: Optional[int] = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        #: Seconds to wait, from the ``Retry-After`` header, when the API sent one.
        self.retry_after = retry_after


class ApiError(MovoiceError):
    """5xx: the failure was on Movoice's side, not in your request."""


class ConnectionError(MovoiceError):  # noqa: A001 - named like the other Movoice clients
    """The request never completed: DNS, TLS, socket or timeout.

    A timeout can still have reached the server, so check before retrying anything that
    spends money.
    """


class InvalidResponseError(MovoiceError):
    """A response came back, but not the JSON envelope the API is supposed to send."""


class WebhookVerificationError(MovoiceError):
    """A webhook delivery could not be proven to come from Movoice. Answer it with a 400."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="WEBHOOK_SIGNATURE_INVALID")


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_STATUS_FALLBACK = {
    400: "The request was rejected.",
    401: "The API key is missing, expired, or not recognised.",
    402: "Your plan allowance and wallet balance are both exhausted.",
    403: "This API key is not allowed to perform that action.",
    404: "Not found on this account.",
    409: "That conflicts with the current state.",
    422: "The request could not be processed.",
    429: "Rate limit exceeded for this API key.",
    500: "Something failed on the Movoice side.",
    503: "The service is temporarily unavailable.",
}


def _read_error_body(body: Any) -> Dict[str, Any]:
    """Pull ``raw_code``, ``message`` and ``details`` out of whichever envelope this is."""
    if not isinstance(body, dict):
        return {}
    err = body.get("error")
    if not err:
        return {}
    # Bare-string shape: ``{"error": "DAILY_SPEND_CAP", "message": "..."}`` carries the reason
    # code in ``error``; with no sibling ``message`` the string is the message itself.
    if isinstance(err, str):
        sibling = body.get("message")
        if isinstance(sibling, str):
            return {"raw_code": err, "message": sibling}
        return {"message": err}
    if not isinstance(err, dict):
        return {}
    code = err.get("code")
    message = err.get("message")
    details = err.get("details")
    return {
        "raw_code": code if isinstance(code, str) else None,
        "message": message if isinstance(message, str) else None,
        "details": details if isinstance(details, dict) else None,
    }


def _status_to_code(status: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        402: "PAYMENT_REQUIRED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "RATE_LIMITED",
        503: "SERVICE_UNAVAILABLE",
    }.get(status, "INTERNAL_ERROR" if status >= 500 else "BAD_REQUEST")


def _parse_retry_after(headers: Optional[Mapping[str, str]]) -> Optional[int]:
    if headers is None:
        return None
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def error_from_response(
    status: int, body: Any, headers: Optional[Mapping[str, str]] = None
) -> MovoiceError:
    """Build the right error class from an HTTP response: status first, code second."""
    parsed = _read_error_body(body)
    raw_code = parsed.get("raw_code")
    code = raw_code.upper() if raw_code else _status_to_code(status)
    message = parsed.get("message") or _STATUS_FALLBACK.get(status) or f"Request failed with status {status}."
    kwargs: Dict[str, Any] = {
        "code": code,
        "status": status,
        "raw_code": raw_code,
        "details": parsed.get("details"),
        "body": body,
    }
    if status == 401:
        return AuthenticationError(message, **kwargs)
    if status == 402:
        return InsufficientBalanceError(message, **kwargs)
    if status == 403:
        return PermissionError(message, **kwargs)
    if status == 404:
        return NotFoundError(message, **kwargs)
    if status == 409:
        return ConflictError(message, **kwargs)
    if status in (400, 422):
        return InvalidRequestError(message, **kwargs)
    if status == 429:
        return RateLimitError(message, retry_after=_parse_retry_after(headers), **kwargs)
    if status >= 500:
        return ApiError(message, **kwargs)
    return MovoiceError(message, **kwargs)
