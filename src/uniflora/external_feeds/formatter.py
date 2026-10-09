from __future__ import annotations

from .models import AprsEvent


def render_bbs_event(
    event: AprsEvent,
    *,
    field_name: str = "DEIR EL-MEDINA EXTERIOR FIELD",
) -> str:
    timestamp = event.occurred_at.strftime("%Y-%m-%d %H:%M:%SZ")
    event_label = event.event_type.replace("_", " ").upper()

    return (
        "```text\n"
        f"{field_name}\n"
        f"{event_label} // {timestamp}\n"
        "────────────────────────────────\n"
        f"{event.body}\n"
        "```\n"
        "*external observation only — settlement state unchanged*"
    )
