"""Shared helpers for the resource modules."""

from __future__ import annotations

from typing import Any, Dict
from urllib.parse import quote

from .._http import HttpClient


class Resource:
    def __init__(self, http: HttpClient) -> None:
        self._http = http


def compact(**fields: Any) -> Dict[str, Any]:
    """The fields that were given. ``None`` means "leave it out", never "send null"."""
    return {key: value for key, value in fields.items() if value is not None}


def segment(value: str) -> str:
    """One path segment, escaped the way JavaScript's encodeURIComponent escapes it."""
    return quote(str(value), safe="!'()*-._~")
