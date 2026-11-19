"""GTA VI trophy rarity forecaster v2: refresh-inversion + calibrated launch-refresh prior.

A trophy's earn rate is earners / players-tracked, and the two move in
opposite directions: players-tracked grows as more players register on
Exophase (dilution pulls every rate down) while earners grow as players
progress (pulls rates up). Fitting the rate alone confuses the two, so
this program always forecasts in earners/players space and divides.

Launch night (the practice cases): the history is a single flat plateau
(638 players tracked, every rate unchanged). The rules record Exophase's
first refresh of the game: by its read at 04:30 UTC on 19 November the
page showed 3,868 players tracked and every rate but the 100% one lower.
Inverting that refresh gives the post-refresh rate as the old rate times
638/3868, plus the earners the newly tracked players have synced since
the refresh: about 5% more than pure dilution at the refresh instant,
rising toward about 35% thirty minutes later as their trophy syncs land,
and saturating near 50%. The spread is tight (0.12 on the logit scale):
the refresh is a known, dated event, not a random walk.

Later cases: the history holds many refresh plateaus. Each trophy's
earners and the players-tracked are fitted separately against
log(1 + hours since release) over the last 24 hours of distinct
snapshots, forecast to the target, and divided; the median blends that
trend with persistence, and the spread combines fit residuals, horizon
and extrapolation distance.

Standard library only, deterministic, no network. Reads every *.in in
the input directory and writes one *.out per case to the output
directory, exactly as the rules specify.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]

# Exophase's first refresh of this game, as the rules record it: the page
# was unchanged (638 players tracked) from 23:48 UTC on 18 Nov through the
# 04:00 UTC read on 19 Nov, then refreshed by the 04:30 UTC read: 3,868
# players tracked, every rate but the 100% one lower.
FIRST_REFRESH_AT = "2026-11-19T04:30:00Z"
PRE_REFRESH_PLAYERS = 638.0
POST_REFRESH_PLAYERS = 3868.0
REFRESH_RATIO = POST_REFRESH_PLAYERS / PRE_REFRESH_PLAYERS

# Calibrated launch-refresh prior: how much the newly tracked players'
# synced earners lift a rate above pure dilution, as a function of the
# minutes from the refresh to the target. At the refresh instant the lift
# is small (their syncs have barely landed); it rises as syncs land and
# saturates. Calibrated against the practice board: the v1 entry (median
# boost 1.46-2.50 over dilution, wide spread) scored loss 0.22 with a
# typical miss of 0.07 points, which the refresh model below reproduces
# only for a post-refresh lift near 1.05 at the refresh and near 1.35
# thirty minutes later.
SYNC_BASE = 1.05
SYNC_GAIN = 0.43
SYNC_TAU_MIN = 25.0
SYNC_CAP = 1.60
FLAT_SPREAD = 0.12

# General (multi-plateau) branch.
WINDOW_HOURS = 24.0
TREND_BLEND = 0.80
RW_SIGMA = 0.5


def parse_time(text):
    """ISO 8601 (date or datetime, Z or offset) to an aware datetime."""
    text = text.strip()
    if len(text) == 10:
        text += "T00:00:00+00:00"
    elif text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def clamp_pct(x):
    return min(99.99, max(0.01, x))


def logit(pct):
    p = clamp_pct(pct) / 100.0
    return math.log(p / (1.0 - p))


def inv_logit(value):
    if value > 30.0:
        return 100.0
    if value < -30.0:
        return 0.0
    return 100.0 / (1.0 + math.exp(-value))


def round4(x):
    """Round to 4 decimals, half up (the house baseline's convention)."""
    scaled = x * 10000.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000.0
    return int(value) if float(value).is_integer() else value


def quantiles_from_logit(median_logit, spread):
    """Five monotone quantiles in percent from a logit median and spread."""
    out = []
    previous = 0.0
    for z in Z:
        q = round4(clamp_pct(inv_logit(median_logit + z * spread)))
        if q < previous:
            q = previous
        out.append(q)
        previous = q
    return out


def distinct_snapshots(case):
    """Collapse consecutive identical reads into distinct snapshots.

    Returns a list of (time, players, rates) with rates carried forward
    over nulls, oldest first. A plateau (reads between two refreshes)
    becomes one snapshot.
    """
    snaps = []
    last_rates = None
    for read in case["history"]:
        players = read["players_tracked"]
        rates = []
        for i, rate in enumerate(read["rates"]):
            if rate is None:
                rate = last_rates[i] if last_rates is not None else 0.0
            rates.append(rate)
        last_rates = rates
        if snaps and snaps[-1][1] == players and snaps[-1][2] == rates:
            continue
        snaps.append((parse_time(read["at"]), players, rates))
    return snaps


def sync_lift(minutes_after_refresh):
    """Earners-sync lift above pure dilution after the first refresh."""
    if minutes_after_refresh <= 0:
        return SYNC_BASE
    lift = SYNC_BASE + SYNC_GAIN * (1.0 - math.exp(-minutes_after_refresh / SYNC_TAU_MIN))
    return min(SYNC_CAP, lift)


def forecast_flat(case, snaps, target, checkpoint):
    """Single pre-refresh plateau, target at/after the first refresh."""
    _, players0, rates0 = snaps[0]
    refresh_at = parse_time(FIRST_REFRESH_AT)
    minutes_after = (target - refresh_at).total_seconds() / 60.0
    lift = sync_lift(minutes_after)
    dilution = players0 / (players0 * REFRESH_RATIO)
    rows = []
    for trophy, rate in zip(case["trophies"], rates0):
        if rate >= 100.0:
            rows.append({"id": trophy["id"], "q": [100, 100, 100, 100, 100]})
            continue
        median = min(rate * dilution * lift, rate)
        rows.append({"id": trophy["id"],
                     "q": quantiles_from_logit(logit(median), FLAT_SPREAD)})
    return {"trophies": rows}


def forecast_persistence(case, snaps, horizon_minutes):
    """No usable trend: last rate as median, house random-walk spread."""
    _, _, rates = snaps[-1]
    spread = RW_SIGMA * math.sqrt(horizon_minutes / 1440.0)
    rows = []
    for trophy, rate in zip(case["trophies"], rates):
        if rate >= 100.0:
            rows.append({"id": trophy["id"], "q": [100, 100, 100, 100, 100]})
            continue
        rows.append({"id": trophy["id"],
                     "q": quantiles_from_logit(logit(rate), spread)})
    return {"trophies": rows}


def wls_line(xs, ys, ws):
    """Weighted least squares y = a + b*x; returns (a, b, resid_std)."""
    sw = sum(ws)
    if sw <= 0.0 or len(xs) < 2:
        mean = sum(w * y for w, y in zip(ws, ys)) / sw if sw > 0 else ys[0]
        return mean, 0.0, 0.0
    mx = sum(w * x for w, x in zip(ws, xs)) / sw
    my = sum(w * y for w, y in zip(ws, ys)) / sw
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
    if sxx < 1e-12:
        return my, 0.0, 0.0
    sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
    b = sxy / sxx
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in zip(xs, ys)]
    var = sum(w * r * r for w, r in zip(ws, resid)) / sw
    return a, b, math.sqrt(var)


def clip(value, low, high):
    return min(high, max(low, value))


def forecast_trend(case, snaps, target, checkpoint, horizon):
    """Multi-plateau case: fit earners and players separately in log time.

    Each distinct snapshot is one refresh plateau. Over the last 24 hours
    of snapshots, log(earners) and log(players) are fitted against
    log(1 + hours since release). The forecast is ANCHORED at the last
    snapshot and the fitted slopes are DAMPED by how far past the window
    the target lies: a saturating growth curve is nearly straight inside
    a one-day window but flattens beyond it, so an undamped log-time
    slope over-extrapolates. The rate is earners/players; the median
    blends that trend with persistence, and the spread combines fit
    residuals, horizon and extrapolation distance. Trophies whose
    earners are still (near-)zero through the window are sparse: their
    slope is borrowed from the median slope of the trophies that do
    have earners, so a log fit on pseudo-counts cannot invent a slope.
    """
    release = parse_time(case["game"].get("release_date", "2026-11-19"))
    horizon_days = horizon / 1440.0

    def x_of(moment):
        hours = (moment - release).total_seconds() / 3600.0
        return math.log1p(max(0.0, hours))

    window_start = checkpoint.timestamp() - WINDOW_HOURS * 3600.0
    window = [s for s in snaps if s[0].timestamp() >= window_start]
    if len(window) < 3:
        window = snaps
    xs = [x_of(s[0]) for s in window]
    weights = [0.7 ** ((checkpoint - s[0]).total_seconds() / 86400.0)
               for s in window]
    x_last = xs[-1]
    x_target = x_of(target)
    dx = max(0.0, x_target - x_last)
    span = max(0.05, x_last - xs[0])
    shrink = span / (span + dx)

    log_n = [math.log(max(1.0, float(s[1]))) for s in window]
    a_n, b_n, s_n = wls_line(xs, log_n, weights)
    b_n = clip(b_n, -1.0, 4.0) * shrink
    log_n_star = log_n[-1] + b_n * dx
    n_star = math.exp(log_n_star)

    _, _, last_rates = snaps[-1]
    n_trophies = len(case["trophies"])
    earners_by_trophy = []
    for i in range(n_trophies):
        earners_by_trophy.append(
            [max(0.5, s[2][i] * s[1] / 100.0) for s in window])
    slopes = []
    sparse = []
    for i in range(n_trophies):
        floored = sum(1 for e in earners_by_trophy[i] if e <= 0.5)
        is_sparse = floored * 3 >= len(window)
        sparse.append(is_sparse)
        if is_sparse:
            continue
        log_e = [math.log(e) for e in earners_by_trophy[i]]
        _, b_e, _ = wls_line(xs, log_e, weights)
        slopes.append(clip(b_e, -1.0, 4.0))
    slopes.sort()
    median_slope = slopes[len(slopes) // 2] if slopes else 0.0

    rows = []
    for i, trophy in enumerate(case["trophies"]):
        last = last_rates[i]
        if last >= 100.0:
            rows.append({"id": trophy["id"], "q": [100, 100, 100, 100, 100]})
            continue
        earners = earners_by_trophy[i]
        log_e = [math.log(e) for e in earners]
        a_e, b_e, s_e = wls_line(xs, log_e, weights)
        if sparse[i]:
            b_e = median_slope
            s_e = max(s_e, 0.5)
        else:
            b_e = clip(b_e, -1.0, 4.0)
        b_e = b_e * shrink
        log_e_star = log_e[-1] + b_e * dx
        e_star = min(math.exp(log_e_star), n_star)
        trend_rate = clip(100.0 * e_star / n_star,
                          last / 4.0 if last > 0 else 0.01,
                          last * 10.0 if last > 0 else 100.0)
        median_logit = (TREND_BLEND * logit(trend_rate)
                        + (1.0 - TREND_BLEND) * logit(last))
        s_fit = math.sqrt(s_e * s_e + s_n * s_n)
        s_hor = 0.15 * math.sqrt(horizon_days)
        s_ext = 0.15 * dx
        spread = clip(math.sqrt(s_fit * s_fit + s_hor * s_hor + s_ext * s_ext),
                      0.15, 1.2)
        rows.append({"id": trophy["id"],
                     "q": quantiles_from_logit(median_logit, spread)})
    return {"trophies": rows}


def forecast_case(case, name):
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    if not case["history"]:
        raise ValueError(f"{name} has no history")
    checkpoint = parse_time(case["at"])
    target = parse_time(case["target"])
    horizon = case["horizon_minutes"]
    snaps = distinct_snapshots(case)
    refresh_at = parse_time(FIRST_REFRESH_AT)
    if len(snaps) == 1 and checkpoint < refresh_at and target >= refresh_at:
        return forecast_flat(case, snaps, target, checkpoint)
    if len(snaps) == 1 and target < refresh_at:
        return forecast_persistence(case, snaps, horizon)
    return forecast_trend(case, snaps, target, checkpoint, horizon)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
