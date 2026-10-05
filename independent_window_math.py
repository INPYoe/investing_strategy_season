"""Small reference calculation, independent of seasonality.py and its caches.

This verifies implementation of the declared conventions, not the truth of an
unpublished website convention or the provenance of supplied prices.
"""
from datetime import date, timedelta
import math


def _middle(values):
    ordered = sorted(values)
    half = len(ordered) // 2
    return ordered[half] if len(ordered) % 2 else (ordered[half - 1] + ordered[half]) / 2


def _locate(dates, anchor, forward):
    # Separate binary search implementation; do not call PriceSeries.position.
    lo, hi = 0, len(dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if dates[mid] < anchor or (not forward and dates[mid] == anchor):
            lo = mid + 1
        else:
            hi = mid
    index = lo if forward else lo - 1
    if not 0 <= index < len(dates) or abs((dates[index] - anchor).days) > 7:
        return None
    return index


def calculate(dates, prices, ticker, day, hold, cutoff, convention, period=10, mode='replica'):
    if not 1 <= day <= 365 or period < 1 or mode not in ('replica', 'investment'):
        raise ValueError('Invalid reference calculation input')
    offset = convention.get('hold_offset', 0)
    if hold + offset < 1:
        raise ValueError('Holding interval must be positive')
    samples = []
    template = date(2001, 1, 1) + timedelta(days=day - 1)
    for year in range(cutoff.year - period, cutoff.year + 1):
        anchor = (date(year, 1, 1) + timedelta(days=day - 1)
                  if convention.get('date_mode', 'doy') == 'doy'
                  else date(year, template.month, template.day))
        buy = _locate(dates, anchor, convention.get('roll', 'next') == 'next')
        if buy is None:
            continue
        sell = buy + hold + offset
        if sell >= len(dates):
            continue
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        if (mode == 'replica' and convention.get('cross_year_alignment') == 'leap_after_first_year'
                and year != cutoff.year - period and leap and dates[sell].year > year):
            sell += 1
        if sell >= len(dates) or dates[sell] >= cutoff:
            continue
        samples.append({'year': year, 'entry': dates[buy].isoformat(), 'exit': dates[sell].isoformat(),
                        'return': prices[sell] / prices[buy] - 1})
    if mode == 'investment':
        samples = samples[-period:]
        if len(samples) != period:
            return None
    if not samples:
        return None
    rates = [sample['return'] for sample in samples]
    average = math.fsum(rates) / len(rates)
    variance = math.fsum((r - average) ** 2 for r in rates) / len(rates)
    exit_days = [(date.fromisoformat(s['exit']) - date(int(s['exit'][:4]), 1, 1)).days + 1
                 for s in samples]
    return {'ticker': ticker, 'month': template.month, 'entry_day': day, 'hold_days': hold,
            'exit_day': int(_middle(exit_days)), 'avg_return': average,
            'median_return': _middle(rates), 'worst_return': min(rates), 'std': math.sqrt(variance),
            'win_rate': sum(r > 0 for r in rates) / len(rates),
            'sample_count': len(samples), 'samples': samples, 'asof_year': cutoff.year}


def objective(row, name, policy='inclusive'):
    samples = row['samples']
    if policy != 'inclusive':
        samples = [s for s in samples if (s['year'] if policy == 'past_entry_years'
                    else int(s['exit'][:4])) < row['asof_year']]
    if not samples:
        return None
    rates = [s['return'] for s in samples]
    average = math.fsum(rates) / len(rates)
    win = sum(r > 0 for r in rates) / len(rates)
    middle = _middle(rates)
    if name == 'win_mean':
        return win, average
    if name == 'win_daily':
        return win, average / row['hold_days']
    if name == 'win_median':
        return win, middle
    if name == 'median':
        return middle, win, min(rates)
    if name == 'mean':
        return average,
    if name == 'sharpe':
        std = math.sqrt(math.fsum((r - average) ** 2 for r in rates) / len(rates))
        return average / max(std, 1e-12),
    raise ValueError('Unknown objective')


def signature(row):
    return tuple((s['year'], s['entry'], s['exit']) for s in row['samples']) if row else None


def path_metrics(dates, prices, row, indices=None):
    if indices is None:
        indices = {d.isoformat(): i for i, d in enumerate(dates)}
    observations = []
    for sample in row['samples']:
        first, last = indices[sample['entry']], indices[sample['exit']]
        path = prices[first:last + 1]
        peak = path[0]
        drawdowns = []
        for value in path:
            peak = max(peak, value)
            drawdowns.append(value / peak - 1)
        daily = [b / a - 1 for a, b in zip(path, path[1:])]
        daily_mean = math.fsum(daily) / len(daily)
        observations.append({'year': sample['year'], 'entry': sample['entry'], 'exit': sample['exit'],
                             'max_drawdown': min(drawdowns),
                             'worst_from_entry': min(value / path[0] - 1 for value in path),
                             'daily_volatility': math.sqrt(math.fsum((x - daily_mean) ** 2 for x in daily) / len(daily))})
    return {'worst_path_drawdown': min(x['max_drawdown'] for x in observations),
            'mean_path_drawdown': math.fsum(x['max_drawdown'] for x in observations) / len(observations),
            'worst_intrahold_from_entry': min(x['worst_from_entry'] for x in observations),
            'mean_daily_volatility': math.fsum(x['daily_volatility'] for x in observations) / len(observations),
            'details': observations, 'basis': 'supplied price path; cash dividends are not separately credited'}
