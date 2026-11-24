"""Memory: what an agent remembers about a caller."""

from __future__ import annotations

from typing import Optional, cast

from ..types import MemoryRecallResult
from ._base import Resource


class Memory(Resource):
    def recall(self, *, agent_id: str, phone: str, timeout: Optional[float] = None) -> MemoryRecallResult:
        """What this agent remembers about this caller.

        Unlike every other endpoint this one answers with a bare object, and "nothing
        remembered" is a 200, not a 404. Branch on ``found``, never on catching an error::

            memory = client.memory.recall(agent_id=agent_id, phone="+14155550123")
            if memory["found"]:
                print(memory["data"]["total_calls"])
            else:
                print(memory["message"])
        """
        return cast(
            MemoryRecallResult,
            self._http.request_raw(
                "GET", "/memory/recall", query={"agent_id": agent_id, "phone": phone}, timeout=timeout
            ),
        )
