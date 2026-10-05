"""Independent seasonality calculations. All rates are decimals, not percentages."""
from __future__ import annotations

import bisect
import calendar
import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median, pstdev


@dataclass(frozen=True)
class Profile:
    date_mode: str = "doy"
    roll: str = "next"
    hold_offset: int = 0
    entry_step: int = 1
    entry_offset: int = 0
    objective: str = "win_mean"
    selection_history: str = "inclusive"
    # This finite search grid is a replication hypothesis, not an investment cap.
    holds: tuple[int, ...] = (5, 10, 15, 20, 25, 30)
    # Research-only observed year-boundary behavior. Investment mode never uses it.
    cross_year_alignment: str = "sessions"

    def __post_init__(self):
        if self.date_mode not in ("doy", "month_day") or self.roll not in ("next", "previous"):
            raise ValueError("Unknown date/holiday convention")
        if self.objective not in ("win_mean", "win_daily", "mean", "sharpe", "win_median", "median"):
            raise ValueError("Unknown objective")
        if self.selection_history not in ("inclusive", "past_entry_years", "past_exit_years"):
            raise ValueError("Unknown selection history")
        if self.cross_year_alignment not in ("sessions", "leap_after_first_year"):
            raise ValueError("Unknown year-boundary alignment")
        if self.entry_step < 1 or not self.holds or min(self.holds) + self.hold_offset < 1:
            raise ValueError("Invalid search grid")


@dataclass
class PriceSeries:
    ticker: str
    dates: list[date]
    prices: list[float]
    source: str = "user CSV"
    price_field: str = "Close"
    sha256: str = ""

    def __post_init__(self):
        if len(self.dates) != len(self.prices) or not self.dates:
            raise ValueError("Empty or unequal price/date arrays")
        if any(b <= a for a, b in zip(self.dates, self.dates[1:])):
            raise ValueError("Dates must be unique and strictly increasing")
        if any(not math.isfinite(p) or p <= 0 for p in self.prices):
            raise ValueError("Prices must be finite and positive")

    @classmethod
    def load(cls, path: str | Path, ticker: str | None = None, field: str = "Close"):
        path = Path(path)
        payload = path.read_bytes()
        if path.suffix.lower() == ".json":
            obj = json.loads(payload)
            candles = obj["candles"]
            chosen = field.lower().replace(" ", "_")
            rows = [(date.fromisoformat(x["date"][:10]), float(x[chosen])) for x in candles]
            symbol = ticker or obj.get("ticker", path.stem.split("_")[0])
            source = obj.get("source", "easyinvesting public chart snapshot; calibration only")
        else:
            records = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
            rows = [(date.fromisoformat(x.get("Date", x.get("date", ""))[:10]), float(x[field])) for x in records]
            symbol = ticker or path.stem
            source = "independent CSV"
        rows.sort()
        return cls(symbol.upper(), [r[0] for r in rows], [r[1] for r in rows], source, field,
                   hashlib.sha256(payload).hexdigest())

    def position(self, target: date, roll: str = "next") -> int | None:
        i = bisect.bisect_left(self.dates, target) if roll == "next" else bisect.bisect_right(self.dates, target) - 1
        if i < 0 or i >= len(self.dates) or abs((self.dates[i] - target).days) > 7:
            return None
        return i


def target_date(year: int, day: int, mode: str) -> date:
    if not 1 <= day <= 365:
        raise ValueError("entry_day must be 1..365")
    if mode == "doy":
        return date(year, 1, 1) + timedelta(days=day - 1)
    template = date(2001, 1, 1) + timedelta(days=day - 1)
    return date(year, template.month, template.day)


def md(day: int) -> str:
    return (date(2001, 1, 1) + timedelta(days=(day - 1) % 365)).strftime("%m-%d")


def summarize(samples: list[dict]) -> dict | None:
    if not samples:
        return None
    rates = [s["return"] for s in samples]
    return {"avg_return": mean(rates), "median_return": median(rates), "worst_return": min(rates),
            "win_rate": sum(r > 0 for r in rates) / len(rates), "sample_count": len(rates),
            "std": pstdev(rates), "samples": samples}


def evaluate_window(series: PriceSeries, day: int, hold: int, asof: date, profile: Profile,
                    lookback: int = 10, mode: str = "replica") -> dict | None:
    if mode not in ("replica", "investment"):
        raise ValueError("mode must be replica or investment")
    if lookback < 1:
        raise ValueError("lookback must be positive")
    samples = []
    # Replica models the observed inclusive calendar-year range. Investment
    # retains only the latest ten completed observations inside this range.
    for year in range(asof.year - lookback, asof.year + 1):
        anchor = target_date(year, day, profile.date_mode)
        i = series.position(anchor, profile.roll)
        if i is None:
            continue
        j = i + hold + profile.hold_offset
        if (mode == "replica" and profile.cross_year_alignment == "leap_after_first_year"
                and year > asof.year-lookback and calendar.isleap(year)
                and j < len(series.dates) and series.dates[j].year > year):
            j += 1
        if j >= len(series.dates) or series.dates[j] >= asof:
            continue
        # Avoid treating an IPO later in the year as a January observation.
        if abs((series.dates[i] - anchor).days) > 7:
            continue
        samples.append({"year": year, "entry": series.dates[i].isoformat(),
                        "exit": series.dates[j].isoformat(), "return": series.prices[j] / series.prices[i] - 1})
    if mode == "investment":
        samples = samples[-lookback:]
        if len(samples) != lookback:
            return None
    stats = summarize(samples)
    if stats is None:
        return None
    # Median exit day is an explicitly unverified display-date hypothesis.
    exits = [date.fromisoformat(s["exit"]).timetuple().tm_yday for s in samples]
    exit_day = int(median(exits))
    return {"ticker": series.ticker, "month": (date(2001, 1, 1) + timedelta(days=day - 1)).month,
            "entry_day": day, "entry_md": md(day), "exit_day": exit_day, "exit_md": md(exit_day),
            "hold_days": hold, "asof_year": asof.year, **stats}


def selection_stats(row: dict, policy: str) -> dict | None:
    if policy == "inclusive":
        return row
    key = "year" if policy == "past_entry_years" else "exit"
    samples = [s for s in row["samples"] if (s[key] if key == "year" else int(s[key][:4])) < row["asof_year"]]
    stats = summarize(samples)
    return {**row, **stats} if stats else None


def objective_key(row: dict, objective: str):
    if objective == "win_mean":
        return row["win_rate"], row["avg_return"]
    if objective == "win_daily":
        return row["win_rate"], row["avg_return"] / row["hold_days"]
    if objective == "win_median":
        return row["win_rate"], row["median_return"]
    if objective == "median":
        return row["median_return"], row["win_rate"], row["worst_return"]
    if objective == "sharpe":
        return row["avg_return"] / max(row["std"], 1e-12)
    return row["avg_return"]


def all_windows(series: PriceSeries, month: int, asof: date, profile: Profile,
                lookback: int = 10, mode: str = "replica") -> list[dict]:
    if not 1 <= month <= 12:
        raise ValueError("month must be 1..12")
    rows = []
    for day in range(1, 366):
        if (date(2001, 1, 1) + timedelta(days=day - 1)).month != month:
            continue
        if (day - profile.entry_offset) % profile.entry_step:
            continue
        for hold in profile.holds:
            row = evaluate_window(series, day, hold, asof, profile, lookback, mode)
            if row:
                rows.append(row)
    return rows


def optimize(series: PriceSeries, month: int, asof: date, profile: Profile,
             lookback: int = 10, mode: str = "replica") -> dict | None:
    rows = all_windows(series, month, asof, profile, lookback, mode)
    scored = [(r, selection_stats(r, profile.selection_history)) for r in rows]
    scored = [(r, score) for r, score in scored if score]
    return max(scored, key=lambda x: objective_key(x[1], profile.objective))[0] if scored else None


def rejection_reasons(row: dict, asset: dict) -> list[str]:
    reasons = []
    kind = asset.get("kind")
    if asset.get("listing_country") != "US" or kind not in ("stock", "etf"):
        reasons.append("unsupported universe")
    if kind == "etf" and (asset.get("leverage") != 1 or asset.get("inverse") is not False):
        reasons.append("leverage/inverse classification missing or excluded")
    if row["sample_count"] != 10:
        reasons.append("requires exactly 10 completed samples")
    if row["win_rate"] + 1e-12 < (0.9 if kind == "stock" else 0.8):
        reasons.append("win rate below threshold")
    if row["worst_return"] < -0.1 - 1e-12:
        reasons.append("historical worst return below -10%")
    return reasons


def select_new(candidates: list[dict], held: list[dict] | None = None) -> list[dict]:
    held = held or []
    if len(held) > 5 or sum(x["kind"] == "stock" for x in held) > 3:
        raise ValueError("Existing positions exceed agreed limits")
    symbols = {x["ticker"] for x in held}
    stocks = sum(x["kind"] == "stock" for x in held)
    slots = 5 - len(held)
    selected = []
    for row in sorted(candidates, key=lambda x: (-x["median_return"], -x["win_rate"], -x["worst_return"], x["ticker"])):
        if row["ticker"] in symbols or (row["kind"] == "stock" and stocks >= 3):
            continue
        if len(selected) >= slots:
            break
        selected.append(row)
        symbols.add(row["ticker"])
        stocks += row["kind"] == "stock"
    return selected


def equal_weights(positions: list[dict]) -> dict:
    return {x["ticker"]: 1 / len(positions) for x in positions} if positions else {"CASH": 1.0}


def schedule_row(row: dict, target_year: int, sessions: list[date], profile: Profile) -> dict:
    anchor = target_date(target_year, row["entry_day"], profile.date_mode)
    i = bisect.bisect_left(sessions, anchor) if profile.roll == "next" else bisect.bisect_right(sessions, anchor) - 1
    j = i + row["hold_days"] + profile.hold_offset
    if i < 0 or j >= len(sessions) or abs((sessions[i] - anchor).days) > 7:
        raise ValueError("Need an exchange-session calendar covering the entire proposed holding period")
    return {**row, "entry": sessions[i].isoformat(), "exit": sessions[j].isoformat()}


def event_schedule(signals: list[dict]) -> list[dict]:
    """Enter on original signal date only. Keep incumbents through fixed exit."""
    events = sorted({s[k] for s in signals for k in ("entry", "exit")})
    held = []
    output = []
    for day in events:
        exited = [x for x in held if x["exit"] == day]
        held = [x for x in held if x["exit"] > day]
        incoming = [x for x in signals if x["entry"] == day]
        admitted = select_new(incoming, held)
        held.extend(admitted)
        if exited or admitted:
            output.append({"date": day, "exited": [x["ticker"] for x in exited],
                           "entered": [x["ticker"] for x in admitted],
                           "positions": [dict(x) for x in held], "target_weights": equal_weights(held)})
    return output


def simulate(events: list[dict], prices: dict[str, PriceSeries], initial: float = 10000,
             cost_bps: float = 0) -> dict:
    """Fractional-share, close-price ledger; commission+slippage charged per side."""
    if initial <= 0 or not 0 <= cost_bps < 10000:
        raise ValueError("Invalid initial capital or trading costs")
    fee = cost_bps / 10000
    holdings = {}
    cash = initial
    lookup = {t: dict(zip(s.dates, s.prices)) for t, s in prices.items()}
    event_map = {date.fromisoformat(e["date"]): e for e in events}
    if not events:
        return {"initial": initial, "final": initial, "return": 0, "max_drawdown": 0, "ledger": []}
    start, end = min(event_map), max(event_map)
    # Require actual quotes for every held security. Never silently ffill gaps.
    days = sorted({d for s in prices.values() for d in s.dates if start <= d <= end})
    if not set(event_map).issubset(days):
        raise ValueError("An event falls on a date without price observations")
    ledger = []
    peak = initial
    max_dd = 0.0
    for day in days:
        event = event_map.get(day)
        needed = set(holdings)
        if event:
            needed |= set(event["target_weights"]) - {"CASH"}
        if any(day not in lookup[t] for t in needed):
            raise ValueError(f"Missing held-security quote on {day}")
        values = {t: q * lookup[t][day] for t, q in holdings.items()}
        before = cash + sum(values.values())
        cost = turnover = 0.0
        if event:
            weights = {t: w for t, w in event["target_weights"].items() if t != "CASH"}
            if weights:
                # Solve post-fee equity = pre-fee equity - fee * turnover.
                lo, hi = 0.0, before
                universe = set(values) | set(weights)
                for _ in range(60):
                    net = (lo + hi) / 2
                    turnover = sum(abs(net * weights.get(t, 0) - values.get(t, 0)) for t in universe)
                    if net + fee * turnover > before:
                        hi = net
                    else:
                        lo = net
                net = (lo + hi) / 2
                turnover = sum(abs(net * weights.get(t, 0) - values.get(t, 0)) for t in universe)
                cost = fee * turnover
                holdings = {t: net * w / lookup[t][day] for t, w in weights.items()}
                cash = max(0, before - net - cost)
            else:
                turnover = sum(values.values())
                cost = fee * turnover
                holdings = {}
                cash = before - cost
        nav = cash + sum(q * lookup[t][day] for t, q in holdings.items())
        peak = max(peak, nav)
        max_dd = min(max_dd, nav / peak - 1)
        ledger.append({"date": day.isoformat(), "equity": nav, "cash": cash, "cost": cost,
                       "turnover": turnover, "shares": dict(holdings), "event": bool(event)})
    final = ledger[-1]["equity"]
    return {"initial": initial, "final": final, "return": final / initial - 1,
            "max_drawdown": max_dd, "cost_bps_per_side": cost_bps, "ledger": ledger}


def write_json(path: str | Path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def profile_from_json(path: str | Path) -> Profile:
    obj = json.loads(Path(path).read_text())
    if "profile" in obj:
        obj = obj["profile"]
    if "holds" in obj:
        obj["holds"] = tuple(obj["holds"])
    return Profile(**obj)
