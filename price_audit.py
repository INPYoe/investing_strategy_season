"""Compare external CSV prices and available fixed-window samples without rescaling."""
import argparse
import hashlib
from datetime import date
from pathlib import Path
from statistics import median

from lab import dataset
from seasonality import PriceSeries, evaluate_window, profile_from_json, write_json


def audit(args):
    profile = profile_from_json(args.profile)
    reports = []
    for ticker, website, refs, cutoff in dataset(args.evidence, args.tickers, args.period):
        path = Path(args.data) / f"{ticker}.csv"
        external = {field: PriceSeries.load(path, ticker, field) for field in args.fields}
        website_prices = dict(zip(website.dates, website.prices))
        maps = {field: dict(zip(series.dates, series.prices)) for field, series in external.items()}
        shared = sorted(set(website_prices).intersection(*(set(m) for m in maps.values())))
        if not shared:
            raise ValueError(f"No overlapping dates for {ticker}")
        fields = {}
        for field, prices in maps.items():
            ratios = [website_prices[d]/prices[d] for d in shared]
            fields[field] = {"website_to_csv_ratio_min": min(ratios), "website_to_csv_ratio_median": median(ratios),
                             "website_to_csv_ratio_max": max(ratios),
                             "max_absolute_price_difference": max(abs(website_prices[d]-prices[d]) for d in shared)}
        windows = []
        for expected in refs:
            calculated = evaluate_window(website, expected["entry_day"], expected["hold_days"], cutoff, profile, args.period)
            samples = []
            for sample in calculated["samples"]:
                entry, exit = date.fromisoformat(sample["entry"]), date.fromisoformat(sample["exit"])
                if any(entry not in prices or exit not in prices for prices in maps.values()):
                    continue
                returns = {field: prices[exit]/prices[entry]-1 for field, prices in maps.items()}
                samples.append({**sample, "csv_returns": returns,
                                "return_differences": {field: value-sample["return"] for field, value in returns.items()}})
            windows.append({"month": expected["month"], "available_samples": len(samples),
                            "required_replica_samples": calculated["sample_count"], "samples": samples})
        reports.append({"ticker": ticker, "csv_path": str(path.resolve()),
                        "csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "website_sha256": website.sha256,
                        "overlapping_dates": len(shared), "first": shared[0].isoformat(), "last": shared[-1].isoformat(),
                        "fields": fields, "windows": windows})
    write_json(args.out, {"source_note": args.source_note, "prices_rescaled": False,
                         "full_period_independent_validation": False, "reports": reports})
    print(f"Saved partial price audit for {len(reports)} tickers to {args.out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--fields", nargs="+", default=["Close", "Adj Close"])
    parser.add_argument("--source-note", required=True)
    parser.add_argument("--evidence", default="evidence")
    parser.add_argument("--profile", default="results/best_profile.json")
    parser.add_argument("--period", type=int, default=10)
    parser.add_argument("--out", default="results/price_audit.json")
    audit(parser.parse_args())
