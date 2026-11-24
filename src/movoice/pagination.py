"""Paging, made boring.

``/calls`` pages by cursor; the other list endpoints page by number. ``Page.next()`` follows
the cursor when there is one and increments the page number when there is not, so the same
loop works everywhere::

    page = client.calls.list(per_page=50)
    page.data        # list of calls on this page
    page.has_more
    nxt = page.next()   # Page or None

    for call in page:   # every result across every page; stops fetching when you break
        ...
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Generic, Iterator, List, Optional, TypeVar

T = TypeVar("T")

#: Fetches one page given the query params for it; returns ``{"data": [...], "pagination": {...}}``.
PageFetcher = Callable[[Dict[str, Any]], Dict[str, Any]]


class Page(Generic[T]):
    """One page of results, and the means to get the next one."""

    def __init__(self, raw: Dict[str, Any], params: Dict[str, Any], fetcher: PageFetcher) -> None:
        meta = raw.get("pagination") or {}
        #: The results on this page.
        self.data: List[T] = list(raw.get("data") or [])
        #: 1-based page number.
        self.page: int = meta.get("page", 1)
        self.per_page: int = meta.get("perPage", len(self.data))
        #: Total matching records. ``None`` when the set was too large to count: never rely on it.
        self.total: Optional[int] = meta.get("total")
        self.total_pages: Optional[int] = meta.get("totalPages")
        # A missing hasMore is treated as "no more" rather than looping forever.
        self.has_more: bool = bool(meta.get("hasMore", False))
        #: Opaque cursor for the next page, on endpoints that support cursor paging.
        self.cursor: Optional[str] = meta.get("cursor")
        self._params = params
        self._fetcher = fetcher

    def next(self) -> Optional["Page[T]"]:
        """The next page, or ``None`` when this was the last one."""
        params = self._next_params()
        if params is None:
            return None
        return Page(self._fetcher(params), params, self._fetcher)

    def __iter__(self) -> Iterator[T]:
        """Every result across every page, fetching the next page only when it is reached."""
        current: Optional[Page[T]] = self
        while current is not None:
            yield from current.data
            current = current.next()

    def __repr__(self) -> str:
        return f"Page(page={self.page}, items={len(self.data)}, has_more={self.has_more})"

    def _next_params(self) -> Optional[Dict[str, Any]]:
        if not self.has_more:
            return None
        if self.cursor:
            # Guard against a server that keeps handing back the cursor it was given.
            if self.cursor == self._params.get("cursor"):
                return None
            return {**self._params, "cursor": self.cursor}
        # No cursor on this endpoint: walk page numbers. An empty page means we ran past the
        # end whatever hasMore claimed, so stop rather than loop.
        if not self.data:
            return None
        return {**self._params, "page": self.page + 1, "cursor": None}
