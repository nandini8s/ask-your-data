import sqlite3
import random
from datetime import datetime, timedelta

random.seed(42)          # same data every run
DB_FILE = "campus.db"

buildings = [
    (1, "CS Lab Block", "lab"),
    (2, "Main Academic Block", "academic"),
    (3, "Library", "library"),
    (4, "Boys Hostel A", "hostel"),
    (5, "Girls Hostel B", "hostel"),
    (6, "Auditorium", "auditorium"),
    (7, "Admin Block", "admin"),
    (8, "Canteen", "canteen"),
]

events = [
    ("Mid-semester exams", "2026-09-14", "2026-09-20"),
    ("Annual tech fest", "2026-09-24", "2026-09-26"),
]

START = datetime(2026, 8, 1)
DAYS = 60


def in_event(day_str, name):
    for ev_name, start, end in events:
        if ev_name == name and start <= day_str <= end:
            return True
    return False


def base_kwh(btype, hour, weekend, exam_week, fest_day):
    daytime = 8 <= hour < 18
    if btype == "academic":
        return 55 if (daytime and not weekend) else 12
    if btype == "lab":
        return 30 if (daytime and not weekend) else 20      # story 1: night waste
    if btype == "library":
        if exam_week and (hour >= 18 or hour < 3):
            return 28                                        # story 2: exam surge
        return 25 if daytime else (18 if hour >= 18 else 3)
    if btype == "hostel":
        if 18 <= hour < 24:
            return 18
        if hour < 6:
            return 10
        return 8 if hour < 8 else 6
    if btype == "auditorium":
        if fest_day and 8 <= hour < 24:
            return 45                                        # story 3: fest spike
        return 3
    if btype == "admin":
        return 14 if (daytime and not weekend) else 2
    if btype == "canteen":
        return 16 if hour in (7, 8, 12, 13, 19, 20) else 4
    return 5


conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

cur.execute("DROP TABLE IF EXISTS readings")
cur.execute("DROP TABLE IF EXISTS events")
cur.execute("DROP TABLE IF EXISTS buildings")

cur.execute("""CREATE TABLE buildings (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL)""")

cur.execute("""CREATE TABLE events (
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL)""")

cur.execute("""CREATE TABLE readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    building_id INTEGER NOT NULL,
    reading_time TEXT NOT NULL,
    kwh REAL NOT NULL,
    FOREIGN KEY (building_id) REFERENCES buildings(id))""")

cur.executemany("INSERT INTO buildings VALUES (?, ?, ?)", buildings)
cur.executemany("INSERT INTO events VALUES (?, ?, ?)", events)

rows = []
for d in range(DAYS):
    day = START + timedelta(days=d)
    day_str = day.strftime("%Y-%m-%d")
    weekend = day.weekday() >= 5
    exam_week = in_event(day_str, "Mid-semester exams")
    fest_day = in_event(day_str, "Annual tech fest")
    for hour in range(24):
        stamp = f"{day_str} {hour:02d}:00"
        for b_id, name, btype in buildings:
            kwh = base_kwh(btype, hour, weekend, exam_week, fest_day)
            kwh = round(kwh * random.uniform(0.9, 1.1), 2)
            rows.append((b_id, stamp, kwh))

cur.executemany(
    "INSERT INTO readings (building_id, reading_time, kwh) VALUES (?, ?, ?)", rows
)

conn.commit()
conn.close()
print(f"Created {DB_FILE} with {len(buildings)} buildings and {len(rows)} readings.")