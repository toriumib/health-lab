#!/usr/bin/env python3
"""Stream an Apple Health export into daily, source-aware CSV (stdlib only)."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, time, timedelta, timezone
from itertools import groupby
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


METRICS = ("sleep_hours", "steps", "exercise_min", "resting_hr", "weight_kg", "hrv_ms")
TYPE_METRICS = {
    "HKCategoryTypeIdentifierSleepAnalysis": "sleep_hours",
    "HKQuantityTypeIdentifierStepCount": "steps",
    "HKQuantityTypeIdentifierAppleExerciseTime": "exercise_min",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_hr",
    "HKQuantityTypeIdentifierBodyMass": "weight_kg",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv_ms",
}
ASLEEP = {
    "HKCategoryValueSleepAnalysisAsleep", "HKCategoryValueSleepAnalysisAsleepUnspecified",
    "HKCategoryValueSleepAnalysisAsleepCore", "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
}
UNIT_FACTORS = {
    "steps": {"count": 1},
    "exercise_min": {"min": 1, "s": 1 / 60, "hr": 60, "h": 60},
    "resting_hr": {"count/min": 1, "bpm": 1},
    "weight_kg": {"kg": 1, "g": .001, "lb": .45359237, "lbs": .45359237, "oz": .028349523125},
    "hrv_ms": {"ms": 1, "s": 1000},
}
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone offset")
    return result.astimezone(timezone.utc)


def micros(value: datetime) -> int:
    delta = value.astimezone(timezone.utc) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def date_segments(start: datetime, end: datetime, zone: ZoneInfo):
    """Yield UTC interval segments at local midnight, respecting offset changes."""
    if end < start:
        raise ValueError("End precedes start")
    if end == start:
        yield start.astimezone(zone).date().isoformat(), start, end
        return
    cursor = start
    while cursor < end:
        local_day = cursor.astimezone(zone).date()
        boundary = datetime.combine(local_day + timedelta(days=1), time(), zone).astimezone(timezone.utc)
        # ZoneInfo can represent a historical date with a skipped midnight.
        if boundary <= cursor:
            boundary = cursor + timedelta(hours=1)
        stop = min(end, boundary)
        yield local_day.isoformat(), cursor, stop
        cursor = stop


def make_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("""CREATE TABLE samples (
        day TEXT NOT NULL, metric TEXT NOT NULL, source TEXT NOT NULL,
        start_us INTEGER NOT NULL, end_us INTEGER NOT NULL, value REAL NOT NULL,
        PRIMARY KEY(day, metric, source, start_us, end_us, value)
    ) WITHOUT ROWID""")
    return conn


def read_records(xml_path: Path, conn: sqlite3.Connection, zone: ZoneInfo) -> dict[str, int]:
    stats = {"records": 0, "imported": 0, "duplicates": 0, "ignored": 0, "invalid": 0}
    context = ET.iterparse(xml_path, events=("start", "end"))
    _, root = next(context)
    for event, elem in context:
        if event != "end":
            continue
        if elem.tag == "Record":
            stats["records"] += 1
            attrs = elem.attrib
            metric = TYPE_METRICS.get(attrs.get("type", ""))
            if metric is None or (metric == "sleep_hours" and attrs.get("value") not in ASLEEP):
                stats["ignored"] += 1
            else:
                try:
                    start = timestamp(attrs["startDate"])
                    end = timestamp(attrs["endDate"])
                    if end < start:
                        raise ValueError("End precedes start")
                    source = attrs.get("sourceName") or "(unknown)"
                    if metric == "sleep_hours":
                        if end == start:
                            raise ValueError("Sleep interval is empty")
                        value = 0.0
                    else:
                        factor = UNIT_FACTORS[metric][attrs["unit"]]
                        value = float(attrs["value"]) * factor
                        if not math.isfinite(value) or value < 0:
                            raise ValueError("Value must be finite and nonnegative")
                    total_seconds = (end - start).total_seconds()
                    # Round the original count once, then allocate cumulative
                    # elapsed-time shares. Every day gets integer steps and the
                    # parts sum to the rounded original, including midnight ties.
                    total_steps = math.floor(value + .5) if metric == "steps" else 0
                    allocated_steps, elapsed_seconds = 0, 0.0
                    if metric in ("sleep_hours", "steps", "exercise_min"):
                        parts = date_segments(start, end, zone)
                    else:
                        parts = [(end.astimezone(zone).date().isoformat(), start, end)]
                    added = 0
                    for day, part_start, part_end in parts:
                        part_value = value
                        if metric == "steps":
                            elapsed_seconds += (part_end - part_start).total_seconds()
                            cumulative_steps = (total_steps if part_end == end or total_seconds == 0 else
                                                math.floor(total_steps * elapsed_seconds / total_seconds + .5))
                            part_value = float(cumulative_steps - allocated_steps)
                            allocated_steps = cumulative_steps
                        elif metric == "exercise_min" and total_seconds > 0:
                            part_value *= (part_end - part_start).total_seconds() / total_seconds
                        cursor = conn.execute("INSERT OR IGNORE INTO samples VALUES (?, ?, ?, ?, ?, ?)",
                                              (day, metric, source, micros(part_start), micros(part_end), part_value))
                        added += cursor.rowcount
                    stats["imported" if added else "duplicates"] += 1
                except (KeyError, ValueError, OverflowError):
                    stats["invalid"] += 1
            elem.clear()
            root.clear()
        elif elem.tag in {"Workout", "ActivitySummary", "Correlation", "ClinicalRecord"}:
            elem.clear()
            root.clear()
        if stats["records"] and stats["records"] % 10_000 == 0 and elem.tag == "Record":
            conn.commit()
    conn.commit()
    return stats


def union_seconds(intervals) -> float:
    start = end = None
    total = 0
    for next_start, next_end in intervals:
        if start is None:
            start, end = next_start, next_end
        elif next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    if start is not None:
        total += end - start
    return total / 1_000_000


def aggregate(conn: sqlite3.Connection, day: str, metric: str, source: str) -> float:
    args = (day, metric, source)
    where = "WHERE day=? AND metric=? AND source=?"
    if metric == "sleep_hours":
        intervals = conn.execute(f"SELECT start_us, end_us FROM samples {where} ORDER BY start_us, end_us", args)
        return union_seconds(intervals) / 3600
    if metric == "weight_kg":
        # A numerical tie-break makes conflicting measurements at the same instant reproducible.
        return conn.execute(f"SELECT value FROM samples {where} ORDER BY end_us DESC, start_us DESC, value ASC LIMIT 1", args).fetchone()[0]
    operation = "SUM" if metric in ("steps", "exercise_min") else "AVG"
    return conn.execute(f"SELECT {operation}(value) FROM samples {where}", args).fetchone()[0]


def number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def safe_csv_text(value: str) -> str:
    """Prevent source names from becoming formulas in spreadsheet applications."""
    stripped = value.lstrip()
    if value.startswith(("\t", "\r", "\n")) or stripped.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_csv(conn: sqlite3.Connection, output: Path, sources: Path, overrides: dict[str, str], timezone_name: str) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    sources.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as out, sources.open("w", encoding="utf-8", newline="") as provenance:
        writer, source_writer = csv.writer(out), csv.writer(provenance)
        writer.writerow(("date", *METRICS, "note"))
        source_writer.writerow(("date", "metric", "source", "unique_records", "selection"))
        candidates = conn.execute("""SELECT day, metric, source, COUNT(*) FROM samples
            GROUP BY day, metric, source ORDER BY day, metric, COUNT(*) DESC, source COLLATE BINARY ASC""")
        count = 0
        for day, day_rows in groupby(candidates, key=lambda row: row[0]):
            values, selected_sources = {}, {}
            for metric, metric_rows in groupby(day_rows, key=lambda row: row[1]):
                candidates_for_metric = list(metric_rows)
                preferred = overrides.get(metric)
                selected = next((row for row in candidates_for_metric if preferred is None or row[2] == preferred), None)
                if selected is None:
                    continue
                _, _, source, sample_count = selected
                values[metric] = number(aggregate(conn, day, metric, source))
                selected_sources[metric] = source.replace("\r", " ").replace("\n", " ")
                source_writer.writerow((day, metric, safe_csv_text(source), sample_count, "requested" if preferred else "most_unique_records_then_source_name"))
            source_note = "; ".join(f"{metric}={selected_sources[metric]}" for metric in METRICS if metric in selected_sources)
            note = (f"採用ソース: {source_note or 'なし'} | 日付: {timezone_name} 0時区切り（睡眠も分割） | "
                    "HRV: SDNN(ms) | 歩数: 時間比で整数配分")
            writer.writerow((day, *(values.get(metric, "") for metric in METRICS), note))
            count += 1
    return count


def import_health(xml_path: Path, output: Path, *, timezone_name: str = "Asia/Tokyo", sources: Path | None = None,
                  overrides: dict[str, str] | None = None, temp_directory: Path | None = None) -> dict[str, int]:
    zone = ZoneInfo(timezone_name)
    xml_path, output = xml_path.resolve(), output.resolve()
    sources = (sources or output.with_name(output.stem + ".sources.csv")).resolve()
    if len({xml_path, output, sources}) != 3:
        raise ValueError("Input, daily CSV, and source CSV must be different files")
    overrides = overrides or {}
    if any(metric not in METRICS or not source for metric, source in overrides.items()):
        raise ValueError("Invalid source override")
    with tempfile.TemporaryDirectory(prefix="health-lab-", dir=temp_directory) as folder:
        conn = make_database(Path(folder) / "samples.sqlite")
        try:
            stats = read_records(xml_path, conn, zone)
            stats["days"] = write_csv(conn, output, sources, overrides, timezone_name)
        finally:
            conn.close()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml", type=Path, help="Unzipped Apple Health export.xml")
    parser.add_argument("--output", type=Path, default=Path("health-daily.csv"))
    parser.add_argument("--sources-output", type=Path, help="Defaults to <output stem>.sources.csv")
    parser.add_argument("--timezone", default="Asia/Tokyo", help="IANA timezone for daily boundaries")
    parser.add_argument("--source", action="append", default=[], metavar="METRIC=SOURCE", help="Select this source for a metric; repeat as needed")
    parser.add_argument("--temp-directory", type=Path, help="Directory for a temporary local SQLite database")
    args = parser.parse_args()
    try:
        overrides = {}
        for item in args.source:
            metric, source = item.split("=", 1)
            if metric not in METRICS or not source:
                raise ValueError(f"Source override must be one of {', '.join(METRICS)} followed by =SOURCE")
            overrides[metric] = source
        stats = import_health(args.xml, args.output, timezone_name=args.timezone, sources=args.sources_output,
                              overrides=overrides, temp_directory=args.temp_directory)
    except (OSError, ET.ParseError, ValueError, ZoneInfoNotFoundError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(f"Wrote {stats['days']} daily rows to {args.output}; source choices are in {args.sources_output or args.output.with_name(args.output.stem + '.sources.csv')}.")
    print("Records: " + ", ".join(f"{key}={stats[key]}" for key in ("records", "imported", "duplicates", "ignored", "invalid")), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
