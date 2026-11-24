"""Calls: place them, hang them up, and read their history and transcripts."""

from __future__ import annotations

from typing import Any, Dict, Iterator, Mapping, Optional, cast

from ..pagination import Page
from ..types import Call, CreatedCall, HangupResult
from ._base import Resource, compact, segment


class Calls(Resource):
    def list(
        self,
        *,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        cursor: Optional[str] = None,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Page[Call]:
        """One page of calls, newest first.

        The one list endpoint with cursor paging; ``next()`` follows the cursor. ``total`` is
        ``None`` when the set is too large to count.
        """
        def fetch(p: Dict[str, Any]) -> Dict[str, Any]:
            query = {
                "page": p.get("page"),
                "per_page": p.get("per_page"),
                "cursor": p.get("cursor"),
                "agent_id": p.get("agent_id"),
                "status": p.get("status"),
            }
            return self._http.request_page("GET", "/calls", query=query, timeout=timeout)

        start: Dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "cursor": cursor,
            "agent_id": agent_id,
            "status": status,
        }
        return Page(fetch(start), start, fetch)

    def list_all(
        self,
        *,
        per_page: Optional[int] = None,
        cursor: Optional[str] = None,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Iterator[Call]:
        """Every matching call, following the cursor."""
        return iter(self.list(per_page=per_page, cursor=cursor, agent_id=agent_id, status=status, timeout=timeout))

    def get(self, call_id: str, *, include_transcript: bool = False, timeout: Optional[float] = None) -> Call:
        """One call. ``include_transcript=True`` adds the transcript once the call has one."""
        # The API compares against the exact string "true"; anything else omits it.
        query = {"include_transcript": "true"} if include_transcript else None
        return cast(Call, self._http.request("GET", f"/calls/{segment(call_id)}", query=query, timeout=timeout))

    def create(
        self,
        *,
        agent_id: str,
        phone_number: str,
        context_data: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CreatedCall:
        """Place an outbound call. This spends your balance (a ``mv_test_`` key places a pretend
        call that dials nobody and costs nothing).

        ``context_data`` is your own data for this call, e.g. ``{"leadId": "L-889", "name": "Rahul"}``.
        Each key fills the matching ``{placeholder}`` in the agent's prompt and greeting, and the
        whole object comes back as ``context_data`` on this call's webhooks and as
        ``contextData`` on ``calls.get()``.

        Without an ``idempotency_key`` it is never retried, even on a timeout: the first attempt
        may have dialled. With one (8 to 255 characters), a timeout or 5xx is retried safely,
        because the server answers a repeat of the same key with the first answer.
        """
        body = compact(
            agentId=agent_id,
            phoneNumber=phone_number,
            contextData=dict(context_data) if context_data is not None else None,
        )
        return cast(
            CreatedCall,
            self._http.request(
                "POST",
                "/calls",
                body=body,
                idempotency_key=idempotency_key,
                accepts_idempotency_key=True,
                timeout=timeout,
            ),
        )

    def hangup(self, call_id: str, *, timeout: Optional[float] = None) -> HangupResult:
        """Ask for a call in progress to be ended; its ``call.completed`` webhook follows.

        Raises ``NotFoundError`` for an id that is not one of your calls. Never retried.
        """
        return cast(
            HangupResult,
            self._http.request("POST", f"/calls/{segment(call_id)}/hangup", timeout=timeout),
        )
