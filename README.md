# movoice

The official Python client for the [Movoice AI](https://movoice.ai) API: voice agents, calls,
contacts, bookings, SMS, WhatsApp, and webhook verification.

Python 3.9+. One dependency ([httpx](https://www.python-httpx.org)). Fully typed.

```bash
pip install movoice
```

> **Rolling out:** the call-result fields `id`, `context_data` and `agent`, and giving an agent a phone number with `agents.update(agent_id, phone_number=...)`, are live on Movoice's testing server and reach app.movoice.ai with the next Movoice release.

## Call a lead from your CRM and get the result back

```python
import os
from movoice import Movoice

client = Movoice()  # reads MOVOICE_API_KEY

# 1. Your CRM says "call this lead". context_data fills {name} in the agent's prompt and comes back on every event.
call = client.calls.create(
    agent_id=os.environ["MOVOICE_AGENT_ID"],
    phone_number="+14155550123",
    context_data={"leadId": "L-889", "name": "Rahul"},
    idempotency_key="call-L-889-1",  # retry safely: the same key never dials twice
)
crm.save_call_id("L-889", call["id"])
```

```python
# 2. Movoice posts call.completed to your webhook. Verify it, then match it back to the lead. (FastAPI)
import os
import movoice
from fastapi import FastAPI, Request, Response

app = FastAPI()

@app.post("/movoice-webhook")
async def movoice_webhook(request: Request):
    try:
        event = movoice.webhooks.verify(await request.body(), request.headers, os.environ["MOVOICE_WEBHOOK_SECRET"])
    except movoice.WebhookVerificationError:
        return Response(status_code=400)
    if event["event"] == "call.completed":
        crm.log_call(event.get("context_data", {}).get("leadId"), event.get("summary"), event.get("duration_seconds"))
    return Response(status_code=200)
```

The same receiver in Flask:

```python
from flask import Flask, request

app = Flask(__name__)

@app.post("/movoice-webhook")
def movoice_webhook():
    try:
        event = movoice.webhooks.verify(request.get_data(), request.headers, os.environ["MOVOICE_WEBHOOK_SECRET"])
    except movoice.WebhookVerificationError:
        return "", 400
    ...
    return "", 200
```

`call["id"]` is the call's Movoice id. Every webhook for that call carries it as `id`, plus the
`context_data` you sent and the agent as `agent["id"]`, so either one leads back to the record in
your CRM. `client.calls.get(call["id"])` reads the call (status, duration, `summary`, transcript)
whenever you want it instead.

Responses are plain `dict`s with the API's own keys (`call["movoiceWebSocketCallId"]`,
`agent["welcomeMessage"]`); `movoice.types` has `TypedDict`s describing each one for your editor.
Arguments are Python keyword arguments (`agent_id=`, `phone_number=`, `context_data=`).

## Test keys and live keys

Create keys on the Developer page: https://app.movoice.ai/admin/developer

| Key | What it does |
| --- | --- |
| `mv_live_...` | The real thing. Calls dial and are charged; writes change your account. |
| `mv_test_...` | A sandbox. `calls.create` places a pretend call (`id` starts with `test_call_`, `livemode: False`) that dials nobody and costs nothing, and your webhook endpoints receive pretend `call.started` and `call.completed` events for it, carrying your `context_data`. Reads return sample data; writes answer with `livemode: False` and change nothing. |
| `mv_pk_...` | Publishable, for the chat widget in a browser. It cannot call this API, and the client refuses it at construction. |

Build and test the whole loop with a test key, then swap in the live key.

```python
client = Movoice()                                  # MOVOICE_API_KEY from the environment
client = Movoice("mv_test_...")                     # or pass it
client = Movoice(base_url="https://testing.movoice.ai", timeout=10, max_retries=0)
```

Keep your key on your server: a secret key can place calls and spend your balance.

## Errors

Every failure raises. One class hierarchy, whatever shape the API replied with:

```python
import movoice

try:
    client.calls.create(agent_id=agent_id, phone_number=phone)
except movoice.InsufficientBalanceError:
    top_up_wallet()
except movoice.RateLimitError as err:
    retry_later(err.retry_after)
except movoice.MovoiceError as err:
    print(err.code, err.message, err.status)
```

| Class | When |
| --- | --- |
| `AuthenticationError` | 401: key missing, expired, or unknown |
| `PermissionError` | 403: key lacks the scope. `err.required_scopes` lists what it needed |
| `InvalidRequestError` | 400 / 422. `err.field_errors` has per-field messages |
| `NotFoundError` | 404: also returned for another account's ids |
| `ConflictError` | 409: conflicts with the current state |
| `InsufficientBalanceError` | 402: plan allowance and wallet both empty |
| `RateLimitError` | 429. `err.retry_after` in seconds, when the API sent one |
| `ApiError` | 5xx |
| `ConnectionError` | never reached the server, or timed out (`err.code == "TIMEOUT"`) |

`movoice.PermissionError` and `movoice.ConnectionError` share their names with Python built-ins,
like the other Movoice clients; use them through the package (`movoice.PermissionError`), or catch
`movoice.MovoiceError` for everything. `err.code` is normalised to upper case; the API's own value
is on `err.raw_code`, and the parsed body on `err.body`.

## Retries and idempotency

Retried automatically: `429` on any method, and `5xx` or network faults **on GET**.

A `POST` or `PATCH` that failed with a `5xx` or timed out is **not** retried on its own: a `500`
does not tell you whether the work happened first, and retrying `calls.create` would place a
second call and bill you twice.

Unless you give it an idempotency key. `calls.create`, `agents.create`, `agents.update`,
`appointments.create`, `appointments.cancel` and `appointments.reschedule` take
`idempotency_key=`, sent as the `Idempotency-Key` header. The server keeps the first answer under
that key and hands it back for any repeat instead of acting again, so with a key the client does
retry a timeout or a `5xx`, and so can you. Use one key per thing you mean to happen once; reusing
a key with a different body is refused (`422`), and a repeat that arrives while the first is still
running gets `ConflictError` (`409`). Keys are 8 to 255 characters. Methods that do not accept a
key do not take the argument at all.

Tune with `Movoice(max_retries=0)`, or `timeout=` (seconds, default 30) per client or per call.

## Webhooks

Add an endpoint on the Developer page and copy its signing secret (it starts with `whsec_`).
Every delivery is signed:

```
X-Movoice-Timestamp: <unix seconds>
X-Movoice-Signature: sha256=<hex HMAC-SHA256 of "<timestamp>.<raw body>", keyed with the whole whsec_ secret>
X-Movoice-Event:     call.completed
X-Movoice-Delivery:  <event_id>
```

`movoice.webhooks.verify(raw_body, headers, secret, tolerance=300)` checks the signature
(constant-time, `hmac.compare_digest`) and that the timestamp is within 5 minutes of now, then
returns the parsed event. Anything else raises `WebhookVerificationError`
(`code == "WEBHOOK_SIGNATURE_INVALID"`): answer it with a 400.

Pass the body **exactly as it arrived** (`str` or `bytes`: Flask `request.get_data()`,
FastAPI/Starlette `await request.body()`, Django `request.body`), never parsed JSON. `headers` may
be a dict or any headers object; names are matched case-insensitively. It needs no API key;
`client.webhooks.verify` is the same function. Events: `call.started`, `call.completed`,
`call.failed`, `call.missed`. Answer quickly with a 2xx: a failed delivery is retried with the same
`event_id`, so drop duplicates by it.

## Paging

```python
page = client.calls.list(per_page=50, agent_id=agent_id)
page.data       # list of calls
page.has_more
page.total      # may be None: the set can be too large to count
nxt = page.next()   # Page or None

for call in client.calls.list_all(agent_id=agent_id):   # every page, fetched as you go
    print(call["id"], call["status"])
```

`next()` follows a cursor where the endpoint offers one (`/calls`) and increments the page number
where it does not, so the same loop is correct everywhere.

## Hang up a call

```python
client.calls.hangup(call["id"])   # the network is asked to end it; call.completed follows
```

## Give an agent a phone number

```python
client.agents.update(agent_id, phone_number="+14155550123")  # or the number's id from numbers.list()
```

The agent then answers that number, as when you pick it in the dashboard. A number not on your
account raises `NotFoundError`; one another agent answers raises `ConflictError`.

## Contacts

```python
existing = client.contacts.list(search="+14155550123")
contact = existing[0] if existing else client.contacts.create(name="Rahul", phone="+14155550123", tags=["crm"])
client.contacts.update(contact["id"], notes="Wants a callback on Thursday")
client.contacts.delete(contact["id"])
```

`list` returns up to `per_page` (max 100) contacts, newest first, with no paging: narrow it with
`search`. A second contact with the same phone raises `ConflictError`.

## Appointments and availability

```python
slots = client.availability.get(agent_id=agent_id, date="2026-12-01", timezone="Asia/Kolkata")["slots"]
booking = client.appointments.create(
    agent_id=agent_id, customer_name="Rahul", customer_phone="+919845000001",
    date="2026-12-01", time=slots[0], idempotency_key="book-L-889",
)
client.appointments.reschedule(booking["id"], date="2026-12-02", time="11:00")
client.appointments.cancel(booking["id"], tell_customer=True)

for a in client.appointments.list_all(from_="2026-12-01", to="2026-12-31"):
    print(a["date"], a["time"])
```

`from_` has a trailing underscore because `from` is a Python keyword.

## Sending messages

```python
client.messages.send(to="+14155550123", body="Your appointment is confirmed.")
client.messages.send_whatsapp(to="+14155550123", body="Your appointment is confirmed.")
```

Both spend your balance and are capped at 500 messages per key per 24 hours. The response field
`status` is always `"sent"`; the honest signal is `providerMessageId`, and the client raises
(`code == "NOT_SENT"`) when a nominally successful response carries none. A recipient who replied
STOP is suppressed on every channel and raises `InvalidRequestError`.

## Caller memory and your account

```python
memory = client.memory.recall(agent_id=agent_id, phone="+14155550123")
if memory["found"]:
    print(memory["data"]["total_calls"], memory["data"]["facts"])
else:
    print(memory["message"])   # no memory yet, memory switched off, or unknown caller

account = client.account.get()
account["accountNumber"]           # your Movoice Account ID: quote it to support
account["creditBalanceUsdCents"]   # US cents, whatever currency you pay in
```

## Conventions

- Every timestamp is **epoch milliseconds**; a call's `duration` is **seconds**.
- An agent's `bolnaAgentId` key is its engine id inside the Movoice WebSocket voice engine (the key
  name the API has always sent); use `id` everywhere else.
- `client.http.request("GET", "/some/new/endpoint")` reaches anything this version does not wrap
  yet, with the same auth, retries and errors. Paths are relative to `/api/v1`.

## Reference

Docs: https://docs.movoice.ai. The machine-readable spec lives at
[`/api/v1/openapi.json`](https://app.movoice.ai/api/v1/openapi.json).

## Licence

MIT
