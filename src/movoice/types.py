"""What the API returns, as ``TypedDict`` shapes for editors and type checkers.

Responses are plain ``dict`` objects with the API's own (camelCase) keys; these types only
describe them. Two conventions worth knowing:

- every timestamp is epoch MILLISECONDS;
- a call's ``duration`` is SECONDS.

Keys marked optional in the API are omitted from the JSON, never null, except on phone
numbers, contacts, appointments and the account, where absent values are ``None``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

__all__ = [
    "Agent",
    "CreatedAgent",
    "UpdatedAgent",
    "AgentPhoneNumber",
    "Call",
    "CreatedCall",
    "HangupResult",
    "TranscriptEntry",
    "Contact",
    "Appointment",
    "AppointmentPage",
    "CreatedAppointment",
    "CancelledAppointment",
    "RescheduledAppointment",
    "Availability",
    "PhoneNumber",
    "MessageResult",
    "CallerMemory",
    "MemoryRecallResult",
    "Account",
    "CallWebhookEvent",
]


class _LLM(TypedDict, total=False):
    provider: str
    model: str


class _TTS(TypedDict, total=False):
    provider: str
    voice: str


class _ASR(TypedDict, total=False):
    provider: str


class Agent(TypedDict, total=False):
    """An agent as returned by ``agents.list()`` and ``agents.get()``."""

    #: The agent's Movoice id. Pass it as ``agent_id`` everywhere.
    id: str
    #: The agent's id inside the Movoice WebSocket voice engine (the key is the name the API has
    #: always sent). It is the ``agent_id`` on a webhook; ``agent.id`` there is the Movoice id.
    bolnaAgentId: str
    name: str
    prompt: str
    welcomeMessage: str
    llm: _LLM
    tts: _TTS
    asr: _ASR
    language: str
    webhookUrl: str
    isActive: bool
    createdAt: int
    updatedAt: int


class CreatedAgent(TypedDict, total=False):
    """What ``agents.create()`` returns: the settings it applied, with no timestamps."""

    id: str
    #: The agent's id inside the Movoice WebSocket voice engine. See ``Agent``.
    bolnaAgentId: str
    name: str
    prompt: str
    welcomeMessage: str
    llm: _LLM
    tts: _TTS
    asr: _ASR
    language: str
    webhookUrl: str
    enableMemory: bool
    isActive: bool


class AgentPhoneNumber(TypedDict):
    id: str
    number: str


class UpdatedAgent(Agent, total=False):
    """``agents.update()``: the agent, plus the number it now answers when you sent ``phone_number``."""

    phoneNumber: AgentPhoneNumber


class TranscriptEntry(TypedDict, total=False):
    speaker: str
    text: str
    timestamp: int
    isFinal: bool
    confidence: float


class Call(TypedDict, total=False):
    """A call as returned by ``calls.list()`` and ``calls.get()``."""

    #: The call's Movoice id: the ``id`` ``calls.create()`` returned and the ``id`` on its webhooks.
    id: str
    #: The call's id inside the Movoice WebSocket voice engine: the ``call_id`` on its webhooks.
    movoiceWebSocketCallId: str
    agentId: str
    phoneNumber: str
    #: Free-form, e.g. "initiated", "answered_phone", "completed".
    status: str
    #: SECONDS. Absent until the call ends.
    duration: int
    startedAt: int
    completedAt: int
    #: The ``context_data`` you sent to ``calls.create()``, exactly as you sent it.
    contextData: Dict[str, Any]
    summary: str
    #: Only when asked for with ``include_transcript=True`` and the call finished with one.
    transcript: List[TranscriptEntry]


class CreatedCall(TypedDict, total=False):
    """What ``calls.create()`` returns. The call is accepted, not completed."""

    #: Store it next to your lead. With a test key it starts with ``test_call_``.
    id: str
    movoiceWebSocketCallId: str
    agentId: str
    phoneNumber: str
    status: Literal["initiated"]
    startedAt: int
    contextData: Dict[str, Any]
    #: ``False`` when a test key placed a pretend call: nothing dialled, nothing charged.
    livemode: bool


class HangupResult(TypedDict, total=False):
    id: str
    #: Which phone network carried the call, e.g. "twilio".
    provider: str
    status: Literal["hangup_requested"]
    livemode: bool


class Contact(TypedDict, total=False):
    id: str
    name: str
    phone: str
    email: Optional[str]
    tags: List[str]
    notes: Optional[str]
    createdAt: int
    updatedAt: int
    livemode: bool


class Appointment(TypedDict, total=False):
    id: str
    agentId: Optional[str]
    customerName: Optional[str]
    customerPhone: Optional[str]
    customerEmail: Optional[str]
    serviceType: Optional[str]
    #: YYYY-MM-DD, in the booking's own time zone.
    date: str
    #: 24-hour HH:MM, in the booking's own time zone.
    time: str
    timezone: Optional[str]
    durationMinutes: int
    #: "pending", "confirmed", "cancelled", "completed" or "no_show".
    status: str
    #: "call" when an agent booked it on a call, "manual" otherwise.
    source: str
    calendarSynced: bool
    notes: Optional[str]
    createdAt: int
    livemode: bool


class AppointmentPage(TypedDict):
    items: List[Appointment]
    #: Pass back as ``cursor`` for the next page; ``None`` on the last one.
    cursor: Optional[str]


class CreatedAppointment(TypedDict, total=False):
    id: str
    status: str
    date: str
    time: str
    durationMinutes: int
    calendarSynced: bool
    confirmationSent: Optional[str]
    livemode: bool


class CancelledAppointment(TypedDict, total=False):
    id: str
    status: Literal["cancelled"]
    calendarRemoved: bool
    customerTold: Optional[str]
    livemode: bool


class _PreviousSlot(TypedDict):
    date: str
    time: str


class RescheduledAppointment(TypedDict, total=False):
    id: str
    status: Literal["confirmed"]
    date: str
    time: str
    previous: Optional[_PreviousSlot]
    calendarMoved: bool
    customerTold: Optional[str]
    livemode: bool


class Availability(TypedDict, total=False):
    date: str
    timezone: str
    #: 24-hour HH:MM start times.
    slots: List[str]
    #: Which calendar answered, e.g. "google"; "sample" for a test key; None when none is connected.
    calendar: Optional[str]
    closed: bool
    livemode: bool


class _Capabilities(TypedDict):
    voice: Optional[bool]
    sms: Optional[bool]


class PhoneNumber(TypedDict, total=False):
    id: str
    phoneNumber: str
    friendlyName: Optional[str]
    #: None does NOT mean unrouted: an agent group or the dialer can answer it instead.
    assignedAgentId: Optional[str]
    capabilities: _Capabilities
    isActive: Optional[bool]
    createdAt: Optional[int]


class MessageResult(TypedDict, total=False):
    to: str
    channel: Literal["sms", "whatsapp"]
    #: Always the string "sent"; carries no delivery meaning. Read ``providerMessageId``.
    status: str
    providerMessageId: Optional[str]


class CallerMemory(TypedDict, total=False):
    name: Optional[str]
    total_calls: int
    #: A display string in en-IN, e.g. "14/3/2026", not a timestamp.
    last_call_date: Optional[str]
    last_call_summary: Optional[str]
    facts: List[str]
    history: List[Dict[str, Any]]


class MemoryRecallResult(TypedDict, total=False):
    """Branch on ``found``: "nothing remembered" is a normal answer, not an error."""

    found: bool
    data: CallerMemory
    context: str
    message: str
    welcome_message: Optional[str]


class Account(TypedDict, total=False):
    #: Your Movoice Account ID: 11 digits, the number to quote to support. Not a secret.
    accountNumber: Optional[str]
    userId: str
    email: str
    name: Optional[str]
    subscriptionTier: Optional[str]
    subscriptionStatus: Optional[str]
    maxAgents: Optional[int]
    #: The plan's monthly call LIMIT, not a usage count.
    maxCallsPerMonth: Optional[int]
    trialEndsAt: Optional[int]
    currentPeriodEnd: Optional[int]
    #: Wallet balance in US CENTS (1000 = $10.00), whatever currency you pay in.
    creditBalanceUsdCents: Optional[int]


class _WebhookAgent(TypedDict):
    id: str


class _WebhookTranscriptLine(TypedDict, total=False):
    speaker: str
    text: str
    timestamp: float


class CallWebhookEvent(TypedDict, total=False):
    """A call event as Movoice sends it. The payload is flat (snake_case keys)."""

    #: Stable id of this event. A retry carries the same one: drop duplicates by it.
    event_id: str
    #: "call.started", "call.completed", "call.failed" or "call.missed".
    event: str
    #: The call's Movoice id: the ``id`` that ``calls.create()`` returned.
    id: str
    #: The ``context_data`` you sent to ``calls.create()``.
    context_data: Dict[str, Any]
    #: The Movoice agent that handled the call.
    agent: Optional[_WebhookAgent]
    #: The call's id inside the Movoice WebSocket voice engine.
    call_id: str
    #: The agent's id inside the voice engine. Use ``agent["id"]`` for the Movoice agent id.
    agent_id: str
    agent_name: str
    caller_phone: str
    direction: str
    duration_seconds: int
    summary: str
    recording_url: str
    sentiment: str
    transcript: List[_WebhookTranscriptLine]
    #: ISO 8601.
    timestamp: str
    #: ``False`` on a test key's pretend events and on "Send test" from the Developer page.
    livemode: bool
