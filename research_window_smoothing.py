"""Test score smoothing and latest-completed selection, keeping reports raw.

The display audit supports an 11-point cubic smoothing hypothesis. This research
tests whether that operation is also applied to the entry-day score arrays.
Smoothing values are ranking scores, not reported probabilities or trade returns.
"""
import argparse
import itertools
from dataclasses import replace
from datetime import date, timedelta

from lab import comparison, dataset
from research import counts, training_key
from research_daily_curve import polynomial_smooth
from research_dividends import price_data
from seasonality import Profile, evaluate_window, objective_key, selection_stats, summarize, write_json


POLICIES = ('inclusive', 'past_entry_years', 'past_exit_years', 'latest_completed')


def window_stats(row, policy, period):
    if policy == 'latest_completed':
        stats = summarize(row['samples'][-period:])
        return {**row, **stats} if stats else None
    return selection_stats(row, policy)


def prepared(prices, cutoff, period, date_mode):
    profile = Profile(date_mode=date_mode, cross_year_alignment='leap_after_first_year')
    raw = {(day, hold): evaluate_window(prices, day, hold, cutoff, profile, period)
           for day in range(1, 366) for hold in profile.holds}
    scored = {}
    for policy in POLICIES:
        for hold in profile.holds:
            rows = [raw[day, hold] for day in range(1, 366)]
            if any(row is None for row in rows):
                raise ValueError('Missing entry-day statistics; do not bridge missing price history')
            stats = [window_stats(row, policy, period) for row in rows]
            if any(row is None for row in stats):
                raise ValueError('Missing selection history')
            means = polynomial_smooth([row['avg_return'] for row in stats])
            wins = polynomial_smooth([row['win_rate'] for row in stats])
            for row, original, avg_return, win_rate in zip(rows, stats, means, wins):
                for rule in ('raw', 'mean', 'wins', 'both'):
                    scored[policy, rule, row['entry_day'], hold] = {
                        **original,
                        'avg_return': avg_return if rule in ('mean', 'both') else original['avg_return'],
                        'win_rate': win_rate if rule in ('wins', 'both') else original['win_rate'],
                    }
    by_month = {month: [row for row in raw.values() if row['month'] == month] for month in range(1, 13)}
    return by_month, scored


def choose(by_month, scored, month, policy, smoothing, origin, step, phase, objective):
    candidates = []
    first_day = date(2001, month, 1).timetuple().tm_yday
    for row in by_month[month]:
        day = row['entry_day']
        coordinate = day if origin == 'year' else day - first_day
        if coordinate % step == phase:
            candidates.append(row)
    return max(candidates, key=lambda row: objective_key(
        scored[policy, smoothing, row['entry_day'], row['hold_days']], objective)) if candidates else None


def run(args):
    training, inputs = price_data(args, dataset(args.evidence, ['SPY', 'QQQ', 'AAPL']))
    grids = [(1, 0)] + [(7, phase) for phase in range(7)]
    trials, best = [], None
    for dm in ('doy', 'month_day'):
        ready = {ticker: prepared(prices, cutoff, 10, dm) for ticker, prices, refs, cutoff in training}
        for policy, smoothing, origin, (step, phase), objective in itertools.product(
                POLICIES, ('raw', 'mean', 'wins', 'both'), ('year', 'month'), grids,
                ('win_mean', 'win_daily', 'mean', 'sharpe', 'win_median')):
            details = []
            for ticker, prices, refs, cutoff in training:
                for ref in refs:
                    row = choose(*ready[ticker], ref['month'], policy, smoothing, origin, step, phase, objective)
                    details.append({'ticker': ticker, **comparison(ref, row)})
            trial = {'date_mode': dm, 'selection_history': policy, 'score_smoothing': smoothing,
                     'origin': origin, 'step': step, 'phase': phase, 'objective': objective,
                     'training': counts(details)}
            trials.append(trial)
            if best is None or training_key(trial['training']) > training_key(best[0]['training']):
                best = trial, details
        print(dm, len(trials), 'window score trials; best', best[0], flush=True)
    winner, details = best
    frozen = {ticker: prices for ticker, prices, refs, cutoff in training}
    holdouts = {}
    for name, tickers, period in [('GLD_10', ['GLD'], 10), ('SPY_QQQ_5', ['SPY', 'QQQ'], 5)]:
        results = []
        for ticker, prices, refs, cutoff in dataset(args.evidence, tickers, period):
            ready = prepared(frozen.get(ticker, prices), cutoff, period, winner['date_mode'])
            for ref in refs:
                row = choose(*ready, ref['month'], winner['selection_history'], winner['score_smoothing'],
                             winner['origin'], winner['step'], winner['phase'], winner['objective'])
                results.append({'ticker': ticker, **comparison(ref, row)})
        holdouts[name] = {**counts(results), 'details': results}
    write_json(args.out, {'trials': trials, 'iterations': len(trials), 'winner': winner,
                         'training_details': details, 'holdouts': holdouts, 'price_inputs': inputs,
                         'smoothing_window': 11, 'polynomial_degree': 3,
                         'scope': 'Observed display operation tested on scores; server source not confirmed',
                         'selection': 'Training only; diagnostics already reused',
                         'production_changed': False, 'replication_complete': False})
    print('held', {name: {key: value for key, value in report.items() if key != 'details'}
                   for name, report in holdouts.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', default='evidence')
    parser.add_argument('--universe', default='config/universe.example.json')
    parser.add_argument('--actions', default='evidence/actions')
    parser.add_argument('--raw-cache', required=True)
    parser.add_argument('--raw-field', default='close')
    parser.add_argument('--append-raw-tail', action='store_true')
    parser.add_argument('--normalize-vintage', action='store_true')
    parser.add_argument('--out', default='results/research/window_smoothing.json')
    run(parser.parse_args())
