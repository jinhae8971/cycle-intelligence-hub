# Cycle Intelligence Hub

Cycle Intelligence Hub is the central dashboard for market-cycle systems under
the `jinhae8971` GitHub account. It uses GitHub Actions for scheduled
aggregation and GitHub Pages for static publishing.

## What It Does

- Reads subsystem definitions from `registry.yaml`.
- Fetches each subsystem's published `latest.json`.
- Normalizes cycle scores where available.
- Saves combined JSON artifacts in `data/`.
- Publishes a static dashboard from `docs/site/`.
- Optionally sends one Telegram summary per run.

## Architecture

```text
cycle-intelligence-hub
  .github/workflows/hub-pipeline.yml  Scheduled runner and Pages deploy
  registry.yaml                       Subsystem registry
  scripts/run_hub.py                  Aggregation pipeline
  data/hub_summary.json               Latest combined state
  data/hub_history.json               Daily score history
  data/snapshots/                     Daily archives
  docs/site/index.html                GitHub Pages dashboard
```

## Registered Systems

The hub currently monitors:

- Crypto Cycle Intelligence
- AI / Semiconductor Cycle Intelligence
- KOSPI Valuation Radar
- US Valuation Radar

Systems with a `score_path` are included in score averages, spread, phase
classification, and history charts. Systems without a score are still monitored
for reachability, freshness, and summary metrics.

## Operations

The workflow runs daily at `22:10 UTC`, which is `07:10 KST`.

Manual runs are available from:

```text
https://github.com/jinhae8971/cycle-intelligence-hub/actions/workflows/hub-pipeline.yml
```

The published dashboard is:

```text
https://jinhae8971.github.io/cycle-intelligence-hub/
```

## Required GitHub Settings

In the repository settings, enable GitHub Pages with:

- Source: GitHub Actions

Optional Telegram notifications require these repository secrets:

- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

## Adding a System

Append a new item to `registry.yaml`:

```yaml
- id: example
  name: "Example System"
  asset_class: "Equities"
  description: "Short description."
  label: "EX"
  color: "#4d8df7"
  data_url: "https://jinhae8971.github.io/example-system/data/latest.json"
  dashboard_url: "https://jinhae8971.github.io/example-system/"
  score_path: "score.composite"
  phase_path: "score.phase"
  dimensions_path: "score.dimensions"
  generated_at_paths:
    - "generated_at"
```

If the system does not expose a normalized 0-100 score yet, omit `score_path`.
It will be monitored as a status-only system until a score is added.
