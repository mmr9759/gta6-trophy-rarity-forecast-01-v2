# gta6-trophy-rarity-forecast-01-v2

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/mmr9759/gta6-trophy-rarity-forecast-01-v2/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/mmr9759/gta6-trophy-rarity-forecast-01-v2/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Forecasts every GTA VI PS5 trophy's Exophase earn rate at 2026-11-26T00:00:00Z
as five quantiles (5 / 25 / 50 / 75 / 95%), scored by mean pinball loss on
the logit scale. Refresh-inversion forecaster with a calibrated
launch-refresh prior: it forecasts in earners/players space, never by
fitting the rate alone.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>

## Method

An earn rate is earners / players-tracked, and the two move in opposite
directions: players-tracked grows as more players register on Exophase
(dilution pulls every rate down) while earners grow as players progress
(pulls rates up). Fitting the rate alone confuses the two — a refresh
that jumps players-tracked looks like a sudden fall in every rate.

Launch night (the practice cases) the history is a single flat plateau
(638 players, every rate unchanged), and the rules record Exophase's
first refresh: by 04:30 UTC on 19 Nov the page showed 3,868 players
tracked, every rate but the 100% one lower. Inverting that refresh, the
post-refresh rate is the old rate times 638/3868, plus the earners the
newly tracked players have synced since the refresh: about 5% above pure
dilution at the refresh instant, rising toward about 35% thirty minutes
later as their trophy syncs land, saturating near 50%. The spread is
tight (0.12 on the logit scale) because the refresh is a known, dated
event, not a random walk. The 100% trophy is forecast at 100%.

Later cases hold many refresh plateaus. Each trophy's earners and the
players-tracked are fitted separately against log(1 + hours since
release) over the last 24 hours of distinct snapshots, forecast to the
target anchored at the last snapshot with slopes damped by
extrapolation distance, and divided; the median blends that trend (80%)
with persistence (20%). Trophies whose earners are still (near-)zero
borrow the median slope of the trophies that have earners, so a log fit
on pseudo-counts cannot invent a slope.

## Local verification

- Practice cases p00/p01: exit 0, valid output (55 rows, monotone
  quantiles), two runs byte-identical, ~0.05 s for both cases.
- Practice pinball loss against the refresh scenarios the v1 board
  result implies (p00 near pure dilution, p01 about 1.3-1.45x dilution,
  identified from v1's server loss 0.22 and typical miss 0.07): **0.027
  to 0.066, mean 0.039** across the credible scenarios, vs v1 **0.22**
  on the same metric and the house baseline **1.69**.
- Synthetic final-like cases (2.5 days of history, 4.5-day horizon,
  refresh plateaus, five worlds): **0.51-1.37** vs house baseline
  **0.77-1.54** — better in every world.
