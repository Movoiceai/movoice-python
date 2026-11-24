"""The API's resources, one module each."""

from .account import AccountResource
from .agents import Agents
from .appointments import Appointments, AvailabilityResource
from .calls import Calls
from .contacts import Contacts
from .memory import Memory
from .messages import Messages
from .numbers import Numbers

__all__ = [
    "AccountResource",
    "Agents",
    "Appointments",
    "AvailabilityResource",
    "Calls",
    "Contacts",
    "Memory",
    "Messages",
    "Numbers",
]
