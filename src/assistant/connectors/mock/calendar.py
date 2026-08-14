"""Mock Google Calendar connector (spec §11.2).

Also exposes `is_out_of_office`, which can back the Permission Engine's AbsenceProvider
in M5 (out-of-office is a lower-sensitivity availability signal).
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from assistant.connectors.base import (
    BaseConnector,
    Capability,
    PermissionContext,
    WriteResult,
)
from assistant.domain.enums import ActionType, System

# Seeded out-of-office window for Anna (spec flagship: she is on vacation).
_OOO: dict[str, tuple[date, date]] = {
    "anna": (date(2026, 8, 10), date(2026, 8, 24)),
}


class MockCalendarConnector(BaseConnector):
    system: ClassVar[System] = System.CALENDAR

    def manifest(self) -> list[Capability]:
        return [
            Capability(system=self.system, action="get_user_calendar", access=ActionType.READ),
            Capability(system=self.system, action="detect_out_of_office", access=ActionType.READ),
            Capability(system=self.system, action="create_event", access=ActionType.WRITE),
        ]

    def is_out_of_office(self, user_id: str, on: date | None = None) -> bool:
        """Availability signal — usable without a PermissionContext (non-sensitive)."""
        window = _OOO.get(user_id)
        if window is None:
            return False
        day = on or date.today()
        return window[0] <= day <= window[1]

    def detect_out_of_office(self, ctx: PermissionContext, on: date | None = None) -> bool:
        self._guard(ctx, "detect_out_of_office", ActionType.READ)
        target = ctx.target_user or ctx.active_user
        return self.is_out_of_office(target, on)

    def create_calendar_event_as_active_user(
        self, ctx: PermissionContext, title: str, start_time: str, end_time: str
    ) -> WriteResult:
        conn = self._guard(ctx, "create_event", ActionType.WRITE)
        return WriteResult(
            system=self.system, action="create_event", actor=conn.user_id, detail=title
        )
