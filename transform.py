#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Трансформація schedule.json → trains.json
Плоский формат для фронтенду.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
import re

SCHEDULE_FILE = Path(__file__).resolve().parent / "schedule.json"
TRAINS_FILE = Path(__file__).resolve().parent / "trains.json"

# Нумерація регіональних поїздів (з /\ або 8xx/8xxx)
REGIONAL_PATTERNS = [
    r"^\d+/\d+$",      # 892/891, 896/895, 886/885
    r"^8\d{2}$",       # 894, 898, 893, 897
    r"^8\d{3}$",       # якщо будуть 4-значні
]

# Електрички — 69xx, 690x, 691x, 692x
ELECTRIC_PATTERNS = [
    r"^69\d{2}$",
]


def is_regional(number: str) -> bool:
    """Визначає чи регіональний поїзд за номером."""
    for pattern in REGIONAL_PATTERNS:
        if re.match(pattern, number):
            return True
    return False


def is_electric(number: str) -> bool:
    """Визначає чи електричка за номером."""
    for pattern in ELECTRIC_PATTERNS:
        if re.match(pattern, number):
            return True
    return False


def get_kind(number: str, course: str) -> str:
    """Визначає тип поїзда."""
    if is_regional(number):
        return "Регіональний"
    if is_electric(number):
        return "Електричка"
    # Fallback за маршрутом
    if "фастів" in course.lower() or "конотоп" in course.lower() or "славутич" in course.lower() or "чернігів" in course.lower() or "хостка" in course.lower():
        return "Регіональний"
    return "Електричка"


def parse_time(time_str: str) -> int | None:
    """Конвертує 'HH:MM' в хвилини від полуночі."""
    if not time_str:
        return None
    try:
        h, m = map(int, time_str.split(":"))
        return h * 60 + m
    except (ValueError, AttributeError):
        return None


def format_duration(minutes: int | None) -> str:
    """Форматує тривалість у 'Xг Yхв'."""
    if minutes is None:
        return "—"
    hours = minutes // 60
    mins = minutes % 60
    if hours:
        return f"{hours}г {mins:02d}хв"
    return f"{mins}хв"


def get_first_departure(stations: list) -> str | None:
    """Перша станція з не-null departure."""
    for s in stations:
        if s.get("departure"):
            return s["departure"]
    return None


def get_last_arrival(stations: list) -> str | None:
    """Остання станція з не-null arrival."""
    for s in reversed(stations):
        if s.get("arrival"):
            return s["arrival"]
    return None


def count_stops(stations: list) -> int:
    """Рахує зупинки (станції з arrival/departure, крім першої/останньої)."""
    count = 0
    for i, s in enumerate(stations):
        if i == 0 or i == len(stations) - 1:
            continue
        if s.get("arrival") or s.get("departure"):
            count += 1
    return count


def get_origin_name(stations: list, direction: str) -> str:
    """Назва початкової станції (перша з часом)."""
    for s in stations:
        if s.get("departure"):
            return s["name"]
    return stations[0]["name"] if stations else ""


def get_destination_name(stations: list, direction: str) -> str:
    """Назва кінцевої станції (остання з часом)."""
    for s in reversed(stations):
        if s.get("arrival"):
            return s["name"]
    return stations[-1]["name"] if stations else ""


def transform_schedule(schedule: dict) -> list:
    """Перетворює schedule.json на плоский масив trains[]."""
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

            # Тривалість
            dep_min = parse_time(dep_time)
            arr_min = parse_time(arr_time)
            duration_min = None
            if dep_min is not None and arr_min is not None:
                # Якщо прибуття раніше відправлення — перехід через північ
                if arr_min < dep_min:
                    arr_min += 24 * 60
                duration_min = arr_min - dep_min

            # Зупинки
            stops = count_stops(stations)

            # Станції для модалки (УСІ станції маршруту)
            station_list = []
            for s in stations:
                station_list.append({
                    "name": s["name"],
                    "arrival": s.get("arrival"),
                    "departure": s.get("departure"),
                    "km": s.get("km")
                })

            trains.append({
                "id": number,                    # номер поїзда
                "number": number,                # дубль для сумісності
                "kind": kind,                    # "Електричка" | "Регіональний"
                "course": train.get("course", ""), # маршрут
                "days": train.get("days", ""),   # дні курсування
                "direction": direction,          # "kyiv_nizhyn" | "nizhyn_kyiv"
                "dep": dep_time or "—",          # відправлення
                "arr": arr_time or "—",          # прибуття
                "duration": format_duration(duration_min),
                "stops": stops,
                "from": get_origin_name(stations, direction),
                "to": get_destination_name(stations, direction),
                "stations": station_list,        # для модалки
                "date": schedule.get("date"),    # дата розкладу
                "tid": train.get("tid")
            })

    # Сортування: за напрямком, потім за часом відправлення
    def sort_key(t):
        dir_order = 0 if t["direction"] == "kyiv_nizhyn" else 1
        dep_min = parse_time(t["dep"]) or 9999
        return (dir_order, dep_min)

    trains.sort(key=sort_key)
    return trains


def main():
    if not SCHEDULE_FILE.exists():
        print(f"❌ Не знайдено {SCHEDULE_FILE}")
        return 1

    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        schedule = json.load(f)

    trains = transform_schedule(schedule)

    output = {
        "source": schedule.get("source"),
        "checked": schedule.get("checked"),
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "date": schedule.get("date"),
        "trains": trains
    }

    with open(TRAINS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Статистика
    electric = sum(1 for t in trains if t["kind"] == "Електричка")
    regional = sum(1 for t in trains if t["kind"] == "Регіональний")
    kyiv_nizhyn = sum(1 for t in trains if t["direction"] == "kyiv_nizhyn")
    nizhyn_kyiv = sum(1 for t in trains if t["direction"] == "nizhyn_kyiv")

    print("✅ Трансформація завершена")
    print(f"   Файл: {TRAINS_FILE}")
    print(f"   Всього поїздів: {len(trains)}")
    print(f"   Електрички: {electric}")
    print(f"   Регіональні: {regional}")
    print(f"   Київ → Ніжин: {kyiv_nizhyn}")
    print(f"   Ніжин → Київ: {nizhyn_kyiv}")

    return 0


if __name__ == "__main__":
    exit(main())