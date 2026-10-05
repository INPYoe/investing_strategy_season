"""Global candidate grids anchored to observed exchange sessions, not targets."""
import argparse
import bisect
import csv
from datetime import date
from dataclasses import replace

from lab import comparison, dataset
from research import counts, training_key
from research_dividends import price_data
from research_stages import displayed_anchor
from seasonality import Profile, all_windows, evaluate_window, objective_key, selection_stats, target_date, write_json


def grid_position(series, sessions, row, cutoff, rule, period, series_start=None):
    origin, year_offset, step, phase = rule
    year = cutoff.year + year_offset if year_offset != 'first' else cutoff.year-period
    anchor = target_date(year, row['entry_day'], 'doy')
    if origin == 'weekday':
        return anchor.weekday() == phase
    i = bisect.bisect_left(sessions, anchor)
    if i >= len(sessions):
        return False
    if origin == 'series':
        first = bisect.bisect_left(sessions, series_start or series.dates[0])
    elif origin == 'year':
        first = bisect.bisect_left(sessions, date(year, 1, 1))
    elif origin == 'month':
        first = bisect.bisect_left(sessions, date(year, anchor.month, 1))
    else:
        raise ValueError('Unknown grid origin')
    return (i-first) % step == phase


def select(pool, series, sessions, cutoff, rule, profile, period, series_start=None):
    scored = [(row, selection_stats(row, profile.selection_history)) for row in pool
              if grid_position(series, sessions, row, cutoff, rule, period, series_start)]
    scored = [(row, stats) for row, stats in scored if stats]
    return max(scored, key=lambda pair: objective_key(pair[1], profile.objective))[0] if scored else None


def run(args):
    training, inputs = price_data(args, dataset(args.evidence, ['SPY', 'QQQ', 'AAPL']))
    with open(args.calendar) as stream:
        sessions = [date.fromisoformat(row['Date']) for row in csv.DictReader(stream)]
    # Series origin requires full history so the first-session phase is factual.
    originals = dataset(args.evidence, ['SPY','QQQ','AAPL','GLD'])
    origins = {ticker: series.dates[0] for ticker, series, _, _ in originals}
    earliest = min(origins.values())
    if sessions[0] > earliest:
        # Observed full-history sessions are available in these frozen charts.
        historic = [d for _, series, _, _ in originals for d in series.dates]
        sessions = sorted(set(historic+sessions))
    rules = [(origin, offset, step, phase) for origin in ('series', 'year', 'month')
             for offset in (0, -1, 'first') for step in (5, 7) for phase in range(step)]
    rules += [('weekday', offset, 7, phase) for offset in (0, -1, 'first') for phase in range(7)]
    methods = ('anchor', 'median_doy', 'last_doy')
    trials, best = [], None
    base = Profile()
    pools = {(ticker, ref['month']): all_windows(prices, ref['month'], cutoff, base)
             for ticker, prices, refs, cutoff in training for ref in refs}
    refreshed = {}
    for ticker, prices, refs, cutoff in training:
        for ref in refs:
            for row in pools[ticker, ref['month']]:
                for method in methods:
                    day = displayed_anchor(row, method)
                    key = ticker, day, row['hold_days']
                    if key not in refreshed:
                        refreshed[key] = evaluate_window(prices, day, row['hold_days'], cutoff, base)
    for rule in rules:
        for policy in ('inclusive', 'past_entry_years'):
            for objective in ('win_mean', 'mean', 'sharpe'):
                profile = replace(base, selection_history=policy, objective=objective)
                chosen = {(ticker, ref['month']): select(pools[ticker, ref['month']], prices, sessions, cutoff, rule, profile, 10, origins[ticker])
                          for ticker, prices, refs, cutoff in training for ref in refs}
                for method in methods:
                    details = []
                    for ticker, prices, refs, cutoff in training:
                        for ref in refs:
                            row = chosen[ticker, ref['month']]
                            day = displayed_anchor(row, method) if row else None
                            actual = refreshed.get((ticker, day, row['hold_days'])) if row else None
                            details.append({'ticker': ticker, **comparison(ref, actual)})
                    trial = {'grid': rule, 'policy': policy, 'objective': objective,
                             'display': method, 'training': counts(details)}
                    trials.append(trial)
                    if best is None or training_key(trial['training']) > training_key(best[0]['training']):
                        best = trial, profile, details
    winner, profile, details = best
    frozen = {ticker: prices for ticker, prices, refs, cutoff in training}
    holdouts = {}
    for name, tickers, period in [('GLD_10', ['GLD'], 10), ('SPY_QQQ_5', ['SPY','QQQ'], 5)]:
        reports = []
        for ticker, prices, refs, cutoff in dataset(args.evidence, tickers, period):
            prices = frozen.get(ticker, prices)
            for ref in refs:
                pool = all_windows(prices, ref['month'], cutoff, base, period)
                row = select(pool, prices, sessions, cutoff, winner['grid'], profile, period, origins[ticker])
                day = displayed_anchor(row, winner['display']) if row else None
                actual = evaluate_window(prices, day, row['hold_days'], cutoff, base, period) if row else None
                reports.append({'ticker': ticker, **comparison(ref, actual)})
        holdouts[name] = {**counts(reports), 'details': reports}
    write_json(args.out, {'trials': trials, 'winner': winner, 'training_details': details,
                         'holdouts': holdouts, 'price_inputs': inputs, 'production_changed': False,
                         'replication_complete': False})
    print('trials', len(trials), 'winner', winner, flush=True)
    print('holdouts', {name: {k:v for k,v in r.items() if k != 'details'} for name,r in holdouts.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', default='evidence')
    parser.add_argument('--universe', default='config/universe.example.json')
    parser.add_argument('--actions', default='evidence/actions')
    parser.add_argument('--calendar', default='calendar.csv')
    parser.add_argument('--raw-cache', required=True)
    parser.add_argument('--raw-field', default='close')
    parser.add_argument('--append-raw-tail', action='store_true')
    parser.add_argument('--normalize-vintage', action='store_true')
    parser.add_argument('--out', default='results/research/trading_grid.json')
    run(parser.parse_args())
