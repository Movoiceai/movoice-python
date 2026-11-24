"""movoice: the official Python client for the Movoice AI API.

::

    import movoice

    client = movoice.Movoice()  # reads MOVOICE_API_KEY
    call = client.calls.create(agent_id="...", phone_number="+14155550123",
                               context_data={"leadId": "L-889"}, idempotency_key="call-L-889-1")

    event = movoice.webhooks.verify(raw_body, headers, secret)
"""

from . import webhooks
from ._client import Movoice
from ._version import __version__
from .errors import (
    ApiError,
    AuthenticationError,
    ConflictError,
    ConnectionError,
    InsufficientBalanceError,
    InvalidRequestError,
    InvalidResponseError,
    MovoiceError,
    NotFoundError,
    PermissionError,
    RateLimitError,
    WebhookVerificationError,
)
from .pagination import Page

__all__ = [
    "Movoice",
    "Page",
    "webhooks",
    "__version__",
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
]
