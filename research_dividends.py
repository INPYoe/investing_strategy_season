"""Replica price-basis hypothesis using issuer actions and an external Close anchor.

Stock price reconstruction does not read seasonality reference values. A raw tail
is an explicit, separately recorded hypothesis, never an acquisition fallback.
"""
import argparse
import hashlib
import itertools
import json
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path

from corporate_actions import reconstruct_close
from research_price_vintage import normalize_vintage
from lab import comparison, dataset, evaluate_profile, report_html
from research import counts, training_key
from research_stages import select
from seasonality import Profile, PriceSeries, all_windows, write_json


def stock_close(series, events, independent_close, start, append_raw_tail=False):
    raw_map = dict(zip(independent_close.dates, independent_close.prices))
    overlap = [d for d in series.dates if d in raw_map and d >= start]
    if not overlap:
        raise ValueError("No external Close anchor available")
    anchor = overlap[-1]
    begin = next(i for i, d in enumerate(series.dates) if d >= start)
    end = series.dates.index(anchor)+1
    prefix = PriceSeries(series.ticker, series.dates[begin:end], series.prices[begin:end])
    actions = [e for e in events if prefix.dates[0] < date.fromisoformat(e["ex_date"]) <= anchor]
    terminal_factor = prefix.prices[-1]/raw_map[anchor]
    reconstructed = reconstruct_close(prefix, actions, terminal_factor)
    lookup = dict(zip(reconstructed.dates, reconstructed.prices))
    errors = [lookup[d]-raw_map[d] for d in overlap]
    tail = series.prices[end:]
    if tail and not append_raw_tail:
        raise ValueError("Unverified website tail exists; explicit hypothesis flag required")
    # Record evidence for the tail hypothesis; do not turn it into proof of Close.
    cents = sum(abs(p*100-round(p*100)) < 1e-8 for p in tail)
    dates = series.dates[begin:] if append_raw_tail else prefix.dates
    prices = reconstructed.prices+tail if append_raw_tail else reconstructed.prices
    result = PriceSeries(series.ticker, dates, prices,
                         "Replica diagnostic: issuer-dividend reversal anchored to external Close; tail assumed raw",
                         "split-adjusted Close estimate", series.sha256)
    return result, {"anchor": anchor.isoformat(), "terminal_factor": terminal_factor,
                    "overlap_prices": len(errors), "max_abs_close_error": max(abs(e) for e in errors),
                    "tail_prices": len(tail), "tail_cent_aligned": cents,
                    "tail_policy": "assumed raw" if append_raw_tail else "excluded",
                    "full_independent_price_validation": False}


def calibrate(data, cross_year_alignment="sessions"):
    trials, best = [], None
    grids = [(1, 0)]+[(7, offset) for offset in range(7)]
    for dm, roll, offset in itertools.product(("doy", "month_day"), ("next", "previous"), (0, -1)):
        base = Profile(date_mode=dm, roll=roll, hold_offset=offset, cross_year_alignment=cross_year_alignment)
        pools = {(ticker, ref["month"]): all_windows(prices, ref["month"], cutoff, base)
                 for ticker, prices, refs, cutoff in data for ref in refs}
        for policy, (step, phase), objective in itertools.product(("inclusive", "past_entry_years", "past_exit_years"), grids,
                                                                 ("win_mean", "win_daily", "mean", "sharpe", "win_median")):
            profile = replace(base, selection_history=policy, entry_step=step, entry_offset=phase, objective=objective)
            details = [{"ticker": ticker, **comparison(ref, select(pools[ticker, ref["month"]], profile))}
                       for ticker, prices, refs, cutoff in data for ref in refs]
            metrics = counts(details)
            trial = {"iteration": len(trials)+1, "profile": asdict(profile), **metrics}
            trials.append(trial)
            if best is None or training_key(metrics) > training_key(best[0]):
                best = metrics, profile
        print(f"{len(trials)} price-basis trials; best {best[0]}", flush=True)
    return best[1], trials


def price_data(args, data):
    assets = json.loads(Path(args.universe).read_text())["assets"]
    inputs = []
    converted = []
    for ticker, series, refs, cutoff in data:
        if assets[ticker]["kind"] == "stock":
            action_path = Path(args.actions)/f"{ticker}_dividends.json"
            actions = json.loads(action_path.read_text())
            raw_path = Path(args.raw_cache)/f"{ticker}.csv"
            raw = PriceSeries.load(raw_path, ticker, args.raw_field)
            series, diagnostic = stock_close(series, actions["dividends"], raw,
                                              date(cutoff.year-getattr(args, 'price_lookback', 10), 1, 1), args.append_raw_tail)
            inputs.append({"ticker": ticker, **diagnostic, "actions_source": actions["source"],
                           "actions_sha256": hashlib.sha256(action_path.read_bytes()).hexdigest(),
                           "anchor_cache_sha256": raw.sha256})
        else:
            vintage_path = Path(args.actions)/f"{ticker}_vintage.json"
            if args.normalize_vintage and vintage_path.exists():
                vintage = json.loads(vintage_path.read_text())
                series, diagnostic = normalize_vintage(series, vintage['anchor'], vintage['events'],
                                                       vintage['quotes'], args.append_raw_tail)
                inputs.append({'ticker': ticker, **diagnostic, 'source': vintage['source'],
                               'input_sha256': hashlib.sha256(vintage_path.read_bytes()).hexdigest()})
            else:
                inputs.append({"ticker": ticker, "policy": "website chart adjusted-price snapshot"})
        converted.append((ticker, series, refs, cutoff))
    return converted, inputs


def run(args):
    converted, inputs = price_data(args, dataset(args.evidence, args.tickers))
    profile, trials = calibrate(converted)
    report = evaluate_profile(converted, profile)
    report.update({"price_basis_hypothesis": inputs, "iterations": len(trials), "trials": trials,
                   "production_optimizer_changed": False, "full_independent_validation": False})
    frozen_prices = {ticker: series for ticker, series, refs, cutoff in converted}
    held_data = [(ticker, frozen_prices.get(ticker, series), refs, cutoff)
                 for ticker, series, refs, cutoff in dataset(args.evidence, ["SPY", "QQQ"], 5)]
    holdouts = {"GLD_10": evaluate_profile(dataset(args.evidence, ["GLD"]), profile),
                "SPY_QQQ_5": evaluate_profile(held_data, profile, 5)}
    out = Path(args.out)
    write_json(out/"calibration.json", report)
    report_html(out/"comparison.html", report)
    for name, result in holdouts.items():
        write_json(out/f"{name}.json", result)
        report_html(out/f"{name}.html", result)
    write_json(out/"profile.json", {"profile": asdict(profile), "price_basis_hypothesis": inputs,
                                    "replication_complete": False, "holdouts": {name: {k: r[k] for k in ("cases", "fully_matching_cases", "window_matching_cases")} for name, r in holdouts.items()}})
    print("training", report["fully_matching_cases"], "/", report["cases"],
          "fixed averages", report["fixed_window_formula"]["average_matches"],
          "displayed", report["fixed_window_formula"]["displayed_average_matches"])
    return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default="evidence")
    parser.add_argument("--tickers", nargs="+", default=["SPY", "QQQ", "AAPL"])
    parser.add_argument("--universe", default="config/universe.example.json")
    parser.add_argument("--actions", default="evidence/actions")
    parser.add_argument("--raw-cache", required=True)
    parser.add_argument("--raw-field", default="Close")
    parser.add_argument("--append-raw-tail", action="store_true")
    parser.add_argument("--normalize-vintage", action="store_true")
    parser.add_argument("--out", default="results/research/dividends")
    raise SystemExit(run(parser.parse_args()))
