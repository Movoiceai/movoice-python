"""Account: the account your key belongs to."""

from __future__ import annotations

from typing import Optional, cast

from ..types import Account
from ._base import Resource


class AccountResource(Resource):
    def get(self, *, timeout: Optional[float] = None) -> Account:
        """Your Movoice Account ID, plan, plan limits and credit balance.

        ``account["accountNumber"]`` is the number to quote to support; it names the account and
        is not a secret. A key whose only scope is Widget, and publishable keys, cannot read it.
        """
        return cast(Account, self._http.request("GET", "/account", timeout=timeout))
