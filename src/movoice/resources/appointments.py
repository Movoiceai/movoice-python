"""Appointments and availability: the bookings on your agents' calendars."""

from __future__ import annotations

from typing import Iterator, Optional, Set, cast

from ..types import (
    Appointment,
    AppointmentPage,
    Availability,
    CancelledAppointment,
    CreatedAppointment,
    RescheduledAppointment,
)
from ._base import Resource, compact, segment


class Appointments(Resource):
    def list(
        self,
        *,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        cursor: Optional[str] = None,
        per_page: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> AppointmentPage:
        """One page of bookings, ordered by day and time.

        ``from_`` and ``to`` are YYYY-MM-DD, inclusive (``from_`` has a trailing underscore
        because ``from`` is a Python keyword). Pass the page's ``cursor`` back for the next one;
        it is ``None`` on the last page.
        """
        query = {
            "status": status,
            "agent_id": agent_id,
            "from": from_,
            "to": to,
            "cursor": cursor,
            "per_page": per_page,
        }
        return cast(AppointmentPage, self._http.request("GET", "/appointments", query=query, timeout=timeout))

    def list_all(
        self,
        *,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        cursor: Optional[str] = None,
        per_page: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> Iterator[Appointment]:
        """Every matching booking, following the cursor. Stops fetching as soon as you break out."""
        seen: Set[str] = set()
        while True:
            page = self.list(
                status=status,
                agent_id=agent_id,
                from_=from_,
                to=to,
                cursor=cursor,
                per_page=per_page,
                timeout=timeout,
            )
            yield from page.get("items") or []
            nxt = page.get("cursor")
            # A cursor the server hands back twice would loop forever; stop instead.
            if not nxt or nxt in seen:
                return
            seen.add(nxt)
            cursor = nxt

    def get(self, appointment_id: str, *, timeout: Optional[float] = None) -> Appointment:
        """One booking. Raises ``NotFoundError`` if it is not on your account."""
        return cast(
            Appointment, self._http.request("GET", f"/appointments/{segment(appointment_id)}", timeout=timeout)
        )

    def create(
        self,
        *,
        agent_id: str,
        customer_name: str,
        date: str,
        time: str,
        timezone: Optional[str] = None,
        customer_phone: Optional[str] = None,
        customer_email: Optional[str] = None,
        service_type: Optional[str] = None,
        notes: Optional[str] = None,
        confirmation: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CreatedAppointment:
        """Book a time on an agent's calendar.

        ``confirmation`` is "sms", "whatsapp", "email" or "none". A time that was just taken
        raises ``ConflictError`` whose message lists the free times that day.
        """
        body = compact(
            agentId=agent_id,
            customerName=customer_name,
            date=date,
            time=time,
            timezone=timezone,
            customerPhone=customer_phone,
            customerEmail=customer_email,
            serviceType=service_type,
            notes=notes,
            confirmation=confirmation,
        )
        return cast(
            CreatedAppointment,
            self._http.request(
                "POST",
                "/appointments",
                body=body,
                idempotency_key=idempotency_key,
                accepts_idempotency_key=True,
                timeout=timeout,
            ),
        )

    def cancel(
        self,
        appointment_id: str,
        *,
        tell_customer: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CancelledAppointment:
        """Cancel a booking. The customer is told unless ``tell_customer=False``."""
        return cast(
            CancelledAppointment,
            self._http.request(
                "POST",
                f"/appointments/{segment(appointment_id)}/cancel",
                body=compact(tellCustomer=tell_customer),
                idempotency_key=idempotency_key,
                accepts_idempotency_key=True,
                timeout=timeout,
            ),
        )

    def reschedule(
        self,
        appointment_id: str,
        *,
        date: str,
        time: str,
        tell_customer: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> RescheduledAppointment:
        """Move a booking to a new day and time. The customer is told unless ``tell_customer=False``."""
        return cast(
            RescheduledAppointment,
            self._http.request(
                "POST",
                f"/appointments/{segment(appointment_id)}/reschedule",
                body=compact(date=date, time=time, tellCustomer=tell_customer),
                idempotency_key=idempotency_key,
                accepts_idempotency_key=True,
                timeout=timeout,
            ),
        )


class AvailabilityResource(Resource):
    def get(
        self,
        *,
        agent_id: str,
        date: str,
        timezone: Optional[str] = None,
        service: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Availability:
        """The free times on one day of an agent's calendar::

            slots = client.availability.get(agent_id=agent_id, date="2026-12-01")["slots"]
        """
        query = {"agent_id": agent_id, "date": date, "timezone": timezone, "service": service}
        return cast(Availability, self._http.request("GET", "/availability", query=query, timeout=timeout))
