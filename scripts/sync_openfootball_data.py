#!/usr/bin/env python3
"""Synchronize public-domain OpenFootball results from 2022 onward.

The generated CSVs use the existing Data Library importer's column aliases.
No API key or third-party Python package is required.
"""
import argparse
import csv
import io
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

SOURCES = [
    {
        "code": "ENG_1",
        "name": "Premier League",
        "country": "England",
        "repo": "england",
        "file": "1-premierleague.txt",
    },
    {
        "code": "ESP_1",
        "name": "La Liga",
        "country": "Spain",
        "repo": "espana",
        "file": "1-liga.txt",
    },
    {
        "code": "GER_1",
        "name": "Bundesliga",
        "country": "Germany",
        "repo": "deutschland",
        "file": "1-bundesliga.txt",
    },
    {
        "code": "ITA_1",
        "name": "Serie A",
        "country": "Italy",
        "repo": "italy",
        "file": "1-seriea.txt",
    },
    {
        "code": "FRA_1",
        "name": "Ligue 1",
        "country": "France",
        "repo": "europe",
        "path_template": "france/{season}_fr1.txt",
    },
]

COLUMNS = [
    "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG",
    "HTHG", "HTAG", "Season", "League", "Country", "Source",
]
DATE_LINE = re.compile(r"^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})\s*$")
MATCH_LINE = re.compile(
    r"^\s*(?:(\d{1,2}:\d{2})\s+)?(.+?)\s+(\d{1,2})-(\d{1,2})"
    r"(?:\s+\((\d{1,2})-(\d{1,2})\))?\s+(.+?)\s*$"
)
MONTHS = {name: number for number, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1
)}


def season_label(start_year):
    return f"{start_year}/{str(start_year + 1)[-2:]}"


def parse_season_text(text, start_year, min_date):
    """Parse OpenFootball Football.TXT match rows into normalized CSV dicts."""
    current_date = None
    rows = []
    for line in text.splitlines():
        date_match = DATE_LINE.match(line)
        if date_match:
            month = MONTHS[date_match.group(1)]
            day = int(date_match.group(2))
            explicit_year = date_match.group(3)
            year = int(explicit_year) if explicit_year else (start_year if month >= 7 else start_year + 1)
            try:
                from datetime import date
                date(year, month, day)
                current_date = f"{year:04d}-{month:02d}-{day:02d}"
            except ValueError:
                current_date = None
            continue

        if not current_date or current_date < min_date:
            continue
        match = MATCH_LINE.match(line)
        if match:
            _kickoff, home, home_goals, away_goals, ht_home, ht_away, away = match.groups()
        else:
            match_v = MATCH_LINE_V.match(line)
            if not match_v:
                continue
            _kickoff, home, away, home_goals, away_goals, ht_home, ht_away = match_v.groups()
        home = " ".join(home.split()).strip()
        away = " ".join(away.split()).strip()
        if not home or not away:
            continue

        rows.append({
            "Date": current_date,
            "HomeTeam": home,
            "AwayTeam": away,
            "FTHG": int(home_goals),
            "FTAG": int(away_goals),
            "HTHG": int(ht_home) if ht_home is not None else "",
            "HTAG": int(ht_away) if ht_away is not None else "",
            "Season": season_label(start_year),
            "League": "",
            "Country": "",
            "Source": "OpenFootball (CC0 public domain)",
        })
    return rows


def fetch_text(url, timeout=45):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "FootballPredictionPlatform historical data sync"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def collect_source(source, first_season, last_season, min_date):
    rows = []
    errors = []
    for start_year in range(first_season, last_season + 1):
        season = f"{start_year}-{str(start_year + 1)[-2:]}"
        source_path = source.get("path_template", f"{season}/{source.get('file', '')}").format(season=season)
        url = (
            f"https://raw.githubusercontent.com/openfootball/{source['repo']}/"
            f"master/{source_path}"
        )
        try:
            text = fetch_text(url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            errors.append(f"{season}: unavailable ({exc})")
            continue

        season_rows = parse_season_text(text, start_year, min_date)
        for row in season_rows:
            row["League"] = source["name"]
            row["Country"] = source["country"]
        rows.extend(season_rows)
        print(f"{source['code']} {season}: {len(season_rows)} matches")

    # Stable deduplication protects against repeated source rows.
    unique = {}
    for row in rows:
        key = (row["Date"], row["HomeTeam"].casefold(), row["AwayTeam"].casefold())
        unique[key] = row
    return list(unique.values()), errors


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (row["Date"], row["HomeTeam"])))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-year", type=int, default=2022,
                        help="Earliest calendar year to include (default: 2022)")
    parser.add_argument("--to-year", type=int, default=2026,
                        help="Latest season start year to fetch (default: 2026)")
    parser.add_argument("--min-date", default="2022-01-01",
                        help="Hard lower date boundary (default: 2022-01-01)")
    parser.add_argument("--output", default="Data/OpenFootball_2022_2026",
                        help="Output directory for normalized CSV files")
    args = parser.parse_args(argv)

    if args.from_year < 1900 or args.to_year < args.from_year:
        parser.error("Invalid year range.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.min_date):
        parser.error("--min-date must use YYYY-MM-DD.")

    # Include the season that contains January-May of the requested first year.
    first_season = args.from_year - 1
    output_dir = Path(args.output)
    total = 0
    failures = []

    for source in SOURCES:
        rows, errors = collect_source(
            source, first_season, args.to_year, args.min_date
        )
        failures.extend(f"{source['code']} {item}" for item in errors)
        if not rows:
            print(f"ERROR: no usable rows for {source['name']}", file=sys.stderr)
            continue
        output = output_dir / f"{source['code']}_{args.from_year}_{args.to_year}.csv"
        write_csv(output, rows)
        total += len(rows)
        print(f"Wrote {len(rows)} rows: {output}")

    if total == 0:
        print("No historical matches were downloaded; refusing an empty sync.", file=sys.stderr)
        return 1

    print(f"\nTotal normalized matches: {total}")
    if failures:
        print("Some source seasons were unavailable:")
        for failure in failures:
            print(f" - {failure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
