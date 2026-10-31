# Football Prediction Platform

A local-first Windows football analytics and prediction workspace built with Python, PySide6 and SQLite.

## Current platform

- Dashboard, Live Fixtures, Match Analysis, Prediction History and Performance Lab.
- API-Football integration with a securely stored API key.
- Date-based fixture caching and optional-data caching to reduce repeat API calls.
- Local historical football archive for major competitions, with manual season imports, idempotent fixture updates, sync history and database coverage summaries.
- Match analysis reads team form and head-to-head history from SQLite first; API-Football is used only when local history is missing.
- Newly downloaded fixtures, fallback team histories, head-to-head matches and available corner statistics are saved into the historical archive.
- Local API request counter; it is an app-side counter, not the provider's official remaining quota.
- Automatic fallback to cached fixtures when a provider request fails.
- Demo fixtures for interface testing without API requests.
- Goal and result predictions using an explainable ensemble:
  - Independent Poisson goal-distribution model.
  - Recent-form strength model.
  - Local softmax-regression model that activates after at least 200 verified settled predictions with sufficient examples from all three outcomes.
- 1X2, over/under goals, BTTS and likely scorelines.
- Corner predictions for match totals and each team's corners when sufficient historical corner statistics are available.
- Match intelligence: injuries/suspensions, announced lineups, referee, venue weather and historical corner context.
- Player Intelligence workspace with timestamped API-Football injury/lineup snapshots, completed-match player appearances and performance comparisons.
- Player availability comparisons distinguish confirmed Missing Fixture reports from unknown absences; missing injury feeds are never treated as proof of fitness.
- Prediction settlement and performance tracking by market, day and model version.
- Probability-quality metrics: multiclass Brier score and log loss.
- SQLite migrations preserve existing prediction history and the historical archive shares the same app-private database file.

## Historical database and synchronization

- Open the **Data Library** tab to import seasons manually for the Premier League, La Liga, Bundesliga, Serie A, Ligue 1, UEFA Champions League and Uganda Premier League.
- The default import range is 2021–2026 (five completed-season keys plus the current season key); change it to match your API plan's historical access.
- Import one competition at a time to control API usage. The all-major-competitions action displays an estimated request count and requires confirmation.
- Each successful competition-season is committed immediately. Repeating an import updates existing provider fixture IDs rather than creating duplicates.
- Historical fixture payloads are retained locally. Detailed statistics are stored when separately fetched and supplied by the provider; they are not assumed to exist for every historical match.
- Synchronization is manual: the app does not automatically contact the API on startup.

## Data quality and model safeguards

- Demo forecasts are never counted as real performance.
- Missing data is labelled unavailable; it is never silently replaced with zero.
- Corner markets are not generated without observed corner averages.
- Injury, lineup, referee and weather context are shown and affect the model's data-coverage confidence. Their numerical impact is not weighted until chronological backtesting supports it.
- The local machine-learning model remains inactive until sufficient settled examples exist. The initial Poisson/form ensemble remains available in the meantime.
- Model probabilities are estimates, not guarantees or betting advice.

## Download the Windows build

1. Open the repository Actions tab after a push or manually run the workflow.
2. Open the latest successful Windows desktop build run.
3. Under Artifacts, download `FootballPredictionPlatform-Windows`.
4. Extract the ZIP and launch `FootballPredictionPlatform.exe`.

The app is unsigned, so Windows may display a SmartScreen warning. Only run the build downloaded from your own repository.

## Development notes

- Python 3.12, PySide6, SQLite and PyInstaller.
- Unit tests run before the Windows executable is built.
- API calls are initiated only by user actions; cached data is reused according to its freshness window.
- Open-Meteo supplies weather when venue coordinates are available.


## Player availability and performance intelligence

- Every time match intelligence is loaded, the app stores the injury/suspension response and announced lineup as timestamped snapshots in the same local SQLite database.
- For completed fixtures, the app also requests and stores individual player match statistics (appearances, minutes and ratings where supplied).
- The Player Intelligence tab compares a team's results when a selected player appeared, when a fixture-specific report marked them as a **Missing Fixture**, and when the reason for absence is unknown.
- Historical snapshots are retained when provider data changes. Identical payloads are deduplicated; normalized player records are safely upserted.
- A player missing from a lineup is not assumed injured. Questionable reports are not counted as confirmed absences.
- Player and team IDs currently use API-Football IDs. Cross-provider identity mapping will be added with the FootyStats integration.
- API-Football's injury endpoint has historical availability from April 2021, but actual coverage varies by league and season. The app only records data returned by the user's plan and provider coverage.


## Provider-independent historical CSV imports

- Open Data Library and select **Import Historical CSV** to load a local .csv dataset without a second paid API subscription.
- Select the competition already chosen in Data Library and enter the season start year represented by the file.
- Recognizes common Football-Data.co.uk headers (Date, HomeTeam, AwayTeam, FTHG, FTAG, HC, AC, HY, AY, HR, AR, B365H/D/A) and generic equivalents. Comma, semicolon and tab-delimited files are supported.
- Goals, corners, cards, shots, shots on target, possession and 1X2 odds are retained whenever present. Missing fields remain unavailable, never zero.
- Imported matches use deterministic negative local IDs, separate from API-Football positive fixture IDs. Re-importing a matching date/team/competition/season updates the record instead of duplicating it.
- Original file name, CSV provider marker, normalized match payload, file SHA-256 and an import-history record are stored locally.
- Invalid rows are skipped with row-level explanations; files missing required date, team or full-time-goal columns are rejected with a format hint.
- CSV team identities are source-local and are not silently equated with API-Football IDs. Cross-provider team/fixture mapping is a later reconciliation step before CSV rows are mixed into provider-ID-based model queries.
