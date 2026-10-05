import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from seasonality import (PriceSeries, Profile, equal_weights, evaluate_window, event_schedule,
                        rejection_reasons, schedule_row, select_new, simulate, target_date)


def synthetic(ticker="A", end=date(2027, 3, 1)):
    dates = []
    d = date(2014, 1, 1)
    while d <= end:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    return PriceSeries(ticker, dates, [100 * 1.0001 ** i for i in range(len(dates))], "synthetic weekdays, NOT an exchange calendar")


def signal(ticker, kind="etf", entry="2026-10-05", exit="2026-10-15", score=.02):
    return {"ticker": ticker, "kind": kind, "entry": entry, "exit": exit,
            "median_return": score, "win_rate": .9, "worst_return": -.05}


class CalendarTests(unittest.TestCase):
    def test_leap_conventions_are_distinct(self):
        self.assertEqual(target_date(2024, 83, "doy"), date(2024, 3, 23))
        self.assertEqual(target_date(2024, 83, "month_day"), date(2024, 3, 24))

    def test_weekend_roll_and_trading_hold(self):
        prices = synthetic()
        row = evaluate_window(prices, 3, 5, date(2026, 10, 1), Profile())
        sample = next(s for s in row["samples"] if s["year"] == 2026)
        self.assertEqual(sample["entry"], "2026-01-05")
        self.assertEqual(sample["exit"], "2026-01-12")

    def test_cross_year(self):
        row = evaluate_window(synthetic(), 355, 30, date(2026, 10, 1), Profile())
        sample = next(s for s in row["samples"] if s["year"] == 2025)
        self.assertEqual(sample["exit"][:4], "2026")

    def test_unfinished_excluded(self):
        row = evaluate_window(synthetic(), 280, 25, date(2026, 10, 1), Profile())
        self.assertEqual(row["sample_count"], 10)
        self.assertNotIn(2026, [s["year"] for s in row["samples"]])

    def test_exact_ten_latest_observations(self):
        row = evaluate_window(synthetic(), 20, 20, date(2026, 10, 1), Profile(), mode="investment")
        self.assertEqual(row["sample_count"], 10)
        self.assertEqual(row["samples"][0]["year"], 2017)

    def test_no_future_price_leakage(self):
        prices = synthetic()
        cutoff = date(2026, 10, 1)
        a = evaluate_window(prices, 280, 25, cutoff, Profile(), mode="investment")
        changed = PriceSeries("A", prices.dates, [p if d < cutoff else p * 20 for d, p in zip(prices.dates, prices.prices)])
        b = evaluate_window(changed, 280, 25, cutoff, Profile(), mode="investment")
        self.assertEqual(a, b)

    def test_cutoff_is_exclusive(self):
        prices = synthetic()
        row = evaluate_window(prices, 3, 5, date(2026, 1, 12), Profile())
        self.assertNotIn(2026, [s["year"] for s in row["samples"]])

    def test_ipo_does_not_become_old_sample(self):
        prices = synthetic()
        i = prices.dates.index(date(2020, 7, 1))
        young = PriceSeries("YOUNG", prices.dates[i:], prices.prices[i:])
        self.assertIsNone(evaluate_window(young, 20, 10, date(2026, 10, 1), Profile(), mode="investment"))

    def test_insufficient_calendar_is_explicit(self):
        with self.assertRaises(ValueError):
            schedule_row({"entry_day": 280, "hold_days": 30}, 2026, [date(2026, 10, 7)], Profile())


class SelectionTests(unittest.TestCase):
    def test_asset_specific_win_thresholds(self):
        row = {"sample_count": 10, "win_rate": .8, "worst_return": -.1}
        etf = {"kind": "etf", "listing_country": "US", "leverage": 1, "inverse": False}
        stock = {"kind": "stock", "listing_country": "US"}
        self.assertEqual(rejection_reasons(row, etf), [])
        self.assertIn("win rate below threshold", rejection_reasons(row, stock))

    def test_minus_ten_boundary(self):
        asset = {"kind": "stock", "listing_country": "US"}
        row = {"sample_count": 10, "win_rate": .9, "worst_return": -.100001}
        self.assertIn("historical worst return below -10%", rejection_reasons(row, asset))

    def test_zero_returns_are_not_wins(self):
        prices = synthetic()
        flat = PriceSeries("A", prices.dates, [100] * len(prices.prices))
        self.assertEqual(evaluate_window(flat, 20, 10, date(2026, 10, 1), Profile())["win_rate"], 0)

    def test_unknown_or_leveraged_etfs_rejected(self):
        row = {"sample_count": 10, "win_rate": 1, "worst_return": 0}
        for asset in [{"kind": "etf", "listing_country": "US"},
                      {"kind": "etf", "listing_country": "US", "leverage": 2, "inverse": False}]:
            self.assertTrue(rejection_reasons(row, asset))

    def test_five_total_three_stocks(self):
        rows = [signal(str(i), "stock" if i < 6 else "etf", score=.1 - i * .001) for i in range(10)]
        selected = select_new(rows)
        self.assertEqual(len(selected), 5)
        self.assertEqual(sum(r["kind"] == "stock" for r in selected), 3)

    def test_median_not_mean_ranking(self):
        a, b = signal("A", score=.01), signal("B", score=.02)
        a["avg_return"], b["avg_return"] = .99, .03
        self.assertEqual(select_new([a, b])[0]["ticker"], "B")

    def test_no_duplicate_ticker(self):
        self.assertEqual(len(select_new([signal("A"), signal("A")])), 1)

    def test_single_asset_and_cash(self):
        self.assertEqual(equal_weights([signal("A")]), {"A": 1})
        self.assertEqual(equal_weights([]), {"CASH": 1})

    def test_incumbents_not_replaced(self):
        held = [signal(str(i)) for i in range(5)]
        self.assertEqual(select_new([signal("NEW", score=1)], held), [])

    def test_events_redistribute_then_cash(self):
        rows = [signal("A", exit="2026-10-08"), signal("B", exit="2026-10-15")]
        events = event_schedule(rows)
        self.assertEqual(events[0]["target_weights"], {"A": .5, "B": .5})
        self.assertEqual(events[1]["target_weights"], {"B": 1})
        self.assertEqual(events[2]["target_weights"], {"CASH": 1})

    def test_additions_do_not_extend_exit(self):
        events = event_schedule([signal("A", exit="2026-10-08"), signal("B", exit="2026-10-15")])
        self.assertEqual(events[1]["positions"][0]["exit"], "2026-10-15")

    def test_skipped_entry_not_admitted_late(self):
        signals = [signal(str(i), exit="2026-10-08") for i in range(5)]
        signals += [signal("NEW", entry="2026-10-06", exit="2026-10-15", score=1)]
        self.assertFalse(any("NEW" in e["entered"] for e in event_schedule(signals)))


class LedgerTests(unittest.TestCase):
    def test_no_cost_return_reconciles(self):
        dates = [date(2026, 10, d) for d in (5, 6, 7)]
        prices = {"A": PriceSeries("A", dates, [100, 110, 120])}
        events = event_schedule([signal("A", exit="2026-10-07")])
        result = simulate(events, prices, 1000)
        self.assertAlmostEqual(result["final"], 1200)
        self.assertAlmostEqual(result["ledger"][0]["cash"], 0)

    def test_both_sides_cost_and_self_financing(self):
        dates = [date(2026, 10, d) for d in (5, 6, 7)]
        prices = {"A": PriceSeries("A", dates, [100, 100, 100])}
        events = event_schedule([signal("A", exit="2026-10-07")])
        result = simulate(events, prices, 1000, 100)
        self.assertAlmostEqual(result["final"], 1000 / 1.01 * .99)
        self.assertAlmostEqual(sum(r["cost"] for r in result["ledger"]), 1000 - result["final"])

    def test_no_stop_loss(self):
        dates = [date(2026, 10, d) for d in (5, 6, 7)]
        prices = {"A": PriceSeries("A", dates, [100, 50, 120])}
        result = simulate(event_schedule([signal("A", exit="2026-10-07")]), prices, 1000)
        self.assertAlmostEqual(result["final"], 1200)
        self.assertAlmostEqual(result["max_drawdown"], -.5)

    def test_missing_held_quote_is_error(self):
        prices = {"A": PriceSeries("A", [date(2026, 10, 5), date(2026, 10, 7)], [100, 120]),
                  "B": PriceSeries("B", [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)], [100, 100, 100])}
        with self.assertRaises(ValueError):
            simulate(event_schedule([signal("A", exit="2026-10-07")]), prices, 1000)

    def test_empty_portfolio_cash(self):
        self.assertEqual(simulate([], {}, 1000)["final"], 1000)

    def test_invalid_prices_not_silently_accepted(self):
        for values in ([0], [float("nan")], [-1]):
            with self.assertRaises(ValueError):
                PriceSeries("A", [date(2026, 1, 1)], values)

    def test_duplicate_dates_rejected(self):
        with self.assertRaises(ValueError):
            PriceSeries("A", [date(2026, 1, 1)] * 2, [100, 101])


if __name__ == "__main__":
    unittest.main()
