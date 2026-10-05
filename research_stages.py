"""Test selection/display-date separation without target dates entering selection."""
import argparse
from dataclasses import asdict, replace
from datetime import date
import itertools
from statistics import mean, median

from lab import comparison, dataset
from research import counts, training_key
from seasonality import Profile, all_windows, evaluate_window, objective_key, selection_stats, write_json


def displayed_anchor(row, method):
    if method == "anchor":
        return row["entry_day"]
    entries = [date.fromisoformat(s["entry"]) for s in row["samples"]]
    days = [d.timetuple().tm_yday for d in entries]
    if method == "median_doy":
        value = int(median(days))
    elif method == "mean_doy":
        value = int(mean(days))
    elif method == "first_doy":
        value = days[0]
    elif method == "last_doy":
        value = days[-1]
    elif method == "median_md":
        value = int(median(date(2001, d.month, min(d.day, 28) if d.month == 2 else d.day).timetuple().tm_yday for d in entries))
    else:
        raise ValueError("Unknown display rule")
    return value if 1 <= value <= 365 else None


def select(pool, profile):
    scored = [(row, selection_stats(row, profile.selection_history)) for row in pool
              if (row["entry_day"]-profile.entry_offset) % profile.entry_step == 0]
    scored = [(row, score) for row, score in scored if score]
    return max(scored, key=lambda pair: objective_key(pair[1], profile.objective))[0] if scored else None


def run(args):
    training = dataset(args.evidence, ["SPY", "QQQ", "AAPL"])
    inputs = []
    if args.raw_cache:
        from research_dividends import price_data
        training, inputs = price_data(args, training)
    frozen_prices = {ticker: prices for ticker, prices, refs, cutoff in training}
    methods = ("anchor", "median_doy", "mean_doy", "first_doy", "last_doy", "median_md")
    objectives = ("win_mean", "win_daily", "mean", "sharpe", "win_median")
    grids = [(1, 0)] + [(7, offset) for offset in range(7)]
    reporting = Profile(cross_year_alignment=args.cross_year_alignment)
    trials = []
    best = None
    for date_mode, roll, hold_offset in itertools.product(("doy", "month_day"), ("next", "previous"), (0, -1)):
        base = Profile(date_mode=date_mode, roll=roll, hold_offset=hold_offset,
                       cross_year_alignment=args.cross_year_alignment)
        pools = {(ticker, ref["month"]): all_windows(prices, ref["month"], cutoff, base)
                 for ticker, prices, refs, cutoff in training for ref in refs}
        outputs = {}
        for ticker, prices, refs, cutoff in training:
            for ref in refs:
                for row in pools[ticker, ref["month"]]:
                    for method in methods:
                        day = displayed_anchor(row, method)
                        key = (ticker, day, row["hold_days"])
                        if day is not None and key not in outputs:
                            outputs[key] = evaluate_window(prices, day, row["hold_days"], cutoff, reporting)
        for policy, (step, offset), objective in itertools.product(("inclusive", "past_entry_years", "past_exit_years"), grids, objectives):
            profile = replace(base, selection_history=policy, entry_step=step, entry_offset=offset, objective=objective)
            chosen = {(ticker, ref["month"]): select(pools[ticker, ref["month"]], profile)
                      for ticker, prices, refs, cutoff in training for ref in refs}
            for method in methods:
                details = []
                for ticker, prices, refs, cutoff in training:
                    for ref in refs:
                        row = chosen[ticker, ref["month"]]
                        day = displayed_anchor(row, method) if row else None
                        actual = outputs.get((ticker, day, row["hold_days"])) if row and day else None
                        details.append({"ticker": ticker, **comparison(ref, actual)})
                metrics = counts(details)
                trial = {"selection_profile": asdict(profile), "display_rule": method, "reporting_profile": asdict(reporting), "training": metrics}
                trials.append(trial)
                if best is None or training_key(metrics) > training_key(best["training"]):
                    best = {**trial, "training_details": details}
        print(f"{date_mode}/{roll}/{hold_offset}: {len(trials)} trials; best {best['training']}", flush=True)
    # Holdout scores never participate in the winner selection above.
    holdouts = {}
    winner_profile = Profile(**{**best["selection_profile"], "holds": tuple(best["selection_profile"]["holds"])})
    for name, tickers, period in [("GLD_10", ["GLD"], 10), ("SPY_QQQ_5", ["SPY", "QQQ"], 5)]:
        details = []
        for ticker, prices, refs, cutoff in dataset(args.evidence, tickers, period):
            prices = frozen_prices.get(ticker, prices)
            for ref in refs:
                pool = all_windows(prices, ref["month"], cutoff, replace(winner_profile, entry_step=1), period)
                row = select(pool, winner_profile)
                day = displayed_anchor(row, best["display_rule"]) if row else None
                actual = evaluate_window(prices, day, row["hold_days"], cutoff, reporting, period) if row and day else None
                details.append({"ticker": ticker, **comparison(ref, actual)})
        holdouts[name] = {**counts(details), "details": details}
    write_json(args.out, {"model": "optimize on nominal anchor; store an observed entry date; refresh statistics on stored date",
                         "selection": "training only", "trials": trials, "winner": best,
                         "holdouts": holdouts, "price_inputs": inputs,
                         "production_changed": False, "replication_complete": False})
    print("winner", {k: v for k, v in best.items() if k != "training_details"})
    print("holdouts", {name: {k: v for k, v in report.items() if k != "details"} for name, report in holdouts.items()})
    return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default="evidence")
    parser.add_argument("--raw-cache")
    parser.add_argument("--raw-field", default="close")
    parser.add_argument("--universe", default="config/universe.example.json")
    parser.add_argument("--actions", default="evidence/actions")
    parser.add_argument("--append-raw-tail", action="store_true")
    parser.add_argument("--normalize-vintage", action="store_true")
    parser.add_argument("--cross-year-alignment", default="sessions", choices=("sessions", "leap_after_first_year"))
    parser.add_argument("--out", default="results/research/stages.json")
    raise SystemExit(run(parser.parse_args()))
