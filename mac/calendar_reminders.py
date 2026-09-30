#!/usr/bin/env python3
"""Write configurable routine reminders to an ICS file; never change the OS."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def clock_time(value: str) -> time | None:
    if value.lower() == "none":
        return None
    try:
        result = time.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use HH:MM (or none for wake/winddown)") from exc
    if result.tzinfo is not None or result.second or result.microsecond:
        raise argparse.ArgumentTypeError("Use local HH:MM without seconds or an offset")
    return result


def escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold(value: str) -> str:
    """Fold at 75 UTF-8 octets without breaking a Unicode character (RFC 5545)."""
    lines, line, length = [], "", 0
    for char in value:
        size = len(char.encode("utf-8"))
        if length + size > 75:
            lines.append(line)
            line, length = " ", 1
        line += char
        length += size
    lines.append(line)
    return "\r\n".join(lines)


def utc_stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_calendar(*, start_date: date, days: int = 7, timezone_name: str = "Asia/Tokyo",
                   wake: time | None = time(7), move_start: time = time(9), move_end: time = time(18),
                   move_every: int = 60, winddown: time | None = time(21, 30),
                   alarm_minutes: int | None = None, generated_at: datetime | None = None) -> tuple[str, int]:
    zone = ZoneInfo(timezone_name)
    if not 1 <= days <= 366:
        raise ValueError("days must be from 1 to 366")
    if move_every != 0 and not 5 <= move_every <= 1440:
        raise ValueError("move-every must be 0 (disabled) or 5–1440 minutes")
    if move_every and move_start >= move_end:
        raise ValueError("move-start must precede move-end on the same day")
    if alarm_minutes is not None and not 0 <= alarm_minutes <= 1440:
        raise ValueError("alarm-minutes must be from 0 to 1440")
    for value in (wake, move_start, move_end, winddown):
        if value is not None and value.tzinfo is not None:
            raise ValueError("Schedule times must be local, without a timezone offset")
    stamp = utc_stamp(generated_at or datetime.now(timezone.utc))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Health Lab//Mac Health Toolkit//JA", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:ヘルスラボの日々のリズム", f"X-WR-TIMEZONE:{escape(timezone_name)}"]
    count = 0
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        slots = []
        if wake is not None:
            slots.append(("wake", wake, 10, "朝のリズムを整える", "起床時刻を確認。今日の予定と体調に合わせて朝を始める。"))
        if move_every:
            cursor = datetime.combine(day, move_start)
            end = datetime.combine(day, move_end)
            while cursor < end:
                slots.append(("move", cursor.time(), 5, "少し動く・姿勢を変える", "休憩して姿勢を変える。短い歩行やストレッチは無理のない範囲で。"))
                cursor += timedelta(minutes=move_every)
        if winddown is not None:
            slots.append(("winddown", winddown, 20, "夜の時間をゆるめる", "照明と画面の明るさを見直し、就寝前の過ごし方を選ぶ。"))
        for kind, when, duration, title, description in sorted(slots, key=lambda slot: (slot[1], slot[0])):
            start = datetime.combine(day, when, zone)
            # Round-trip catches a wall time that does not exist during a DST change.
            if start.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != start.replace(tzinfo=None):
                raise ValueError(f"{start.isoformat()} is a nonexistent local time; choose another time")
            finish = start.astimezone(timezone.utc) + timedelta(minutes=duration)
            identity = f"health-lab|{timezone_name}|{day.isoformat()}|{when.isoformat()}|{kind}"
            uid = hashlib.sha256(identity.encode()).hexdigest()[:32] + "@health-lab.toriumis.com"
            lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"DTSTART:{utc_stamp(start)}", f"DTEND:{utc_stamp(finish)}",
                      f"SUMMARY:{escape(title)}", f"DESCRIPTION:{escape(description + ' 設定した時間帯: ' + timezone_name)}",
                      "URL:https://toriumis.com/health-lab/", "TRANSP:TRANSPARENT"]
            if alarm_minutes is not None:
                lines += ["BEGIN:VALARM", f"TRIGGER:-PT{alarm_minutes}M", "ACTION:DISPLAY", f"DESCRIPTION:{escape(title)}", "END:VALARM"]
            lines.append("END:VEVENT")
            count += 1
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n", count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("health-lab-reminders.ics"))
    parser.add_argument("--start-date", type=date.fromisoformat, help="YYYY-MM-DD; defaults to today in the selected timezone")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--timezone", default="Asia/Tokyo")
    parser.add_argument("--wake", type=clock_time, default=time(7), help="HH:MM or none; default 07:00")
    parser.add_argument("--move-start", type=clock_time, default=time(9))
    parser.add_argument("--move-end", type=clock_time, default=time(18))
    parser.add_argument("--move-every", type=int, default=60, help="Minutes; 0 disables movement reminders")
    parser.add_argument("--winddown", type=clock_time, default=time(21, 30), help="HH:MM or none; default 21:30")
    parser.add_argument("--alarm-minutes", type=int, default=None, help="Optional notification this many minutes before; omitted = no VALARM")
    args = parser.parse_args()
    try:
        zone = ZoneInfo(args.timezone)
        if args.move_start is None or args.move_end is None:
            raise ValueError("move-start and move-end require HH:MM")
        calendar, count = build_calendar(start_date=args.start_date or datetime.now(zone).date(), days=args.days,
                                        timezone_name=args.timezone, wake=args.wake, move_start=args.move_start,
                                        move_end=args.move_end, move_every=args.move_every, winddown=args.winddown,
                                        alarm_minutes=args.alarm_minutes)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(calendar.encode("utf-8"))
    except (OSError, ValueError, ZoneInfoNotFoundError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(f"Wrote {count} events to {args.output}. No calendar was imported or OS setting changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
