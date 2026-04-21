"""Build a human-readable date/time context block for LLM prompts.

Ports the bash `generate_date_context` function: emits today / tomorrow / three
weeks of days with ← today / ← tomorrow markers. Pure function, no I/O.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


def date_context(now: datetime | None = None) -> str:
    now = now or datetime.now()
    today = now.date()
    tomorrow = today + timedelta(days=1)

    today_dow = today.strftime("%A")
    today_date = today.strftime("%B %d, %Y")
    today_time = now.strftime("%-I:%M %p").lower()
    tomorrow_label = tomorrow.strftime("%a %b %d")

    lines: list[str] = [
        "## CURRENT DATE/TIME CONTEXT",
        "",
        f"Today: {today_dow}, {today_date} ({today_time})",
        f"Tomorrow: {tomorrow_label}",
        "",
    ]

    # Monday of the current calendar week.
    monday = today - timedelta(days=today.weekday())

    for week_idx in range(3):
        week_mon = monday + timedelta(days=week_idx * 7)
        week_sun = week_mon + timedelta(days=6)
        range_label = f"{week_mon.strftime('%a %b %d')} – {week_sun.strftime('%a %b %d')}"
        if week_idx == 0:
            lines.append(f"This week ({range_label}):")
        elif week_idx == 1:
            lines.append(f"Next week ({range_label}):")
        else:
            lines.append(f"Week of {week_mon.strftime('%b %d')} ({range_label}):")

        for day_offset in range(7):
            day = week_mon + timedelta(days=day_offset)
            if week_idx == 0 and day < today:
                continue
            marker = ""
            if day == today:
                marker = " ← today"
            elif day == tomorrow:
                marker = " ← tomorrow"
            lines.append(f"  {day.strftime('%a %b %d')}{marker}")
        lines.append("")

    return "\n".join(lines)
