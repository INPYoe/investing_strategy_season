"""Reproducible replica hypotheses; never changes the investment optimizer.

Selection functions receive prices and a month, never reference entry/exit dates.
Holdouts are evaluated after training selection and cannot choose the winner.
"""
from dataclasses import asdict, replace
from datetime import date, timedelta
import argparse
import hashlib
from pathlib import Path

from lab import comparison, dataset, evaluate_profile, report_html
from seasonality import (all_windows, evaluate_window, objective_key,
                         profile_from_json, selection_stats, write_json)


def choose(pool, profile, origin="year", radius=0):
    def grid(row):
        day = row["entry_day"]
        coordinate = day if origin == "year" else (date(2001, 1, 1) + timedelta(days=day-1)).day - 1
        return (coordinate - profile.entry_offset) % profile.entry_step == 0

    def best(rows):
        scored = [(r, selection_stats(r, profile.selection_history)) for r in rows]
        scored = [(r, s) for r, s in scored if s]
        return max(scored, key=lambda x: objective_key(x[1], profile.objective))[0] if scored else None

    coarse = best([r for r in pool if grid(r)])
    if coarse is None or not radius:
        return coarse
    return best([r for r in pool if abs(r["entry_day"] - coarse["entry_day"]) <= radius])


def counts(details):
    return {"cases": len(details), "full": sum(r["all_match"] for r in details),
            "windows": sum(r["checks"]["entry_day"] and r["checks"]["hold_days"] for r in details),
            "fields": sum(sum(r["checks"].values()) for r in details)}


def training_key(metrics):
    return metrics["full"], metrics["windows"], metrics["fields"]


def rounding_bounds(series, samples, epsilon=0.00005):
    """Possible mean if each stored four-decimal price was rounded to nearest.

    This is a diagnostic bound, not a larger comparison tolerance.
    """
    prices = dict(zip(series.dates, series.prices))
    lower, upper = [], []
    for sample in samples:
        entry = prices[date.fromisoformat(sample["entry"])]
        exit = prices[date.fromisoformat(sample["exit"])]
        if entry <= epsilon:
            raise ValueError("Price too small for rounding interval")
        lower.append((exit-epsilon)/(entry+epsilon)-1)
        upper.append((exit+epsilon)/(entry-epsilon)-1)
    return [sum(lower)/len(lower), sum(upper)/len(upper)]


def diagnose(data, profile, period):
    details = []
    for ticker, prices, refs, cutoff in data:
        for expected in refs:
            fixed = evaluate_window(prices, expected["entry_day"], expected["hold_days"], cutoff, profile, period)
            pool = all_windows(prices, expected["month"], cutoff, replace(profile, entry_step=1), period)
            ranked = sorted(pool, key=lambda r: objective_key(selection_stats(r, profile.selection_history), profile.objective), reverse=True)
            target = (expected["entry_day"], expected["hold_days"])
            rank = next((i+1 for i, r in enumerate(ranked) if (r["entry_day"], r["hold_days"]) == target), None)
            bounds = rounding_bounds(prices, fixed["samples"]) if fixed else None
            price_map = dict(zip(prices.dates, prices.prices))
            samples = []
            for sample in fixed["samples"] if fixed else []:
                samples.append({**sample, "entry_price": price_map[date.fromisoformat(sample["entry"])],
                                "exit_price": price_map[date.fromisoformat(sample["exit"])],
                                "cross_year": sample["entry"][:4] != sample["exit"][:4]})
            details.append({"ticker": ticker, **comparison(expected, fixed),
                            "cutoff_exclusive": cutoff.isoformat(),
                            "candidate_in_current_grid": (expected["entry_day"]-profile.entry_offset) % profile.entry_step == 0 and expected["hold_days"] in profile.holds,
                            "daily_objective_rank": rank,
                            "rounding_mean_interval": bounds,
                            "difference_exceeds_price_rounding": bool(bounds) and not bounds[0] <= expected["avg_return"] <= bounds[1],
                            "samples": samples})
    return details


def run(args):
    base = profile_from_json(args.profile)
    groups = [("training", ["SPY", "QQQ", "AAPL"], 10),
              ("GLD_10", ["GLD"], 10), ("SPY_QQQ_5", ["SPY", "QQQ"], 5)]
    data = {name: dataset(args.evidence, tickers, period) for name, tickers, period in groups}
    hypotheses = [("baseline", base, "year", 0, None),
                  ("daily", replace(base, entry_step=1), "year", 0, None)]
    hypotheses += [(f"month_grid_{offset}", replace(base, entry_offset=offset), "month", 0, None) for offset in range(7)]
    hypotheses += [(f"year_grid_{offset}", replace(base, entry_offset=offset), "year", 0, None) for offset in range(7) if offset != base.entry_offset]
    hypotheses += [(f"refine_{radius}", base, "year", radius, None) for radius in (1, 2, 3)]
    hypotheses += [(f"selection_years_{years}", base, "year", 0, years) for years in (5, 10, 15, 20, 30)]
    hypotheses += [("holds_daily_30", replace(base, holds=tuple(range(1, 31))), "year", 0, None),
                   ("holds_daily_60", replace(base, holds=tuple(range(1, 61))), "year", 0, None)]
    cache = {}

    def evaluate(hypothesis, group, period):
        _, profile, origin, radius, selection_years = hypothesis
        details = []
        for ticker, prices, refs, cutoff in data[group]:
            for expected in refs:
                key = (group, ticker, expected["month"], profile.holds, selection_years or period)
                if key not in cache:
                    cache[key] = all_windows(prices, expected["month"], cutoff, replace(profile, entry_step=1), selection_years or period)
                chosen = choose(cache[key], profile, origin, radius)
                actual = evaluate_window(prices, chosen["entry_day"], chosen["hold_days"], cutoff, profile, period) if chosen else None
                details.append({"ticker": ticker, **comparison(expected, actual)})
        return details

    print(f"Evaluating {len(hypotheses)} training hypotheses...", flush=True)
    # Freeze the winner before reading any holdout scores.
    trials = [{"name": h[0], "profile": asdict(h[1]), "grid_origin": h[2], "refine_radius": h[3],
               "selection_years": h[4], "training": counts(evaluate(h, "training", 10))} for h in hypotheses]
    winner = max(range(len(trials)), key=lambda i: training_key(trials[i]["training"]))
    print(f"Training winner frozen: {trials[winner]['name']}; evaluating holdouts...", flush=True)
    for h, trial in zip(hypotheses, trials):
        trial["holdouts"] = {name: counts(evaluate(h, name, period)) for name, _, period in groups[1:]}
    reports = {}
    for name, _, period in groups:
        reports[name] = evaluate_profile(data[name], base, period)
        reports[name]["diagnostics"] = diagnose(data[name], base, period)
    evidence = Path(args.evidence)
    files = sorted({evidence / f"{ticker}_{suffix}.json" for _, tickers, period in groups for ticker in tickers for suffix in ("chart", f"optimal_{period}")})
    out = Path(args.out)
    write_json(out / "research.json", {"website": "https://easyinvesting.app/#/seasonality",
               "source": "Frozen website chart snapshots; not independent provider validation",
               "evidence_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
               "training_selected": trials[winner]["name"], "production_profile_changed": False,
               "selection_rule": "full, then window, then field matches on training only; ties preserve baseline",
               "trials": trials, "reports": reports, "replication_complete": False})
    for name, report in reports.items():
        write_json(out / f"{name}.json", report)
        report_html(out / f"{name}.html", report)
    print(f"{len(trials)} hypotheses; training winner: {trials[winner]['name']}")
    for name, report in reports.items():
        print(name, report["fully_matching_cases"], "/", report["cases"],
              "fixed averages", report["fixed_window_formula"]["average_matches"],
              "displayed", report["fixed_window_formula"]["displayed_average_matches"])
    return 2  # Research still does not establish full replica parity.


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default="evidence")
    parser.add_argument("--profile", default="results/best_profile.json")
    parser.add_argument("--out", default="results/research")
    raise SystemExit(run(parser.parse_args()))
