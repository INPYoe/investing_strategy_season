"""Explicit adjusted-prefix/raw-tail reconciliation, without reference outcomes."""
from datetime import date
from seasonality import PriceSeries


def normalize_vintage(series, anchor, events, quotes, assume_raw_tail=False):
    if not assume_raw_tail:
        raise ValueError("Raw tail assumption must be explicit")
    anchor = date.fromisoformat(anchor)
    raw = dict(zip(series.dates, series.prices))
    independent = {date.fromisoformat(q['date']): q['close'] for q in quotes}
    replacements = []
    for d, p in independent.items():
        if d > anchor and d in raw:
            if raw[d] != p:
                replacements.append({'date': d.isoformat(), 'website': raw[d], 'independent_close': p})
            raw[d] = p
    factors = []
    for event in events:
        ex = date.fromisoformat(event['ex_date'])
        if not anchor < ex <= series.dates[-1]:
            raise ValueError("Actions must be after the prefix anchor and inside the series")
        i = series.dates.index(ex)
        previous = series.dates[i-1]
        if previous not in independent:
            raise ValueError("Independent pre-ex Close is required")
        factor = 1-event['cash']/independent[previous]
        if not 0 < factor <= 1:
            raise ValueError("Invalid dividend factor")
        factors.append((ex, factor))
    prices = []
    for d in series.dates:
        p = raw[d]
        for ex, factor in factors:
            if d < ex:
                p *= factor
        prices.append(p)
    return PriceSeries(series.ticker, series.dates, prices,
                       'Diagnostic adjusted prefix plus explicitly assumed raw tail',
                       'reconciled Adj Close estimate', series.sha256), {
        'anchor': anchor.isoformat(), 'tail_policy': 'assumed raw except independent quotes',
        'independent_quotes': len(independent), 'replacements': replacements,
        'factors': [{'ex_date': d.isoformat(), 'factor': f} for d, f in factors],
        'full_independent_price_validation': False}
