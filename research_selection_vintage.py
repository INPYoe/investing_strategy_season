"""Select from an earlier information snapshot, then refresh current statistics.

The stored updated_at timestamps establish reported statistics' cutoff, but do
not prove when entry/holding choices were selected. This tests that separation
globally. Daily candidate enumeration avoids the rejected shared weekly grids.
"""
import argparse
import itertools
from dataclasses import asdict
from datetime import date

from lab import comparison, dataset
from research import counts, training_key
from research_dividends import price_data
from research_window_smoothing import POLICIES, window_stats
from seasonality import Profile, evaluate_window, objective_key, write_json


def selection_cutoff(cutoff, rule):
    if rule == 'current':
        return cutoff
    if rule == 'year_start':
        return date(cutoff.year, 1, 1)
    if rule == 'previous_quarter':
        quarter = (cutoff.month - 1) // 3
        return date(cutoff.year, (quarter - 1) * 3 + 1, 1) if quarter else date(cutoff.year - 1, 10, 1)
    if rule == 'previous_year':
        return date(cutoff.year - 1, cutoff.month, min(cutoff.day, 28) if cutoff.month == 2 else cutoff.day)
    raise ValueError('Unknown information snapshot')


def selection_pools(prices, cutoff, profile, period):
    pools = {month: [] for month in range(1, 13)}
    for day, hold in itertools.product(range(1, 366), profile.holds):
        row = evaluate_window(prices, day, hold, cutoff, profile, period)
        if row:
            scored = {policy: window_stats(row, policy, period) for policy in POLICIES}
            pools[row['month']].append((row, scored))
    return pools


def choose(pool, policy, objective):
    available = [item for item in pool if item[1][policy]]
    return max(available, key=lambda item: objective_key(item[1][policy], objective))[0] if available else None


def report_for_choice(prices, cutoff, period, row, cache):
    if row is None:
        return None
    # Inputs are frozen within a research run. Keep the object alive so identity
    # cannot be recycled, and segregate reporting cutoffs and price bases.
    cache.setdefault(('price_input', id(prices)), prices)
    key = 'report', id(prices), prices.ticker, cutoff, period, row['entry_day'], row['hold_days']
    if key not in cache:
        cache[key] = evaluate_window(prices, row['entry_day'], row['hold_days'], cutoff,
                                     Profile(cross_year_alignment='leap_after_first_year'), period)
    return cache[key]


def run(args):
    original = dataset(args.evidence, ['SPY', 'QQQ', 'AAPL'])
    reconciled, inputs = price_data(args, original)
    frozen_original = {ticker: prices for ticker, prices, refs, cutoff in original}
    frozen_report = {ticker: prices for ticker, prices, refs, cutoff in reconciled}
    trials, best, reports = [], None, {}
    for basis, snapshot, dm, roll, offset in itertools.product(
            ('chart_snapshot', 'reconciled'), ('current', 'year_start', 'previous_quarter', 'previous_year'),
            ('doy', 'month_day'), ('next', 'previous'), (0, -1)):
        profile = Profile(date_mode=dm, roll=roll, hold_offset=offset,
                          cross_year_alignment='leap_after_first_year')
        pools = {ticker: selection_pools(frozen_original[ticker] if basis == 'chart_snapshot' else prices,
                                         selection_cutoff(cutoff, snapshot), profile, 10)
                 for ticker, prices, refs, cutoff in reconciled}
        for policy, objective in itertools.product(POLICIES, ('win_mean', 'win_daily', 'mean', 'sharpe', 'win_median')):
            details = []
            for ticker, prices, refs, cutoff in reconciled:
                for ref in refs:
                    selected = choose(pools[ticker][ref['month']], policy, objective)
                    actual = report_for_choice(prices, cutoff, 10, selected, reports)
                    details.append({'ticker': ticker, **comparison(ref, actual)})
            trial = {'selection_price_basis': basis, 'selection_snapshot': snapshot,
                     'selection_profile': asdict(profile), 'selection_history': policy,
                     'objective': objective, 'training': counts(details)}
            trials.append(trial)
            if best is None or training_key(trial['training']) > training_key(best[0]['training']):
                best = trial, details
        if len(trials) % 160 == 0:
            print(len(trials), 'selection-vintage trials; best', best[0], flush=True)
    winner, details = best
    selected_profile = Profile(**{**winner['selection_profile'], 'holds': tuple(winner['selection_profile']['holds'])})
    holdouts = {}
    for name, tickers, period in [('GLD_10', ['GLD'], 10), ('SPY_QQQ_5', ['SPY', 'QQQ'], 5)]:
        results = []
        for ticker, original_prices, refs, cutoff in dataset(args.evidence, tickers, period):
            report_prices = frozen_report.get(ticker, original_prices)
            selected_prices = (frozen_original.get(ticker, original_prices)
                               if winner['selection_price_basis'] == 'chart_snapshot' else report_prices)
            pool = selection_pools(selected_prices, selection_cutoff(cutoff, winner['selection_snapshot']),
                                   selected_profile, period)
            for ref in refs:
                selected = choose(pool[ref['month']], winner['selection_history'], winner['objective'])
                actual = report_for_choice(report_prices, cutoff, period, selected, reports)
                results.append({'ticker': ticker, **comparison(ref, actual)})
        holdouts[name] = {**counts(results), 'details': results}
    write_json(args.out, {'trials': trials, 'iterations': len(trials), 'winner': winner,
                         'training_details': details, 'holdouts': holdouts, 'price_inputs': inputs,
                         'scope': 'Historical selection snapshot hypothesis; reused diagnostics, no new acquisition',
                         'selection': 'Training only; candidates are daily, without reference dates',
                         'production_changed': False, 'replication_complete': False})
    print('winner', winner)
    print('held', {name: {key: value for key, value in result.items() if key != 'details'}
                   for name, result in holdouts.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', default='evidence')
    parser.add_argument('--universe', default='config/universe.example.json')
    parser.add_argument('--actions', default='evidence/actions_extended')
    parser.add_argument('--price-lookback', type=int, default=11)
    parser.add_argument('--raw-cache', required=True)
    parser.add_argument('--raw-field', default='close')
    parser.add_argument('--append-raw-tail', action='store_true')
    parser.add_argument('--normalize-vintage', action='store_true')
    parser.add_argument('--out', default='results/research/selection_vintage.json')
    run(parser.parse_args())
