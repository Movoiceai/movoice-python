"""Contacts: your Movoice address book."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, cast

from ..types import Contact
from ._base import Resource, compact, segment


class Contacts(Resource):
    def list(
        self, *, search: Optional[str] = None, per_page: Optional[int] = None, timeout: Optional[float] = None
    ) -> List[Contact]:
        """Your contacts, newest first, up to ``per_page`` (at most 100). No paging: narrow with ``search``."""
        rows = self._http.request(
            "GET", "/contacts", query={"search": search, "per_page": per_page}, timeout=timeout
        )
        return [_normalise(row) for row in rows] if isinstance(rows, list) else []

    def create(
        self,
        *,
        name: str,
        phone: str,
        email: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        notes: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Contact:
        """Add a contact. A second contact with the same phone raises ``ConflictError``."""
        body = compact(name=name, phone=phone, email=email, tags=None if tags is None else [*tags], notes=notes)
        return _normalise(self._http.request("POST", "/contacts", body=body, timeout=timeout))

    def update(
        self,
        contact_id: str,
        *,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        notes: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Contact:
        """Change some fields; anything left out is untouched."""
        body = compact(name=name, phone=phone, email=email, tags=None if tags is None else [*tags], notes=notes)
        return _normalise(
            self._http.request("PATCH", f"/contacts/{segment(contact_id)}", body=body, timeout=timeout)
        )

    def delete(self, contact_id: str, *, timeout: Optional[float] = None) -> None:
        """Delete the contact. This cannot be undone."""
        self._http.request("DELETE", f"/contacts/{segment(contact_id)}", timeout=timeout)


def _normalise(row: Any) -> Contact:
    """A test key's create/update answer names the contact ``_id``; hand back ``id`` either way."""
    r = dict(row) if isinstance(row, dict) else {}
    if "id" not in r and isinstance(r.get("_id"), str):
        r["id"] = r.pop("_id")
    return cast(Contact, r)
