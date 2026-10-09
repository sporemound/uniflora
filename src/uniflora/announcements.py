from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ScheduledAnnouncement:
    announcement_id: str
    channel_name: str
    send_at: datetime
    expires_at: datetime
    text: str


SCHEDULED_ANNOUNCEMENTS: tuple[ScheduledAnnouncement, ...] = ()
