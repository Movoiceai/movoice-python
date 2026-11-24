"""The Movoice client.

::

    from movoice import Movoice

    client = Movoice()  # reads MOVOICE_API_KEY
    call = client.calls.create(agent_id=agent_id, phone_number="+14155550123")

Server-side only: a secret key can place calls and spend your balance.
"""

from __future__ import annotations

import os
from types import ModuleType, TracebackType
from typing import Mapping, Optional, Type

import httpx

from . import webhooks as _webhooks
from ._http import DEFAULT_BASE_URL, DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT, HttpClient
from .resources import (
    AccountResource,
    Agents,
    Appointments,
    AvailabilityResource,
    Calls,
    Contacts,
    Memory,
    Messages,
    Numbers,
)


class Movoice:
    """A client for the Movoice AI API.

    :param api_key: your secret key, ``mv_live_...`` or ``mv_test_...``. Defaults to the
        ``MOVOICE_API_KEY`` environment variable. Publishable keys (``mv_pk_``) are refused.
    :param base_url: defaults to ``https://app.movoice.ai``.
    :param timeout: seconds before a single attempt is abandoned. Default 30.
    :param max_retries: retries for requests that are safe to repeat. Default 2. A call or a
        message is never retried unless you gave it an idempotency key.
    :param default_headers: extra headers on every request. Cannot override ``Authorization``.
    :param http_client: your own ``httpx.Client`` (proxies, custom transport, tests). The
        client does not close one you pass in.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        if api_key is None:
            api_key = os.environ.get("MOVOICE_API_KEY")
        #: Escape hatch for endpoints this version does not wrap yet: ``client.http.request("GET", "/path")``.
        self.http = HttpClient(
            api_key or "",
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=default_headers,
            http_client=http_client,
        )
        #: The voice agents that answer and place calls.
        self.agents = Agents(self.http)
        #: Place calls, hang them up, and read their history and transcripts.
        self.calls = Calls(self.http)
        #: Your address book.
        self.contacts = Contacts(self.http)
        #: Bookings on your agents' calendars.
        self.appointments = Appointments(self.http)
        #: Free times on an agent's calendar.
        self.availability = AvailabilityResource(self.http)
        #: The phone numbers on your account. Read only.
        self.numbers = Numbers(self.http)
        #: SMS and WhatsApp. These spend your balance.
        self.messages = Messages(self.http)
        #: What an agent remembers about a caller.
        self.memory = Memory(self.http)
        #: The account behind the key, including your Movoice Account ID.
        self.account = AccountResource(self.http)
        #: Verify a webhook delivery. Also usable without a client: ``movoice.webhooks.verify(...)``.
        self.webhooks: ModuleType = _webhooks

    def close(self) -> None:
        """Close the connection pool (only when the client created it)."""
        self.http.close()

    def __enter__(self) -> "Movoice":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"Movoice(base_url={self.http.base_url!r})"
