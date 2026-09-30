"""Synthetic-only unit and CLI checks; never read personal health files."""

import csv
from datetime import date, datetime, time, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from calendar_reminders import build_calendar, escape, fold
from health_import import import_health


HERE = Path(__file__).resolve().parent


def record(kind, value, start, end=None, unit=None, source="A Watch"):
    attrs = {"type": kind, "value": str(value), "sourceName": source, "startDate": start, "endDate": end or start}
    if unit is not None:
        attrs["unit"] = unit
    return attrs


def xml_file(path, records):
    root = ET.Element("HealthData", locale="en_US")
    for attrs in records:
        ET.SubElement(root, "Record", attrs)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def sample_records():
    sleep = "HKCategoryTypeIdentifierSleepAnalysis"
    steps = "HKQuantityTypeIdentifierStepCount"
    return [
        record(sleep, "HKCategoryValueSleepAnalysisAsleepCore", "2026-09-29 14:30:00 +0000", "2026-09-29 15:30:00 +0000"),
        record(sleep, "HKCategoryValueSleepAnalysisAsleepCore", "2026-09-29 23:30:00 +0900", "2026-09-30 00:30:00 +0900"),
        record(sleep, "HKCategoryValueSleepAnalysisAsleepDeep", "2026-09-30 00:00:00 +0900", "2026-09-30 01:00:00 +0900"),
        record(sleep, "HKCategoryValueSleepAnalysisAsleepREM", "2026-09-30 00:45:00 +0900", "2026-09-30 01:15:00 +0900"),
        record(sleep, "HKCategoryValueSleepAnalysisAsleepUnspecified", "2026-09-29 23:30:00 +0900", "2026-09-30 03:00:00 +0900", source="Z Phone"),
        record(sleep, "HKCategoryValueSleepAnalysisInBed", "2026-09-29 21:00:00 +0900", "2026-09-30 07:00:00 +0900"),
        record(steps, 120, "2026-09-29 23:00:00 +0900", "2026-09-30 01:00:00 +0900", "count"),
        record(steps, 100, "2026-09-30 09:00:00 +0900", "2026-09-30 10:00:00 +0900", "count"),
        record(steps, 100, "2026-09-30 09:00:00 +0900", "2026-09-30 10:00:00 +0900", "count"),
        record(steps, 200, "2026-09-30 10:00:00 +0900", "2026-09-30 11:00:00 +0900", "count"),
        record(steps, 1000, "2026-09-30 09:00:00 +0900", "2026-09-30 11:00:00 +0900", "count", "Z Phone"),
        record("HKQuantityTypeIdentifierAppleExerciseTime", 30, "2026-09-30 12:00:00 +0900", unit="min"),
        record("HKQuantityTypeIdentifierAppleExerciseTime", 600, "2026-09-30 12:10:00 +0900", unit="s"),
        record("HKQuantityTypeIdentifierRestingHeartRate", 60, "2026-09-30 06:00:00 +0900", unit="count/min"),
        record("HKQuantityTypeIdentifierRestingHeartRate", 70, "2026-09-30 07:00:00 +0900", unit="bpm"),
        record("HKQuantityTypeIdentifierBodyMass", 154, "2026-09-30 07:00:00 +0900", unit="lb"),
        record("HKQuantityTypeIdentifierBodyMass", 70000, "2026-09-30 20:00:00 +0900", unit="g"),
        record("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", .05, "2026-09-30 06:00:00 +0900", unit="s"),
        record("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", 70, "2026-09-30 07:00:00 +0900", unit="ms"),
        record(steps, 25, "2026-10-01 09:00:00 +0900", unit="count"),
        record(steps, -1, "2026-10-01 09:00:00 +0900", unit="count"),
        record(steps, "inf", "2026-10-01 09:00:00 +0900", unit="count"),
        record("HKQuantityTypeIdentifierBodyMass", 200, "2026-10-01 09:00:00 +0900", unit="unknown"),
    ]


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.xml = self.folder / "export.xml"
        self.output = self.folder / "daily.csv"

    def rows(self):
        with self.output.open(encoding="utf-8", newline="") as handle:
            return {row["date"]: row for row in csv.DictReader(handle)}

    def test_cli_timezone_overlap_units_sources_and_missing_values(self):
        xml_file(self.xml, sample_records())
        run = subprocess.run([sys.executable, str(HERE / "health_import.py"), str(self.xml), "--output", str(self.output)],
                             text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("invalid=3", run.stderr)
        self.assertIn("duplicates=2", run.stderr)
        rows = self.rows()
        self.assertEqual(rows["2026-09-29"]["sleep_hours"], "0.5")
        self.assertEqual(rows["2026-09-30"]["sleep_hours"], "1.25")
        self.assertEqual(rows["2026-09-29"]["steps"], "60")
        self.assertEqual(rows["2026-09-30"]["steps"], "360")
        self.assertEqual(rows["2026-09-30"]["exercise_min"], "40")
        self.assertEqual(rows["2026-09-30"]["resting_hr"], "65")
        self.assertEqual(rows["2026-09-30"]["weight_kg"], "70")
        self.assertEqual(rows["2026-09-30"]["hrv_ms"], "60")
        self.assertIn("steps=A Watch", rows["2026-09-30"]["note"])
        self.assertIn("Asia/Tokyo 0時区切り", rows["2026-09-30"]["note"])
        self.assertIn("SDNN(ms)", rows["2026-09-30"]["note"])
        self.assertEqual(rows["2026-10-01"]["steps"], "25")
        for metric in ("sleep_hours", "exercise_min", "resting_hr", "weight_kg", "hrv_ms"):
            self.assertEqual(rows["2026-10-01"][metric], "")
        with self.output.with_name("daily.sources.csv").open(encoding="utf-8", newline="") as handle:
            sources = list(csv.DictReader(handle))
        self.assertTrue(all(row["source"] == "A Watch" for row in sources))

    def test_source_override_and_record_order_are_deterministic(self):
        records = sample_records()
        xml_file(self.xml, records)
        import_health(self.xml, self.output, overrides={"sleep_hours": "Z Phone"})
        first = self.output.read_bytes()
        self.assertEqual(self.rows()["2026-09-30"]["sleep_hours"], "3")
        xml_file(self.xml, list(reversed(records)))
        import_health(self.xml, self.output, overrides={"sleep_hours": "Z Phone"})
        self.assertEqual(self.output.read_bytes(), first)

    def test_dst_elapsed_time_and_pounds(self):
        xml_file(self.xml, [
            record("HKCategoryTypeIdentifierSleepAnalysis", "HKCategoryValueSleepAnalysisAsleep",
                   "2026-03-08 01:30:00 -0500", "2026-03-08 03:30:00 -0400"),
            record("HKQuantityTypeIdentifierBodyMass", 154, "2026-03-08 07:00:00 -0400", unit="lb"),
        ])
        import_health(self.xml, self.output, timezone_name="America/New_York")
        rows = self.rows()
        self.assertEqual(rows["2026-03-08"]["sleep_hours"], "1")
        self.assertAlmostEqual(float(rows["2026-03-08"]["weight_kg"]), 154 * .45359237, places=5)

    def test_missing_requested_source_is_blank(self):
        xml_file(self.xml, sample_records())
        import_health(self.xml, self.output, overrides={"sleep_hours": "Not present"})
        self.assertTrue(all(row["sleep_hours"] == "" for row in self.rows().values()))

    def test_timezone_required_and_negative_duration_rejected(self):
        xml_file(self.xml, [
            record("HKQuantityTypeIdentifierStepCount", 1, "2026-09-30 12:00:00", unit="count"),
            record("HKQuantityTypeIdentifierStepCount", 1, "2026-09-30 12:00:00 +0900", "2026-09-30 11:00:00 +0900", "count"),
        ])
        stats = import_health(self.xml, self.output)
        self.assertEqual(stats["invalid"], 2)
        self.assertEqual(stats["days"], 0)
        self.assertEqual(self.rows(), {})

    def test_input_output_collision_rejected_without_overwrite(self):
        xml_file(self.xml, sample_records())
        original = self.xml.read_bytes()
        with self.assertRaises(ValueError):
            import_health(self.xml, self.xml)
        self.assertEqual(self.xml.read_bytes(), original)

    def test_source_names_cannot_become_spreadsheet_formulas(self):
        xml_file(self.xml, [record("HKQuantityTypeIdentifierStepCount", 25,
                                 "2026-10-01 09:00:00 +0900", unit="count", source="=SUM(1,2)")])
        import_health(self.xml, self.output)
        with self.output.with_name("daily.sources.csv").open(encoding="utf-8", newline="") as handle:
            source = next(csv.DictReader(handle))["source"]
        self.assertEqual(source, "'=SUM(1,2)")

    def test_midnight_steps_are_integer_and_preserve_total(self):
        xml_file(self.xml, [record("HKQuantityTypeIdentifierStepCount", 3,
                                 "2026-09-29 23:00:00 +0900", "2026-09-30 01:00:00 +0900", "count")])
        import_health(self.xml, self.output)
        rows = self.rows()
        self.assertEqual(rows["2026-09-29"]["steps"], "2")
        self.assertEqual(rows["2026-09-30"]["steps"], "1")
        self.assertEqual(sum(int(row["steps"]) for row in rows.values()), 3)


class CalendarTests(unittest.TestCase):
    def test_default_timezone_and_no_alarm(self):
        data, count = build_calendar(start_date=date(2026, 9, 30), days=2)
        self.assertEqual(count, 22)
        self.assertEqual(data.count("BEGIN:VEVENT\r\n"), 22)
        self.assertIn("DTSTART:20260929T220000Z\r\n", data)
        self.assertNotIn("BEGIN:VALARM", data)
        self.assertNotIn("RRULE", data)
        self.assertTrue(all(len(line.encode("utf-8")) <= 75 for line in data.split("\r\n")))
        self.assertEqual(data.count("UID:"), len({line for line in data.split("\r\n") if line.startswith("UID:")}))

    def test_cli_custom_times_and_optional_alarm(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "reminders.ics"
            run = subprocess.run([sys.executable, str(HERE / "calendar_reminders.py"), "--start-date", "2026-09-30",
                                  "--days", "1", "--wake", "08:30", "--winddown", "none", "--move-every", "0",
                                  "--alarm-minutes", "5", "--output", str(output)], text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            data = output.read_bytes().decode("utf-8")
        self.assertEqual(data.count("BEGIN:VEVENT\r\n"), 1)
        self.assertEqual(data.count("BEGIN:VALARM\r\n"), 1)
        self.assertIn("TRIGGER:-PT5M\r\n", data)
        self.assertIn("DTSTART:20260929T233000Z\r\n", data)

    def test_dst_nonexistent_time_and_invalid_windows_rejected(self):
        with self.assertRaises(ValueError):
            build_calendar(start_date=date(2026, 3, 8), days=1, timezone_name="America/New_York", wake=time(2, 30))
        with self.assertRaises(ValueError):
            build_calendar(start_date=date(2026, 9, 30), move_start=time(18), move_end=time(9))
        with self.assertRaises(ValueError):
            build_calendar(start_date=date(2026, 9, 30), days=0)

    def test_utf8_folding_escape_and_stable_identifiers(self):
        value = "DESCRIPTION:" + "ヘルスラボの記録" * 30
        folded = fold(value)
        self.assertEqual(folded.replace("\r\n ", ""), value)
        self.assertTrue(all(len(line.encode()) <= 75 for line in folded.split("\r\n")))
        self.assertEqual(escape("a,b;c\\d\ne"), "a\\,b\\;c\\\\d\\ne")
        a, _ = build_calendar(start_date=date(2026, 9, 30), days=1, generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
        b, _ = build_calendar(start_date=date(2026, 9, 30), days=1, generated_at=datetime(2026, 9, 2, tzinfo=timezone.utc))
        self.assertEqual([line for line in a.splitlines() if line.startswith("UID:")],
                         [line for line in b.splitlines() if line.startswith("UID:")])


if __name__ == "__main__":
    unittest.main()
