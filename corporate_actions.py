"""Reverse cash-dividend adjustment using independently sourced actions.

This creates diagnostic split-adjusted Close estimates, not independent prices.
Reference seasonality results are never inputs to the reconstruction.
"""
import bisect
from datetime import date, timedelta

from seasonality import PriceSeries


def delivery_sessions(exchange_sessions):
    excluded = set()
    for year in {d.year for d in exchange_sessions}:
        veterans = date(year, 11, 11)
        if veterans.weekday() == 6:
            veterans += timedelta(days=1)
        excluded.add(veterans)
        october = date(year, 10, 1)
        excluded.add(october + timedelta(days=(0-october.weekday()) % 7 + 7))
    return [d for d in exchange_sessions if d not in excluded]


def infer_ex_date(record_date, sessions):
    """Ordinary US cash dividend convention; exchange-designated dates prevail."""
    settlement_days = 3 if record_date < date(2017, 9, 5) else 2 if record_date < date(2024, 5, 28) else 1
    i = bisect.bisect_right(sessions, record_date)-1
    j = i-(settlement_days-1)
    if j < 0:
        raise ValueError("Delivery calendar does not cover record date")
    return sessions[j]


def reconstruct_close(adjusted, dividends, terminal_factor=1.0):
    """Dividend cash amounts must already be split-adjusted to price share units.

    A_before = (P_before - cash) * factor_after, so factor_before
    = factor_after * A_before / (A_before + cash * factor_after).
    """
    if terminal_factor <= 0:
        raise ValueError("terminal_factor must be positive")
    event_map = {}
    for event in dividends:
        day = date.fromisoformat(event["ex_date"])
        amount = float(event["cash_per_price_share"])
        if amount < 0:
            raise ValueError("Negative dividend amount")
        if day > adjusted.dates[-1]:
            raise ValueError("Dividend lies beyond terminal observation")
        i = bisect.bisect_left(adjusted.dates, day)
        if i == 0 or i >= len(adjusted.dates) or adjusted.dates[i] != day:
            raise ValueError("Ex-date must be an observed session with a previous price")
        event_map[i] = event_map.get(i, 0)+amount
    factor = terminal_factor
    close = [0.0]*len(adjusted.dates)
    for i in range(len(close)-1, -1, -1):
        close[i] = adjusted.prices[i]/factor
        if i in event_map:
            before = adjusted.prices[i-1]
            factor = factor*before/(before+event_map[i]*factor)
    return PriceSeries(adjusted.ticker, adjusted.dates, close,
                       "Diagnostic dividend reversal of website adjusted prices; not independently acquired Close",
                       "reconstructed split-adjusted Close", adjusted.sha256)
