# Historical data synchronization

The platform can now synchronize public-domain match results from the
[OpenFootball repositories](https://github.com/openfootball). The source
projects dedicate their datasets to the public domain (CC0); see each
repository's license and attribution guidance.

## Scope

The first automated connector covers:
- England — Premier League
- Spain — La Liga
- Germany — Bundesliga
- Italy — Serie A
- France — Ligue 1
- Egypt — Egyptian Premier League (available seasons begin 2023/24)
- Morocco — Botola Pro (available seasons begin 2023/24)
- Algeria — Ligue 1 (available seasons begin 2023/24)

The sync fetches season files from 2021/22 onward and enforces a hard date
boundary of **2022-01-01**. This is intentional: January–May 2022 belongs to
the 2021/22 season, so that season must be included to avoid losing those
matches. It also fetches season-start years through 2026/27 (the current
season as of November 2026).

The selected African repositories currently publish recent seasons from 2023/24; they do not provide a verified 2022 season archive. The connector exports CSVs into `Data/OpenFootball_2022_2026/` using the
column names recognized by `csv_historical_importer.py`. It includes
full-time and half-time goals when present. The source does not provide
corners, shots, cards, xG, injuries or lineups; missing values are not
fabricated. API-Football remains the source for fixture intelligence,
injuries and lineups.

## Run

From the repository root:

```bash
python scripts/sync_openfootball_data.py
```

To change the range:

```bash
python scripts/sync_openfootball_data.py --from-year 2022 --to-year 2026
```

GitHub Actions runs the sync weekly and also supports manual runs from the
Actions tab. It commits only changed CSVs. The existing Windows build
workflow is unchanged.

## Import into the local Data Library

After the sync completes, download the repository update or pull it locally.
In the app, open Data Library → Import Historical CSV, select the relevant
league, and import the matching CSV from `Data/OpenFootball_2022_2026/`.
The existing importer assigns the selected competition's local/API league
identity and stores records in the existing SQLite archive. This first
connector does not silently rewrite or delete any already-imported local
records.

## Important limitations

This is a results archive, not a complete advanced-statistics feed. Match
coverage depends on what each OpenFootball league repository publishes.
Only completed matches with scores are emitted. Upcoming fixtures without
scores are ignored. This initial connector deliberately does not import
football-data.co.uk files because that provider's published terms restrict
use in commercial and AI/data-training products.
