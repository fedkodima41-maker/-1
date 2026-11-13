#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Генерація розкладу на тиждень (сьогодні + 6 днів).
Запускає parser.py для кожної дати, об'єднує в trains.json.
"""

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PARSER = SCRIPT_DIR / "parser.py"
TRANSFORM = SCRIPT_DIR / "transform.py"
TRAINS_FILE = SCRIPT_DIR / "trains.json"


def run_parser(target_date: date) -> dict | None:
    """Запускає parser.py для конкретної дати, повертає schedule.json як dict."""
    date_str = target_date.isoformat()
    print(f"  📅 Парсинг {date_str}...")

    result = subprocess.run(
        [sys.executable, str(PARSER), "--date", date_str],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
        timeout=60
    )

    if result.returncode != 0:
        print(f"    ❌ Помилка: {result.stderr.strip()}")
        return None

    # Читаємо згенерований schedule.json
    schedule_file = SCRIPT_DIR / "schedule.json"
    if not schedule_file.exists():
        print(f"    ❌ Не створено schedule.json")
        return None

    with open(schedule_file, "r", encoding="utf-8") as f:
        return json.load(f)


def transform_schedule(schedule: dict) -> list:
    """Копія логіки з transform.py для inline-використання."""
    import re

    REGIONAL_PATTERNS = [r"^\d+/\d+$", r"^8\d{2}$", r"^8\d{3}$"]
    ELECTRIC_PATTERNS = [r"^69\d{2}$"]

    def is_regional(number: str) -> bool:
        for p in REGIONAL_PATTERNS:
            if re.match(p, number):
                return True
        return False

    def is_electric(number: str) -> bool:
        for p in ELECTRIC_PATTERNS:
            if re.match(p, number):
                return True
        return False

    def get_kind(number: str, course: str) -> str:
        if is_regional(number):
            return "Регіональний"
        if is_electric(number):
            return "Електричка"
        if any(x in course.lower() for x in ["фастів", "конотоп", "славутич", "чернігів", "хостка"]):
            return "Регіональний"
        return "Електричка"

    def parse_time(time_str: str):
        if not time_str:
            return None
        try:
            h, m = map(int, time_str.split(":"))
            return h * 60 + m
        except (ValueError, AttributeError):
            return None

    def format_duration(minutes):
        if minutes is None:
            return "—"
        hours = minutes // 60
        mins = minutes % 60
        if hours:
            return f"{hours}г {mins:02d}хв"
        return f"{mins}хв"

    def get_first_departure(stations):
        for s in stations:
            if s.get("departure"):
                return s["departure"]
        return None

    def get_last_arrival(stations):
        for s in reversed(stations):
            if s.get("arrival"):
                return s["arrival"]
        return None

    def count_stops(stations):
        count = 0
        for i, s in enumerate(stations):
            if i == 0 or i == len(stations) - 1:
                continue
            if s.get("arrival") or s.get("departure"):
                count += 1
        return count

    def get_origin_name(stations):
        for s in stations:
            if s.get("departure"):
                return s["name"]
        return stations[0]["name"] if stations else ""

    def get_destination_name(stations):
        for s in reversed(stations):
            if s.get("arrival"):
                return s["name"]
        return stations[-1]["name"] if stations else ""

    trains = []

    for direction_key, direction_data in schedule.get("directions", {}).items():
        direction = "kyiv_nizhyn" if direction_key == "kyiv_nizhyn" else "nizhyn_kyiv"

        for train in direction_data.get("trains", []):
            stations = train.get("stations", [])
            if not stations:
                continue

            number = train.get("number", "")
            kind = get_kind(number, train.get("course", ""))

            dep_time = get_first_departure(stations)
            arr_time = get_last_arrival(stations)

            dep_min = parse_time(dep_time)
            arr_min = parse_time(arr_time)
            duration_min = None
            if dep_min is not None and arr_min is not None:
                if arr_min < dep_min:
                    arr_min += 24 * 60
                duration_min = arr_min - dep_min

            stops = count_stops(stations)

            station_list = []
            for s in stations:
                station_list.append({
                    "name": s["name"],
                    "arrival": s.get("arrival"),
                    "departure": s.get("departure"),
                    "km": s.get("km")
                })

            trains.append({
                "id": number,
                "number": number,
                "kind": kind,
                "course": train.get("course", ""),
                "days": train.get("days", ""),
                "direction": direction,
                "dep": dep_time or "—",
                "arr": arr_time or "—",
                "duration": format_duration(duration_min),
                "stops": stops,
                "from": get_origin_name(stations),
                "to": get_destination_name(stations),
                "stations": station_list,
                "date": schedule.get("date"),
                "tid": train.get("tid")
            })

    def sort_key(t):
        dir_order = 0 if t["direction"] == "kyiv_nizhyn" else 1
        dep_min = parse_time(t["dep"]) or 9999
        return (dir_order, dep_min)

    trains.sort(key=sort_key)
    return trains


def main():
    today = date.today()
    all_trains = []
    all_schedules = []

    print("🔄 Генерація розкладу на 7 днів...\n")

    for i in range(7):
        target_date = today + timedelta(days=i)
        schedule = run_parser(target_date)

        if schedule:
            all_schedules.append(schedule)
            trains = transform_schedule(schedule)
            all_trains.extend(trains)
            print(f"    ✅ {len(trains)} поїздів")
        else:
            print(f"    ⚠️  Пропущено")

    if not all_trains:
        print("\n❌ Не вдалося отримати жодного розкладу")
        return 1

    # Видаляємо дублікати (ті самі поїзди на різних датах мають різний tid/date)
    # Але якщо tid+date однакові — це дублікат
    seen = set()
    unique_trains = []
    for t in all_trains:
        key = (t["tid"], t["date"])
        if key not in seen:
            seen.add(key)
            unique_trains.append(t)

    # Останній успішний checked час
    last_checked = all_schedules[-1].get("checked") if all_schedules else None

    output = {
        "source": all_schedules[0].get("source") if all_schedules else "https://swrailway.gov.ua/timetable/eltrain/",
        "checked": last_checked,
        "generated": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "date_from": all_schedules[0].get("date") if all_schedules else today.isoformat(),
        "date_to": all_schedules[-1].get("date") if all_schedules else (today + timedelta(days=6)).isoformat(),
        "trains": unique_trains
    }

    with open(TRAINS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Статистика
    electric = sum(1 for t in unique_trains if t["kind"] == "Електричка")
    regional = sum(1 for t in unique_trains if t["kind"] == "Регіональний")
    kyiv_nizhyn = sum(1 for t in unique_trains if t["direction"] == "kyiv_nizhyn")
    nizhyn_kyiv = sum(1 for t in unique_trains if t["direction"] == "nizhyn_kyiv")
    dates = sorted(set(t["date"] for t in unique_trains))

    print(f"\n✅ Готово! Файл: {TRAINS_FILE}")
    print(f"   Унікальних поїздів: {len(unique_trains)}")
    print(f"   Електрички: {electric}")
    print(f"   Регіональні: {regional}")
    print(f"   Київ → Ніжин: {kyiv_nizhyn}")
    print(f"   Ніжин → Київ: {nizhyn_kyiv}")
    print(f"   Дати: {', '.join(dates)}")

    return 0


if __name__ == "__main__":
    exit(main())