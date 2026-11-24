"""The transport: the key, the base URL, timeouts, retries and unwrapping the envelope.

Resource modules (agents, calls, ...) never touch httpx directly; they describe a request
and let this decide how it is made.
"""

from __future__ import annotations

import builtins
import json
import random
import time
from typing import Any, Dict, Mapping, Optional

import httpx

from ._version import __version__
from .errors import (
    ConnectionError,
    InvalidResponseError,
    MovoiceError,
    RateLimitError,
    error_from_response,
)

DEFAULT_BASE_URL = "https://app.movoice.ai"
API_ROOT = "/api/v1"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2
USER_AGENT = f"movoice-python/{__version__}"

_MISSING = object()


def _sleep(seconds: float) -> None:
    """Indirection so tests can skip the wait between retries."""
    time.sleep(seconds)


class HttpClient:
    """Makes one logical request, with retries where repeating it is safe.

    Also the escape hatch for endpoints this version does not wrap yet::

        data = client.http.request("GET", "/some/new/endpoint")

    Paths are relative to ``/api/v1``.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        key = (api_key or "").strip()
        if not key:
            raise MovoiceError(
                "No API key. Create one at https://app.movoice.ai/developer and pass it as "
                "Movoice(api_key=...) or set MOVOICE_API_KEY.",
                code="UNAUTHORIZED",
            )
        if key.startswith("mv_pk_"):
            raise MovoiceError(
                "That is a publishable key. Publishable keys (mv_pk_) only work with the chat widget "
                "in a browser and cannot call the API. Use a secret key (mv_live_ or mv_test_) from "
                "https://app.movoice.ai/developer, and keep it on your server.",
                code="FORBIDDEN",
            )
        self._api_key = key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self._default_headers = dict(default_headers or {})
        self._owns_client = http_client is None
        self._client = http_client if http_client is not None else httpx.Client()

    def close(self) -> None:
        """Close the connection pool, when this client created it."""
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        body: Any = _MISSING,
        idempotency_key: Optional[str] = None,
        accepts_idempotency_key: bool = False,
        timeout: Optional[float] = None,
    ) -> Any:
        """Make a request and return the unwrapped ``data`` payload."""
        return self._send(method, path, query, body, idempotency_key, accepts_idempotency_key, timeout, True)["data"]

    def request_raw(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Return the body exactly as it arrived, with no envelope (only ``/memory/recall`` needs this)."""
        return self._send(method, path, query, _MISSING, None, False, timeout, False)["data"]

    def request_page(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Make a request to a list endpoint and keep the pagination block."""
        envelope = self._send(method, path, query, _MISSING, None, False, timeout, True)
        data = envelope.get("data")
        if not isinstance(data, list):
            raise InvalidResponseError(
                f"Expected a list from {path} but got {type(data).__name__}.",
                code="INVALID_RESPONSE",
                body=envelope,
            )
        meta = envelope.get("meta")
        pagination = meta.get("pagination") if isinstance(meta, dict) else None
        return {"data": data, "pagination": pagination}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _send(
        self,
        method: str,
        path: str,
        query: Optional[Mapping[str, Any]],
        body: Any,
        idempotency_key: Optional[str],
        accepts_idempotency_key: bool,
        timeout: Optional[float],
        expect_envelope: bool,
    ) -> Dict[str, Any]:
        method = method.upper()
        _check_idempotency_key(method, path, idempotency_key, accepts_idempotency_key)
        url = self.base_url + API_ROOT + path
        params = _clean_query(query)
        headers = self._headers(body is not _MISSING, idempotency_key if accepts_idempotency_key else None)
        content = None if body is _MISSING else json.dumps(body, separators=(",", ":")).encode("utf-8")
        # A GET can always be repeated. A write only with an Idempotency-Key the route honours:
        # the server hands back the first answer for a repeat instead of acting again.
        retryable_request = method == "GET" or (accepts_idempotency_key and idempotency_key is not None)

        last_error: Optional[MovoiceError] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    content=content,
                    timeout=self.timeout if timeout is None else timeout,
                )
            except httpx.TimeoutException as exc:
                error: MovoiceError = ConnectionError(
                    "The request timed out. It may still have been processed: check before retrying "
                    "anything that spends money.",
                    code="TIMEOUT",
                )
                error.__cause__ = exc
            except httpx.TransportError as exc:
                error = ConnectionError(f"Could not reach the Movoice API: {exc}", code="CONNECTION_ERROR")
                error.__cause__ = exc
            else:
                if 200 <= response.status_code < 300:
                    return self._parse_success(response, method, path, expect_envelope)
                error = error_from_response(response.status_code, _read_json_safely(response), response.headers)

            if not self._should_retry(error, retryable_request, attempt):
                raise error
            last_error = error
            _sleep(_backoff_seconds(attempt, last_error))

        # Unreachable: the last attempt always raises above.
        raise last_error or ConnectionError("Request failed.", code="CONNECTION_ERROR")  # pragma: no cover

    def _headers(self, has_body: bool, idempotency_key: Optional[str]) -> Dict[str, str]:
        reserved = {"accept", "authorization", "user-agent", "content-type", "idempotency-key"}
        headers = {k: v for k, v in self._default_headers.items() if k.lower() not in reserved}
        headers["Accept"] = "application/json"
        headers["Authorization"] = f"Bearer {self._api_key}"
        headers["User-Agent"] = USER_AGENT
        if has_body:
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _parse_success(
        self, response: httpx.Response, method: str, path: str, expect_envelope: bool
    ) -> Dict[str, Any]:
        body = _read_json_safely(response)
        # 204 No Content: DELETE answers this way and there is nothing to unwrap.
        if response.status_code == 204 or body is None:
            return {"data": None}
        if not expect_envelope:
            return {"data": body}
        if not isinstance(body, dict) or "data" not in body:
            raise InvalidResponseError(
                f"{method} {path} returned {response.status_code} but not the expected response envelope.",
                code="INVALID_RESPONSE",
                status=response.status_code,
                body=body,
            )
        return body

    def _should_retry(self, error: MovoiceError, retryable_request: bool, attempt: int) -> bool:
        if attempt >= self.max_retries:
            return False
        # Refused before doing any work, so repeating it cannot double-charge.
        if error.code == "RATE_LIMITED":
            return True
        if not retryable_request:
            return False
        return error.is_retryable


def _check_idempotency_key(method: str, path: str, key: Optional[str], accepted: bool) -> None:
    """A key on a route that ignores it, or a key the server would refuse, fails before sending."""
    if key is None:
        return
    if not accepted:
        raise MovoiceError(
            f"{method} {path} does not accept an Idempotency-Key, so the key would not protect "
            "anything. Remove it.",
            code="BAD_REQUEST",
        )
    if not isinstance(key, str) or not 8 <= len(key) <= 255:
        raise MovoiceError("An Idempotency-Key must be 8 to 255 characters.", code="BAD_REQUEST")


def _clean_query(query: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in (query or {}).items():
        if value is None or value == "":
            continue
        if isinstance(value, builtins.bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = str(value)
    return out


def _read_json_safely(response: httpx.Response) -> Any:
    try:
        text = response.text
    except Exception:  # pragma: no cover - undecodable body
        return None
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        # An HTML error page from a proxy, most likely. Keep it for the error body.
        return {"error": {"message": text[:500]}}


def _backoff_seconds(attempt: int, error: Optional[MovoiceError]) -> float:
    """Exponential backoff with jitter, or the server's own Retry-After when it sent one."""
    if isinstance(error, RateLimitError) and error.retry_after and error.retry_after > 0:
        return float(min(error.retry_after, 60))
    return min(0.5 * (2**attempt), 8.0) + random.random() * 0.25
