"""The client, against an httpx.MockTransport: no network, no key, no charges.

Mirrors movoice-sdk/test/client.test.mjs (the TypeScript package) case for case where the
surface is the same, plus the Python-only parts (MOVOICE_API_KEY, keyword arguments).
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

import movoice
from movoice import (
    ApiError,
    AuthenticationError,
    ConflictError,
    ConnectionError,
    InsufficientBalanceError,
    InvalidRequestError,
    InvalidResponseError,
    Movoice,
    MovoiceError,
    NotFoundError,
    PermissionError,
    RateLimitError,
)

KEY = "mv_live_" + "a" * 32
BASE = "https://app.movoice.ai/api/v1"


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    """Retries wait between attempts; the tests count attempts, not seconds."""
    waits = []
    monkeypatch.setattr("movoice._http._sleep", waits.append)
    return waits


def stub(responses, **options):
    """A client whose transport replays ``responses`` (the last one repeats) and records requests."""
    seen = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        status = item.get("status", 200)
        headers = {"content-type": "application/json", **item.get("headers", {})}
        if status == 204:
            return httpx.Response(204, headers=headers)
        if "text" in item:
            return httpx.Response(status, text=item["text"], headers=headers)
        return httpx.Response(status, content=json.dumps(item.get("body", {})).encode(), headers=headers)

    client = Movoice(options.pop("api_key", KEY), http_client=httpx.Client(transport=httpx.MockTransport(handler)), **options)
    return client, seen


def ok(data):
    return {"status": 200, "body": {"success": True, "data": data}}


def err(status, code, message="no", **extra):
    return {"status": status, "body": {"success": False, "error": {"code": code, "message": message, **extra}}}


def query(request):
    return {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}


def sent_json(request):
    return json.loads(request.content)


def future_day(days):
    return (date.today() + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_rejects_a_publishable_key_before_any_request():
    with pytest.raises(MovoiceError, match="publishable"):
        Movoice("mv_pk_" + "b" * 32)


def test_rejects_an_empty_key(monkeypatch):
    monkeypatch.delenv("MOVOICE_API_KEY", raising=False)
    with pytest.raises(MovoiceError, match="No API key"):
        Movoice("   ")
    with pytest.raises(MovoiceError, match="MOVOICE_API_KEY"):
        Movoice()


def test_reads_the_key_from_MOVOICE_API_KEY(monkeypatch):
    monkeypatch.setenv("MOVOICE_API_KEY", KEY)
    seen = []
    transport = httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json={"success": True, "data": []}))
    client = Movoice(http_client=httpx.Client(transport=transport))
    client.agents.list()
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"


def test_base_url_can_point_at_another_deploy():
    client, seen = stub([ok({"id": "a1"})], base_url="https://testing.movoice.ai/")
    client.agents.get("a1")
    assert str(seen[0].url) == "https://testing.movoice.ai/api/v1/agents/a1"


# ---------------------------------------------------------------------------
# The request itself
# ---------------------------------------------------------------------------


def test_requests_api_v1_and_sends_the_bearer_key():
    client, seen = stub([ok({"id": "a1"})])
    client.agents.get("a1")
    assert str(seen[0].url) == f"{BASE}/agents/a1"
    assert seen[0].headers["Authorization"] == f"Bearer {KEY}"
    assert seen[0].headers["Accept"] == "application/json"


def test_an_id_is_escaped_as_one_path_segment():
    client, seen = stub([ok({"id": "x"})])
    client.agents.get("a/b c")
    assert seen[0].url.raw_path.decode() == "/api/v1/agents/a%2Fb%20c"


def test_default_headers_cannot_replace_the_key():
    client, seen = stub([ok([])], default_headers={"authorization": "Bearer stolen", "X-Trace": "t1"})
    client.agents.list()
    assert seen[0].headers.get_list("authorization") == [f"Bearer {KEY}"]
    assert seen[0].headers["x-trace"] == "t1"


def test_maps_keyword_arguments_onto_the_api_snake_case_query_names():
    client, seen = stub([ok([])])
    client.calls.list(per_page=50, agent_id="ag_1", page=2, status="completed")
    assert query(seen[0]) == {"per_page": "50", "agent_id": "ag_1", "page": "2", "status": "completed"}


def test_asks_for_a_transcript_only_when_told_to():
    client, seen = stub([ok({"id": "c1"})])
    client.calls.get("c1")
    client.calls.get("c1", include_transcript=True)
    assert "include_transcript" not in query(seen[0])
    assert query(seen[1])["include_transcript"] == "true"


def test_unwraps_the_envelope():
    client, _ = stub([ok({"id": "a1", "name": "Front desk"})])
    assert client.agents.get("a1") == {"id": "a1", "name": "Front desk"}


def test_a_204_delete_returns_none():
    client, seen = stub([{"status": 204}], max_retries=0)
    assert client.agents.delete("a1") is None
    assert seen[0].method == "DELETE"


def test_a_200_without_the_envelope_is_an_invalid_response():
    client, _ = stub([{"status": 200, "body": {"id": "a1"}}])
    with pytest.raises(InvalidResponseError):
        client.agents.get("a1")


# ---------------------------------------------------------------------------
# Errors: status picks the class, one table
# ---------------------------------------------------------------------------

ERROR_TABLE = [
    (401, {"error": {"code": "unauthorized", "message": "Invalid API key"}}, AuthenticationError, "UNAUTHORIZED"),
    (402, {"error": "PLAN_MINUTES_EXHAUSTED", "message": "You've used all included minutes."}, InsufficientBalanceError, "PLAN_MINUTES_EXHAUSTED"),
    (403, {"success": False, "error": {"code": "FORBIDDEN", "message": "Missing required permissions"}}, PermissionError, "FORBIDDEN"),
    (403, {"error": {"code": "forbidden", "message": "Missing required permissions"}}, PermissionError, "FORBIDDEN"),
    (404, {"success": False, "error": {"code": "NOT_FOUND", "message": "Agent not found"}}, NotFoundError, "NOT_FOUND"),
    (409, {"success": False, "error": {"code": "CONFLICT", "message": "That number is answered by another agent"}}, ConflictError, "CONFLICT"),
    (400, {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Request validation failed"}}, InvalidRequestError, "VALIDATION_ERROR"),
    (422, {}, InvalidRequestError, "UNPROCESSABLE_ENTITY"),
    (429, {"error": {"code": "RATE_LIMITED", "message": "slow"}}, RateLimitError, "RATE_LIMITED"),
    (500, {"success": False, "error": {"code": "INTERNAL_ERROR", "message": "boom"}}, ApiError, "INTERNAL_ERROR"),
    (503, {}, ApiError, "SERVICE_UNAVAILABLE"),
]


@pytest.mark.parametrize("status,body,cls,code", ERROR_TABLE, ids=[f"{s}-{c.__name__}-{code}" for s, _, c, code in ERROR_TABLE])
def test_errors_map_to_classes(status, body, cls, code):
    client, _ = stub([{"status": status, "body": body}], max_retries=0)
    with pytest.raises(cls) as info:
        client.agents.get("a1")
    assert info.value.code == code
    assert info.value.status == status
    assert isinstance(info.value, MovoiceError)
    assert str(info.value)  # never a bare status number


def test_the_raw_code_and_body_are_kept():
    client, _ = stub([{"status": 403, "body": {"error": {"code": "forbidden", "message": "m"}}}], max_retries=0)
    with pytest.raises(PermissionError) as info:
        client.agents.list()
    assert info.value.raw_code == "forbidden"
    assert info.value.body == {"error": {"code": "forbidden", "message": "m"}}


def test_the_plain_string_envelope_message_is_kept():
    client, _ = stub([{"status": 402, "body": {"error": "PLAN_MINUTES_EXHAUSTED", "message": "You've used all included minutes."}}], max_retries=0)
    with pytest.raises(InsufficientBalanceError, match="You've used all included minutes."):
        client.calls.create(agent_id="a", phone_number="+15551234567")


def test_a_bare_string_error_becomes_the_message():
    client, _ = stub([{"status": 403, "body": {"error": "Forbidden"}}], max_retries=0)
    with pytest.raises(PermissionError, match="^Forbidden$"):
        client.memory.recall(agent_id="a", phone="+1")


def test_a_validation_failure_exposes_field_errors():
    client, _ = stub([err(400, "VALIDATION_ERROR", details={"errors": {"prompt": ["Too short"]}})], max_retries=0)
    with pytest.raises(InvalidRequestError) as info:
        client.agents.create(name="x", prompt="y", welcome_message="z")
    assert info.value.field_errors == {"prompt": ["Too short"]}


def test_a_permission_error_exposes_the_required_scopes():
    client, _ = stub([err(403, "forbidden", details={"required": ["agents:write"]})], max_retries=0)
    with pytest.raises(PermissionError) as info:
        client.agents.delete("a1")
    assert info.value.required_scopes == ["agents:write"]


def test_an_html_error_page_from_a_proxy_does_not_crash_the_client():
    client, _ = stub([{"status": 502, "text": "<html>502 Bad Gateway</html>", "headers": {"content-type": "text/html"}}], max_retries=0)
    with pytest.raises(ApiError, match="502 Bad Gateway"):
        client.agents.list()


def test_a_rate_limit_error_carries_retry_after():
    client, _ = stub([{"status": 429, "body": {"error": {"code": "RATE_LIMITED", "message": "slow"}}, "headers": {"retry-after": "42"}}], max_retries=0)
    with pytest.raises(RateLimitError) as info:
        client.agents.list()
    assert info.value.retry_after == 42


def test_a_timeout_is_a_connection_error_with_code_TIMEOUT():
    client, _ = stub([httpx.ReadTimeout("slow")], max_retries=0)
    with pytest.raises(ConnectionError) as info:
        client.agents.list()
    assert info.value.code == "TIMEOUT"


def test_a_refused_connection_is_a_connection_error():
    client, _ = stub([httpx.ConnectError("refused")], max_retries=0)
    with pytest.raises(ConnectionError) as info:
        client.account.get()
    assert info.value.code == "CONNECTION_ERROR"


# ---------------------------------------------------------------------------
# Retries: the money-safety rules
# ---------------------------------------------------------------------------

BOOM = err(500, "INTERNAL_ERROR", "boom")


def test_retries_a_GET_on_500():
    client, seen = stub([BOOM, ok([])], max_retries=2)
    client.agents.list()
    assert len(seen) == 2


def test_retries_a_GET_after_a_timeout():
    client, seen = stub([httpx.ReadTimeout("slow"), ok([])], max_retries=2)
    client.agents.list()
    assert len(seen) == 2


def test_never_retries_a_call_on_500_without_a_key():
    client, seen = stub([BOOM], max_retries=3)
    with pytest.raises(ApiError):
        client.calls.create(agent_id="a", phone_number="+15551234567")
    assert len(seen) == 1, "a POST that spends money must be attempted exactly once"


def test_never_retries_a_call_after_a_timeout_without_a_key():
    client, seen = stub([httpx.ReadTimeout("slow")], max_retries=3)
    with pytest.raises(ConnectionError):
        client.calls.create(agent_id="a", phone_number="+15551234567")
    assert len(seen) == 1


def test_never_retries_a_message_on_500():
    client, seen = stub([BOOM], max_retries=3)
    with pytest.raises(ApiError):
        client.messages.send(to="+15551234567", body="hi")
    assert len(seen) == 1


def test_does_retry_a_POST_on_429_because_it_was_refused_before_doing_anything(no_backoff_sleep):
    client, seen = stub(
        [
            {"status": 429, "body": {"error": {"code": "RATE_LIMITED", "message": "slow"}}, "headers": {"retry-after": "3"}},
            {"status": 201, "body": {"success": True, "data": {"id": "j57abc", "status": "initiated"}}},
        ],
        max_retries=2,
    )
    client.calls.create(agent_id="a", phone_number="+15551234567")
    assert len(seen) == 2
    assert no_backoff_sleep == [3.0], "the wait honours Retry-After"


def test_gives_up_after_max_retries():
    client, seen = stub([BOOM], max_retries=2)
    with pytest.raises(ApiError):
        client.agents.list()
    assert len(seen) == 3


# ---------------------------------------------------------------------------
# Calls: contextData, Idempotency-Key, hangup
# ---------------------------------------------------------------------------


def test_calls_create_sends_context_data_and_returns_both_ids():
    created = {
        "id": "j57abc",
        "movoiceWebSocketCallId": "engine-call-1",
        "agentId": "k17agent",
        "phoneNumber": "+14155550123",
        "status": "initiated",
        "contextData": {"leadId": "L-889", "name": "Rahul"},
    }
    client, seen = stub([{"status": 201, "body": {"success": True, "data": created}}])
    call = client.calls.create(agent_id="k17agent", phone_number="+14155550123", context_data={"leadId": "L-889", "name": "Rahul"})
    assert call["id"] == "j57abc"
    assert call["movoiceWebSocketCallId"] == "engine-call-1"
    assert seen[0].method == "POST"
    assert str(seen[0].url) == f"{BASE}/calls"
    assert sent_json(seen[0]) == {
        "agentId": "k17agent",
        "phoneNumber": "+14155550123",
        "contextData": {"leadId": "L-889", "name": "Rahul"},
    }
    assert seen[0].headers["content-type"] == "application/json"
    assert "idempotency-key" not in seen[0].headers, "no key unless asked for"


def test_calls_create_leaves_context_data_out_when_not_given():
    client, seen = stub([ok({"id": "j57abc"})])
    client.calls.create(agent_id="a", phone_number="+15551234567")
    assert sent_json(seen[0]) == {"agentId": "a", "phoneNumber": "+15551234567"}


def test_calls_create_sends_the_idempotency_key():
    client, seen = stub([ok({"id": "j57abc"})])
    client.calls.create(agent_id="a", phone_number="+15551234567", idempotency_key="call-L-889-1")
    assert seen[0].headers["Idempotency-Key"] == "call-L-889-1"


def test_with_an_idempotency_key_a_call_is_retried_on_500_with_the_same_key():
    client, seen = stub([BOOM, {"status": 201, "body": {"success": True, "data": {"id": "j57abc"}}}], max_retries=2)
    call = client.calls.create(agent_id="a", phone_number="+15551234567", idempotency_key="call-L-889-1")
    assert call["id"] == "j57abc"
    assert len(seen) == 2
    assert [r.headers["Idempotency-Key"] for r in seen] == ["call-L-889-1", "call-L-889-1"]


def test_an_idempotency_key_shorter_than_8_characters_raises_before_sending():
    client, seen = stub([ok({})])
    with pytest.raises(MovoiceError, match="8 to 255"):
        client.calls.create(agent_id="a", phone_number="+15551234567", idempotency_key="short")
    assert seen == []


def test_an_idempotency_key_on_a_route_that_ignores_it_raises_before_sending():
    client, seen = stub([ok({"providerMessageId": "SM1"})])
    with pytest.raises(MovoiceError, match="does not accept an Idempotency-Key"):
        client.http.request("POST", "/messages", body={"to": "+1", "body": "hi"}, idempotency_key="msg-000001")
    with pytest.raises(TypeError):
        client.messages.send(to="+15551234567", body="hi", idempotency_key="msg-000001")  # type: ignore[call-arg]
    assert seen == []


def test_calls_hangup_posts_to_the_hangup_path_and_is_not_retried():
    client, seen = stub([BOOM], max_retries=3)
    with pytest.raises(ApiError):
        client.calls.hangup("j57abc")
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert str(seen[0].url) == f"{BASE}/calls/j57abc/hangup"


def test_calls_hangup_returns_the_answer():
    client, seen = stub([ok({"id": "j57abc", "provider": "twilio", "status": "hangup_requested"})])
    assert client.calls.hangup("j57abc")["status"] == "hangup_requested"
    assert seen[0].content == b""


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


def test_agents_update_sends_phone_number_alone_and_returns_the_number():
    client, seen = stub([ok({"id": "k17agent", "phoneNumber": {"id": "pn1", "number": "+14155550123"}})])
    agent = client.agents.update("k17agent", phone_number="+14155550123")
    assert seen[0].method == "PATCH"
    assert str(seen[0].url) == f"{BASE}/agents/k17agent"
    assert sent_json(seen[0]) == {"phoneNumber": "+14155550123"}
    assert agent["phoneNumber"] == {"id": "pn1", "number": "+14155550123"}


def test_agents_update_maps_fields_to_camel_case_and_takes_a_key():
    client, seen = stub([ok({"id": "k17agent"})])
    client.agents.update("k17agent", welcome_message="Hi", is_active=False, idempotency_key="upd-0000001")
    assert sent_json(seen[0]) == {"welcomeMessage": "Hi", "isActive": False}
    assert seen[0].headers["Idempotency-Key"] == "upd-0000001"


def test_agents_create_sends_camel_case_body():
    client, seen = stub([ok({"id": "k17agent"})])
    client.agents.create(name="Front desk", prompt="Be kind", welcome_message="Hello", tts_voice="rachel", enable_memory=True)
    assert seen[0].method == "POST"
    assert sent_json(seen[0]) == {
        "name": "Front desk",
        "prompt": "Be kind",
        "welcomeMessage": "Hello",
        "ttsVoice": "rachel",
        "enableMemory": True,
    }


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------


def paged(data, pagination):
    return {"status": 200, "body": {"success": True, "data": data, "meta": {"pagination": pagination}}}


def test_follows_the_cursor_when_the_endpoint_provides_one():
    client, seen = stub([
        paged([{"id": "c1"}], {"page": 1, "perPage": 1, "hasMore": True, "cursor": "CUR1"}),
        paged([{"id": "c2"}], {"page": 2, "perPage": 1, "hasMore": False, "cursor": None}),
    ])
    assert [c["id"] for c in client.calls.list_all(per_page=1)] == ["c1", "c2"]
    assert query(seen[1])["cursor"] == "CUR1"


def test_walks_page_numbers_when_the_endpoint_has_no_cursor():
    client, seen = stub([
        paged([{"id": "n1"}], {"page": 1, "perPage": 1, "total": 2, "totalPages": 2, "hasMore": True}),
        paged([{"id": "n2"}], {"page": 2, "perPage": 1, "total": 2, "totalPages": 2, "hasMore": False}),
    ])
    assert [n["id"] for n in client.numbers.list_all(per_page=1)] == ["n1", "n2"]
    assert query(seen[1])["page"] == "2"


def test_stops_when_the_server_keeps_returning_the_same_cursor():
    client, seen = stub([paged([{"id": "c1"}], {"page": 1, "perPage": 1, "hasMore": True, "cursor": "SAME"})])
    assert [c["id"] for c in client.calls.list_all(cursor="SAME")] == ["c1"]
    assert len(seen) == 1


def test_a_missing_total_is_none_not_zero():
    client, _ = stub([paged([{"id": "c1"}], {"page": 1, "perPage": 20, "hasMore": False, "cursor": None})])
    page = client.calls.list()
    assert page.total is None
    assert page.has_more is False
    assert page.next() is None


def test_breaking_out_of_the_loop_fetches_no_more_pages():
    client, seen = stub([paged([{"id": "a1"}, {"id": "a2"}], {"page": 1, "perPage": 2, "hasMore": True})])
    for agent in client.agents.list_all(per_page=2):
        break
    assert len(seen) == 1


# ---------------------------------------------------------------------------
# Messaging: status lies, providerMessageId does not
# ---------------------------------------------------------------------------


def test_raises_NOT_SENT_when_a_200_sent_carries_no_carrier_id():
    client, _ = stub([ok({"to": "+1", "channel": "sms", "status": "sent", "providerMessageId": None})])
    with pytest.raises(MovoiceError) as info:
        client.messages.send(to="+15551234567", body="hi")
    assert info.value.code == "NOT_SENT"


def test_returns_the_result_when_a_carrier_id_is_present():
    client, seen = stub([ok({"to": "+1", "channel": "whatsapp", "status": "sent", "providerMessageId": "SM123"})])
    assert client.messages.send_whatsapp(to="+15551234567", body="hi")["providerMessageId"] == "SM123"
    assert str(seen[0].url) == f"{BASE}/whatsapp"


def test_an_opt_out_block_is_an_error_not_a_silent_success():
    client, _ = stub([err(400, "BAD_REQUEST", "This recipient opted out of messages from you by replying STOP.")], max_retries=0)
    with pytest.raises(InvalidRequestError, match="opted out"):
        client.messages.send_whatsapp(to="+15551234567", body="hi")


# ---------------------------------------------------------------------------
# Memory and account
# ---------------------------------------------------------------------------


def test_recall_returns_the_bare_body():
    client, seen = stub([{"status": 200, "body": {"found": True, "data": {"name": "Ada", "total_calls": 3, "facts": [], "history": []}, "context": "..."}}])
    memory = client.memory.recall(agent_id="ag_1", phone="+15551234567")
    assert memory["found"] is True
    assert memory["data"]["total_calls"] == 3
    assert query(seen[0]) == {"agent_id": "ag_1", "phone": "+15551234567"}


def test_found_false_is_a_normal_answer():
    client, _ = stub([{"status": 200, "body": {"found": False, "message": "No memory for this caller yet."}}])
    memory = client.memory.recall(agent_id="ag_1", phone="+15551234567")
    assert memory == {"found": False, "message": "No memory for this caller yet."}


def test_account_get_reads_the_account_id():
    client, seen = stub([ok({"accountNumber": "72601815914", "userId": "u1", "email": "a@example.com"})])
    assert client.account.get()["accountNumber"] == "72601815914"
    assert str(seen[0].url) == f"{BASE}/account"
    assert seen[0].method == "GET"


# ---------------------------------------------------------------------------
# Contacts, appointments, availability
# ---------------------------------------------------------------------------


def test_contacts_list_sends_search_and_per_page():
    client, seen = stub([ok([{"id": "c1", "name": "Rahul", "phone": "+919845000001"}])])
    rows = client.contacts.list(search="Rahul", per_page=5)
    assert str(seen[0].url) == f"{BASE}/contacts?search=Rahul&per_page=5"
    assert rows[0]["id"] == "c1"


def test_a_test_key_contact_answer_names_underscore_id_and_the_client_hands_back_id():
    client, _ = stub([{"status": 201, "body": {"success": True, "data": {"_id": "test_contact_1", "name": "Rahul", "livemode": False}}}], api_key="mv_test_" + "a" * 32)
    contact = client.contacts.create(name="Rahul", phone="+919845000001")
    assert contact["id"] == "test_contact_1"
    assert "_id" not in contact


def test_contacts_update_and_delete_use_the_contact_path():
    client, seen = stub([ok({"id": "c1"}), {"status": 204}])
    client.contacts.update("c1", notes="VIP")
    client.contacts.delete("c1")
    assert (seen[0].method, sent_json(seen[0])) == ("PATCH", {"notes": "VIP"})
    assert (seen[1].method, str(seen[1].url)) == ("DELETE", f"{BASE}/contacts/c1")


def test_appointments_list_all_follows_the_cursor_until_it_is_none():
    client, seen = stub([ok({"items": [{"id": "a1"}, {"id": "a2"}], "cursor": "c-2"}), ok({"items": [{"id": "a3"}], "cursor": None})])
    ids = [a["id"] for a in client.appointments.list_all(agent_id="k17agent", per_page=2, from_=future_day(1))]
    assert ids == ["a1", "a2", "a3"]
    assert query(seen[0]) == {"agent_id": "k17agent", "per_page": "2", "from": future_day(1)}
    assert query(seen[1])["cursor"] == "c-2"


def test_appointments_create_cancel_and_reschedule_take_an_idempotency_key():
    client, seen = stub([ok({"id": "ap1"})])
    client.appointments.create(agent_id="a", customer_name="R", date=future_day(7), time="10:00", idempotency_key="book-000001")
    client.appointments.cancel("ap1", tell_customer=False, idempotency_key="cancel-00001")
    client.appointments.reschedule("ap1", date=future_day(8), time="11:00", idempotency_key="move-000001")
    assert [str(r.url).replace(BASE, "") for r in seen] == ["/appointments", "/appointments/ap1/cancel", "/appointments/ap1/reschedule"]
    assert [r.headers["Idempotency-Key"] for r in seen] == ["book-000001", "cancel-00001", "move-000001"]
    assert sent_json(seen[0]) == {"agentId": "a", "customerName": "R", "date": future_day(7), "time": "10:00"}
    assert sent_json(seen[1]) == {"tellCustomer": False}


def test_availability_get_maps_onto_agent_id_date_timezone():
    day = future_day(3)
    client, seen = stub([ok({"date": day, "timezone": "Asia/Kolkata", "slots": ["09:00"], "calendar": "google", "closed": False})])
    free = client.availability.get(agent_id="k17agent", date=day, timezone="Asia/Kolkata")
    assert str(seen[0].url) == f"{BASE}/availability?agent_id=k17agent&date={day}&timezone=Asia%2FKolkata"
    assert free["slots"] == ["09:00"]


# ---------------------------------------------------------------------------
# The package itself
# ---------------------------------------------------------------------------


def test_the_user_agent_names_the_package_and_the_version_in_pyproject():
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    assert re.search(r'^name = "movoice"$', pyproject, re.M)
    assert movoice.__version__ == "0.1.1"
    client, seen = stub([ok([])])
    client.agents.list()
    assert seen[0].headers["User-Agent"] == f"movoice-python/{movoice.__version__}"


def test_the_package_ships_py_typed():
    assert (Path(movoice.__file__).parent / "py.typed").is_file()


def test_the_client_is_a_context_manager_and_does_not_close_a_client_it_was_given():
    given = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"success": True, "data": []})))
    with Movoice(KEY, http_client=given) as client:
        client.agents.list()
    assert not given.is_closed
    owned = Movoice(KEY)
    owned.close()
    assert owned.http._client.is_closed


@pytest.mark.parametrize(
    "key",
    ["   ", "mv_pk_" + "b" * 32],
    ids=["no key", "publishable key"],
)
def test_key_errors_point_at_the_real_developer_page(monkeypatch, key):
    monkeypatch.delenv("MOVOICE_API_KEY", raising=False)
    with pytest.raises(MovoiceError) as caught:
        Movoice(key)
    assert "https://app.movoice.ai/admin/developer" in str(caught.value)
