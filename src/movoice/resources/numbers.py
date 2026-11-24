"""Phone numbers: read only.

Buying and releasing numbers is deliberately not exposed over the API: those spend money.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, Optional

from ..pagination import Page
from ..types import PhoneNumber
from ._base import Resource


class Numbers(Resource):
    def list(
        self, *, page: Optional[int] = None, per_page: Optional[int] = None, timeout: Optional[float] = None
    ) -> Page[PhoneNumber]:
        """One page of your phone numbers. No cursor here; ``next()`` walks page numbers."""
        def fetch(p: Dict[str, Any]) -> Dict[str, Any]:
            return self._http.request_page(
                "GET", "/numbers", query={"page": p.get("page"), "per_page": p.get("per_page")}, timeout=timeout
            )

        start: Dict[str, Any] = {"page": page, "per_page": per_page}
        return Page(fetch(start), start, fetch)

    def list_all(self, *, per_page: Optional[int] = None, timeout: Optional[float] = None) -> Iterator[PhoneNumber]:
        """Every phone number on the account, page by page."""
        return iter(self.list(per_page=per_page, timeout=timeout))
