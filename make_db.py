import argparse
import os
import random
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


DB_FILE = Path(__file__).resolve().parent / "campus.db"
EXPECTED_READING_COUNT = 11520

BUILDINGS = [
    (1, "CS Lab Block", "lab"),
    (2, "Main Academic Block", "academic"),
    (3, "Library", "library"),
    (4, "Boys Hostel A", "hostel"),
    (5, "Girls Hostel B", "hostel"),
    (6, "Auditorium", "auditorium"),
    (7, "Admin Block", "admin"),
    (8, "Canteen", "canteen"),
]

EVENTS = [
    ("Mid-semester exams", "2026-09-14", "2026-09-20"),
    ("Annual tech fest", "2026-09-24", "2026-09-26"),
]

START = datetime(2026, 8, 1)
DAYS = 60


def in_event(day_str, name):
    for event_name, start, end in EVENTS:
        if event_name == name and start <= day_str <= end:
            return True
    return False


def base_kwh(btype, hour, weekend, exam_week, fest_day):
    daytime = 8 <= hour < 18
    if btype == "academic":
        return 55 if daytime and not weekend else 12
    if btype == "lab":
        return 30 if daytime and not weekend else 20
    if btype == "library":
        if exam_week and (hour >= 18 or hour < 3):
            return 28
        return 25 if daytime else (18 if hour >= 18 else 3)
    if btype == "hostel":
        if 18 <= hour < 24:
            return 18
        if hour < 6:
            return 10
        return 8 if hour < 8 else 6
    if btype == "auditorium":
        if fest_day and 8 <= hour < 24:
            return 45
        return 3
    if btype == "admin":
        return 14 if daytime and not weekend else 2
    if btype == "canteen":
        return 16 if hour in (7, 8, 12, 13, 19, 20) else 4
    return 5


def _populate_database(database_path):
    rng = random.Random(42)
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE buildings (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL
            );
            CREATE TABLE events (
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL
            );
            CREATE TABLE readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                building_id INTEGER NOT NULL,
                reading_time TEXT NOT NULL,
                kwh REAL NOT NULL,
                FOREIGN KEY (building_id) REFERENCES buildings(id)
            );
            """
        )
        connection.executemany("INSERT INTO buildings VALUES (?, ?, ?)", BUILDINGS)
        connection.executemany("INSERT INTO events VALUES (?, ?, ?)", EVENTS)

        rows = []
        for day_offset in range(DAYS):
            day = START + timedelta(days=day_offset)
            day_str = day.strftime("%Y-%m-%d")
            weekend = day.weekday() >= 5
            exam_week = in_event(day_str, "Mid-semester exams")
            fest_day = in_event(day_str, "Annual tech fest")
            for hour in range(24):
                timestamp = f"{day_str} {hour:02d}:00"
                for building_id, _name, building_type in BUILDINGS:
                    kwh = base_kwh(building_type, hour, weekend, exam_week, fest_day)
                    kwh = round(kwh * rng.uniform(0.9, 1.1), 2)
                    rows.append((building_id, timestamp, kwh))

        connection.executemany(
            "INSERT INTO readings (building_id, reading_time, kwh) VALUES (?, ?, ?)",
            rows,
        )
        connection.commit()
        actual_count = connection.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        if actual_count != EXPECTED_READING_COUNT:
            raise RuntimeError(
                f"Generated {actual_count} readings; expected {EXPECTED_READING_COUNT}."
            )
    finally:
        connection.close()


def create_database(db_file=DB_FILE, overwrite=False):
    target = Path(db_file).resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"{target} already exists; move it aside or pass --force to replace it."
        )
    target.parent.mkdir(parents=True, exist_ok=True)

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        _populate_database(temporary_path)
        if overwrite:
            os.replace(temporary_path, target)
        else:
            # Hard-linking makes the no-overwrite check atomic on this filesystem.
            os.link(temporary_path, target)
            temporary_path.unlink()
    finally:
        temporary_path.unlink(missing_ok=True)

    print(f"Created {target} with {len(BUILDINGS)} buildings and {EXPECTED_READING_COUNT} readings.")
    return target


def main():
    parser = argparse.ArgumentParser(description="Create the synthetic campus SQLite database.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing generated database",
    )
    args = parser.parse_args()
    try:
        create_database(overwrite=args.force)
    except (OSError, sqlite3.Error, RuntimeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
