
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Парсер приміських поїздів Київ — Ніжин.
Джерело: офіційний сайт Південно-Західної залізниці.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup


URL = "https://swrailway.gov.ua/timetable/eltrain/"
OUTPUT = Path(__file__).resolve().parent / "schedule.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                  "AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
TID_RE = re.compile(r"tid=(\d+)")
SID_RE = re.compile(r"sid=(\d+)")


def clean_text(element):
    return " ".join(element.stripped_strings).strip()


def get_stations(tab):
    """Отримує станції та кілометраж з лівої таблиці."""

    table = tab.select_one("table.left")

    if not table:
        raise ValueError("Не знайдено таблицю станцій")

    stations = []

    for row in table.select("tr"):
        link = row.select_one('a.et[href*="sid="]')

        if not link:
            continue

        match = SID_RE.search(link.get("href", ""))

        if not match:
            continue

        km_cell = row.select_one("td.kmss")

        km = None
        if km_cell:
            try:
                km = float(clean_text(km_cell).replace(",", "."))
            except ValueError:
                pass

        stations.append({
            "id": int(match.group(1)),
            "name": clean_text(link),
            "km": km
        })

    if not stations:
        raise ValueError("Список станцій порожній")

    return stations


def get_trains(right_table):
    """Отримує номери, tid, маршрути та дні курсування."""

    links = right_table.select('a.et[href*="tid="]')

    trains = []

    for link in links:
        match = TID_RE.search(link.get("href", ""))

        if not match:
            continue

        text = clean_text(link)
        number_match = re.search(r"[\d]+(?:/[\d]+)?", text)

        if not number_match:
            continue

        trains.append({
            "tid": int(match.group(1)),
            "number": number_match.group(0),
            "days": text.replace(number_match.group(0), "", 1)
                    .strip(" ,"),
            "course": None
        })

    # Додаємо назви маршрутів із верхнього рядка таблиці.
    course_row = right_table.select_one("tr.train_obig")

    if course_row:
        courses = [
            clean_text(cell)
            for cell in course_row.select("td.course")
        ]

        for index, train in enumerate(trains):
            if index < len(courses):
                train["course"] = courses[index]

    if not trains:
        raise ValueError("Не знайдено жодного поїзда")

    return trains


def get_time_rows(right_table, train_count):
    """Отримує рядки часу прибуття та відправлення."""

    result = []

    for row in right_table.select("tr"):
        cells = []

        for cell in row.find_all("td", recursive=False):
            classes = cell.get("class", [])

            if "q0" not in classes and "q1" not in classes:
                continue

            value = clean_text(cell)

            if value == "–" or value == "-":
                cells.append(None)
            elif TIME_RE.match(value):
                cells.append(value)
            else:
                cells.append(None)

        if len(cells) == train_count * 2:
            result.append(cells)

    return result


def parse_direction(soup, tab_id):
    """Розбирає один напрямок руху."""

    tab = soup.select_one(f"div#{tab_id}")

    if not tab:
        raise ValueError(f"Не знайдено блок {tab_id}")

    stations = get_stations(tab)

    right_container = tab.select_one("div.gotime")

    if not right_container:
        raise ValueError(f"Не знайдено таблицю часу в {tab_id}")

    right_table = right_container.select_one("table")

    if not right_table:
        raise ValueError("Не знайдено внутрішню таблицю часу")

    trains = get_trains(right_table)

    time_rows = get_time_rows(right_table, len(trains))

    if len(time_rows) != len(stations):
        raise ValueError(
            f"{tab_id}: кількість станцій ({len(stations)}) "
            f"не збігається з рядками часу ({len(time_rows)}). "
            "Не зберігаю неповний розклад."
        )

    for train_index, train in enumerate(trains):
        train_stations = []

        for station_index, station in enumerate(stations):
            cells = time_rows[station_index]

            arrival = cells[train_index * 2]
            departure = cells[train_index * 2 + 1]

            train_stations.append({
                **station,
                "arrival": arrival,
                "departure": departure
            })

        train["stations"] = train_stations

    heading = tab.select_one("tr.shapka_obig b")

    return {
        "title": clean_text(heading) if heading else tab_id,
        "stations_count": len(stations),
        "trains": trains
    }


def main():
    parser = argparse.ArgumentParser(
        description="Розклад електричок Київ — Ніжин"
    )

    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Дата розкладу у форматі YYYY-MM-DD"
    )

    args = parser.parse_args()

    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        sys.exit("Помилка: дата має бути у форматі YYYY-MM-DD")

    params = {
        "gid": 2,
        "rid": 2,
        "reverse": 0,
        "dateR": 1,
        "eventdate": args.date
    }

    print(f"Завантажую розклад на {args.date}...")

    response = requests.get(
        URL,
        params=params,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()
    response.encoding = response.apparent_encoding

    soup = BeautifulSoup(response.text, "html.parser")

    print("Обробляю Київ → Ніжин...")
    forward = parse_direction(soup, "tabs-trains1")

    print("Обробляю Ніжин → Київ...")
    backward = parse_direction(soup, "tabs-trains2")

    data = {
        "source": URL,
        "checked": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "date": args.date,
        "route": "Київ — Ніжин",
        "directions": {
            "kyiv_nizhyn": forward,
            "nizhyn_kyiv": backward
        }
    }

    temporary = OUTPUT.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    temporary.replace(OUTPUT)

    print()
    print("ГОТОВО!")
    print(f"Файл: {OUTPUT}")
    print(f"Київ → Ніжин: {len(forward['trains'])} поїздів")
    print(f"Ніжин → Київ: {len(backward['trains'])} поїздів")
    print(f"Станцій у першому напрямку: {forward['stations_count']}")
    print(f"Станцій у другому напрямку: {backward['stations_count']}")


if __name__ == "__main__":
    main()
