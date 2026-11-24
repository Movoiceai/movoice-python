"""Agents: the voice agents that answer and place calls."""

from __future__ import annotations

from typing import Any, Dict, Iterator, Optional, cast

from ..pagination import Page
from ..types import Agent, CreatedAgent, UpdatedAgent
from ._base import Resource, compact, segment


class Agents(Resource):
    def list(
        self, *, page: Optional[int] = None, per_page: Optional[int] = None, timeout: Optional[float] = None
    ) -> Page[Agent]:
        """One page of your agents, newest first. ``total`` is exact here; ``next()`` walks page numbers."""
        def fetch(p: Dict[str, Any]) -> Dict[str, Any]:
            return self._http.request_page(
                "GET", "/agents", query={"page": p.get("page"), "per_page": p.get("per_page")}, timeout=timeout
            )

        start: Dict[str, Any] = {"page": page, "per_page": per_page}
        return Page(fetch(start), start, fetch)

    def list_all(self, *, per_page: Optional[int] = None, timeout: Optional[float] = None) -> Iterator[Agent]:
        """Every agent, page by page. Stops fetching as soon as you break out of the loop."""
        return iter(self.list(per_page=per_page, timeout=timeout))

    def get(self, agent_id: str, *, timeout: Optional[float] = None) -> Agent:
        """One agent. Raises ``NotFoundError`` if it is not on your account."""
        return cast(Agent, self._http.request("GET", f"/agents/{segment(agent_id)}", timeout=timeout))

    def create(
        self,
        *,
        name: str,
        prompt: str,
        welcome_message: str,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        tts_provider: Optional[str] = None,
        tts_voice: Optional[str] = None,
        asr_provider: Optional[str] = None,
        language: Optional[str] = None,
        webhook_url: Optional[str] = None,
        enable_memory: Optional[bool] = None,
        is_active: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CreatedAgent:
        """Create an agent. Your AI-disclosure and compliance settings are applied automatically."""
        body = compact(
            name=name,
            prompt=prompt,
            welcomeMessage=welcome_message,
            llmProvider=llm_provider,
            llmModel=llm_model,
            ttsProvider=tts_provider,
            ttsVoice=tts_voice,
            asrProvider=asr_provider,
            language=language,
            webhookUrl=webhook_url,
            enableMemory=enable_memory,
            isActive=is_active,
        )
        return cast(
            CreatedAgent,
            self._http.request(
                "POST",
                "/agents",
                body=body,
                idempotency_key=idempotency_key,
                accepts_idempotency_key=True,
                timeout=timeout,
            ),
        )

    def update(
        self,
        agent_id: str,
        *,
        name: Optional[str] = None,
        prompt: Optional[str] = None,
        welcome_message: Optional[str] = None,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        tts_provider: Optional[str] = None,
        tts_voice: Optional[str] = None,
        asr_provider: Optional[str] = None,
        language: Optional[str] = None,
        webhook_url: Optional[str] = None,
        is_active: Optional[bool] = None,
        phone_number: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> UpdatedAgent:
        """Change some fields; anything left out (or ``None``) is untouched.

        ``phone_number`` gives the agent one of your own numbers to answer: the number's ``id``
        from ``numbers.list()``, or the number itself in E.164. It can be sent alone::

            client.agents.update(agent_id, phone_number="+14155550123")

        A number not on your account raises ``NotFoundError``; one another agent answers
        raises ``ConflictError``.
        """
        body = compact(
            name=name,
            prompt=prompt,
            welcomeMessage=welcome_message,
            llmProvider=llm_provider,
            llmModel=llm_model,
            ttsProvider=tts_provider,
            ttsVoice=tts_voice,
            asrProvider=asr_provider,
            language=language,
            webhookUrl=webhook_url,
            isActive=is_active,
            phoneNumber=phone_number,
        )
        return cast(
            UpdatedAgent,
            self._http.request(
                "PATCH",
                f"/agents/{segment(agent_id)}",
                body=body,
                idempotency_key=idempotency_key,
                accepts_idempotency_key=True,
                timeout=timeout,
            ),
        )

    def delete(self, agent_id: str, *, timeout: Optional[float] = None) -> None:
        """Delete the agent, here and in the voice engine. This cannot be undone."""
        self._http.request("DELETE", f"/agents/{segment(agent_id)}", timeout=timeout)
