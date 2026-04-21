from __future__ import annotations

from datetime import datetime

from porcaria.pipeline.context import date_context


def test_header_and_today_line_present():
    ctx = date_context(datetime(2026, 4, 20, 14, 30))
    lines = ctx.splitlines()
    assert lines[0] == "## CURRENT DATE/TIME CONTEXT"
    assert any("Today: Monday, April 20, 2026" in line for line in lines)


def test_marks_today_and_tomorrow():
    ctx = date_context(datetime(2026, 4, 20, 9, 0))
    assert "← today" in ctx
    assert "← tomorrow" in ctx


def test_includes_three_weeks():
    ctx = date_context(datetime(2026, 4, 20, 9, 0))
    assert "This week" in ctx
    assert "Next week" in ctx
    assert "Week of" in ctx


def test_days_before_today_skipped_in_current_week():
    # Friday: Mon-Thu should not appear as enumerated day lines (two-space indent).
    ctx = date_context(datetime(2026, 4, 24, 9, 0))
    current_week, _, _ = ctx.partition("Next week")
    day_lines = [line for line in current_week.splitlines() if line.startswith("  ")]
    assert not any("Mon Apr 20" in l for l in day_lines)
    assert not any("Thu Apr 23" in l for l in day_lines)
    assert any("Fri Apr 24" in l for l in day_lines)
