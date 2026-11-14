#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Парсер приміських поїздів Київ — Ніжин із сайту Poizdato.net.
Зберігає дані у форматі schedule.json, сумісному з попереднім парсером.
"""

import argparse
import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://poizdato.net"
DIRECTIONS = {
    "kyiv_nizhyn": {
        "title": "Київ — Ніжин",
        "url": "https://poizdato.net/rozklad-poizdiv/kyiv--nizhyn/elektrychky/"
    },
    "nizhyn_kyiv": {
        "title": "Ніжин — Київ",
        "url": "https://poizdato.net/rozklad-poizdiv/nizhyn--kyiv/elektrychky/"
    }
}

OUTPUT = Path(__file__).resolve().parent / "schedule.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8"
}

TIME_RE = re.compile(r"\b(\d{1,2})[.:](\d{2})\b")


def clean_text(element):
    if not element:
        return ""
    return " ".join(element.stripped_strings).strip()


def normalize_time(raw):
    if not raw:
        return None
    match = TIME_RE.search(raw)
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def parse_train_stops(train_url, session):
    """Завантажує сторінку конкретного поїзда та витягує всі його зупинки."""
    resp = session.get(train_url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    days = "щоденно"
    for p in soup.select("p"):
        txt = clean_text(p)
        if "курсує" in txt.lower():
            days = re.sub(r"^.*?курсує\s*", "", txt, flags=re.IGNORECASE).rstrip(".")
            break

    stations = []
    # Шукаємо таблицю розкладу зупинок на сторінці поїзда
    for table in soup.select("table"):
        rows = table.select("tr")
        if len(rows) < 5:
            continue

        temp_stations = []
        for idx, row in enumerate(rows, start=1):
            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) < 2:
                continue

            row_text = clean_text(row)
            if not TIME_RE.search(row_text):
                continue

            # Назва станції зазвичай у першій комірці з посиланням або текстом
            link = row.select_one("a")
            station_name = clean_text(link) if link else clean_text(cells[0])
            station_name = re.sub(r"^(Станція|з\.п\.)\s+", "", station_name, flags=re.IGNORECASE).strip()

            if not station_name or len(station_name) < 2:
                continue

            # Витягуємо час прибуття і відправлення з комірок рядка
            arrival = None
            departure = None
            for cell in cells[1:]:
                c_text = clean_text(cell)
                if "приб" in c_text.lower():
                    arrival = normalize_time(c_text)
                elif "відпр" in c_text.lower():
                    departure = normalize_time(c_text)

            # Якщо підписів "приб./відпр." немає, беремо перші два значення часу у рядку
            if arrival is None and departure is None:
                times = [f"{int(h):02d}:{m}" for h, m in TIME_RE.findall(row_text)]
                # Відсіюємо час у дорозі (наприклад, "2г 15хв" не потрапить під TIME_RE)
                if len(times) == 1:
                    if idx == 1:
                        departure = times[0]
                    else:
                        arrival = times[0]
                elif len(times) >= 2:
                    arrival = times[0]
                    departure = times[1]

            if arrival or departure:
                temp_stations.append({
                    "id": idx,
                    "name": station_name,
                    "km": None,
                    "arrival": arrival,
                    "departure": departure
                })

        if len(temp_stations) >= 3:
            stations = temp_stations
            break

    return days, stations


def parse_direction(dir_key, config, session):
    """Розбирає список електричок для одного напрямку."""
    resp = session.get(config["url"], headers=HEADERS, timeout=25)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    trains = []
    seen_urls = set()

    # Знаходимо всі посилання на сторінки електричок (/rozklad-elektrychky/...)
    for link in soup.select('a[href*="/rozklad-elektrychky/"]'):
        href = link.get("href", "")
        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue

        row = link.find_parent("tr")
        row_text = clean_text(row) if row else clean_text(link)

        # Витягуємо номер поїзда (наприклад, 6902 або 896/895)
        num_match = re.search(r"\b(\d{3,4}(?:/\d{3,4})?)\b", row_text)
        if not num_match:
            continue

        seen_urls.add(full_url)
        train_number = num_match.group(1)

        # Витягуємо назву маршруту (наприклад, "Київ-Волинський — Ніжин")
        course = config["title"]
        route_match = re.search(
            r"([А-ЯІЇЄҐ][А-ЯІЇЄҐа-яіїєґ'\-\.\(\)\s]+?(?:→|—|-)\s*[А-ЯІЇЄҐ][А-ЯІЇЄҐа-яіїєґ'\-\.\(\)\s]+)",
            row_text
        )
        if route_match:
            course = route_match.group(1).replace("→", "—").strip()

        print(f"  Завантажую зупинки поїзда №{train_number}...")
        days, stations = parse_train_stops(full_url, session)

        if not stations:
            print(f"  Увага: не вдалося розібрати зупинки для №{train_number}, пропускаю.")
            continue

        trains.append({
            "tid": int(re.sub(r"\D", "", train_number.split("/")[0])),
            "number": train_number,
            "days": days,
            "course": course,
            "stations": stations
        })

        # Невелика пауза, щоб сервер не блокував часті запити
        time.sleep(0.5)

    if not trains:
        raise ValueError(f"Не знайдено жодної електрички для напрямку {config['title']}")

    max_stations = max(len(t["stations"]) for t in trains)

    return {
        "title": config["title"],
        "stations_count": max_stations,
        "trains": trains
    }


def main():
    parser = argparse.ArgumentParser(
        description="Розклад електричок Київ — Ніжин (Poizdato.net)"
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Дата розкладу у форматі YYYY-MM-DD"
    )
    args = parser.parse_args()

    session = requests.Session()

    print("Обробляю Київ → Ніжин...")
    forward = parse_direction("kyiv_nizhyn", DIRECTIONS["kyiv_nizhyn"], session)

    print("Обробляю Ніжин → Київ...")
    backward = parse_direction("nizhyn_kyiv", DIRECTIONS["nizhyn_kyiv"], session)

    data = {
        "source": DIRECTIONS["kyiv_nizhyn"]["url"],
        "checked": datetime.now().astimezone().isoformat(timespec="seconds"),
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

    print("\nГОТОВО!")
    print(f"Файл: {OUTPUT}")
    print(f"Київ → Ніжин: {len(forward['trains'])} поїздів")
    print(f"Ніжин → Київ: {len(backward['trains'])} поїздів")


if __name__ == "__main__":
    main()
