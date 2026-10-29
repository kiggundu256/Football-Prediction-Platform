# Football Prediction Platform

A Windows desktop prototype for football match analysis, forecast history and performance tracking.

## Current prototype
- PySide6 interface: Dashboard, Match Analysis, Prediction History and Performance Lab.
- Independent Poisson baseline for 1X2, over/under goals (1.5, 2.5, 3.5), BTTS and likely scorelines.
- Local SQLite forecast history. Every saved forecast creates a new record.
- Automated unit tests and a GitHub Actions Windows executable build.

## Data notice
The current fixture list and expected-goals values are illustrative demo inputs. No live football data provider is connected yet. Corners, injuries, lineups, referee effects and weather are not modelled yet. Do not treat demo outputs as real match forecasts. Accuracy reporting will wait for verified final results.

## Download the Windows build without installing Python
1. Open the repository Actions tab after a push or manually run the workflow.
2. Open the latest successful Windows desktop build run.
3. Under Artifacts, download FootballPredictionPlatform-Windows.
4. Extract the ZIP and launch FootballPredictionPlatform.exe.

The app is unsigned, so Windows may display a SmartScreen warning. Only run the build downloaded from your own repository.

## Roadmap
1. Verify free/low-cost provider coverage, especially Uganda Premier League, CAF competitions, results and corner statistics.
2. Add synchronized fixture/results data, source timestamps and data-quality checks.
3. Build historical team-form and corner models.
4. Settle saved forecasts against verified results; report Brier score, log loss and calibration.
5. Add trustworthy pre-kickoff injury, lineup, referee and weather context.
6. Add chronological backtesting and model-version comparisons.

Predictions are estimates, not guarantees.
