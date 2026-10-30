# Football Prediction Platform

A local-first Windows football analytics and prediction workspace built with Python, PySide6 and SQLite.

## Current platform

- Dashboard, Live Fixtures, Match Analysis, Prediction History and Performance Lab.
- API-Football integration with a securely stored API key.
- Date-based fixture caching and optional-data caching to reduce repeat API calls.
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
- Prediction settlement and performance tracking by market, day and model version.
- Probability-quality metrics: multiclass Brier score and log loss.
- SQLite migrations preserve existing prediction history.

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
