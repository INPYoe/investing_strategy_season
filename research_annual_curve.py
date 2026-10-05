"""Select on normalized annual prices; store a floor-mapped calendar date.

The public daily display suggests linear interpolation and floor date labels.
This isolates those two operations from ordinary per-trade reporting. The
original annual-index experiment used a rounded interpolated calendar date.
"""
import argparse
import csv
import itertools
from datetime import date, timedelta

from lab import comparison, dataset
from research import counts, training_key
from research_annual_index import annual_pool
from research_curve_candidates import curve_anchors
from research_daily_curve import daily_curves
from research_dividends import price_data
from seasonality import Profile, evaluate_window, objective_key, selection_stats, write_json


def choose(pool, anchors, month, policy, objective, step, phase):
    candidates = [row for row in pool if row['annual_index'] % step == phase
                  and anchors[row['annual_index']]
                  and (date(2001, 1, 1) + timedelta(days=anchors[row['annual_index']] - 1)).month == month
                  and row['selection'][policy]]
    return max(candidates, key=lambda row: objective_key(row['selection'][policy], objective)) if candidates else None


def prepared(prices, sessions, cutoff, period):
    curves = daily_curves(prices, cutoff, period)
    mappings = {(method, precision): curve_anchors(curves, method, precision)
                for method in ('first_doy', 'last_doy', 'median_doy', 'mean_doy', 'median_md', 'last_md')
                for precision in (None, 2)}
    pool = annual_pool(prices, sessions, cutoff, period, 'normalized')
    pool = [{**row, 'selection': {policy: selection_stats(row, policy)
                                 for policy in ('inclusive', 'past_entry_years', 'past_exit_years')}}
            for row in pool]
    profile = Profile(cross_year_alignment='leap_after_first_year')
    report = {(day, hold): evaluate_window(prices, day, hold, cutoff, profile, period)
              for day in {day for anchors in mappings.values() for day in anchors if day} for hold in profile.holds}
    return mappings, pool, report


def run(args):
    training, inputs = price_data(args, dataset(args.evidence, ['SPY', 'QQQ', 'AAPL']))
    with open(args.calendar) as stream:
        sessions = [date.fromisoformat(row['Date']) for row in csv.DictReader(stream)]
    ready = {ticker: prepared(prices, sessions, cutoff, 10) for ticker, prices, refs, cutoff in training}
    grids = [(1, 0)] + [(step, phase) for step in (5, 7) for phase in range(step)]
    trials, best = [], None
    for (method, precision), (step, phase), policy, objective in itertools.product(
            ready['SPY'][0], grids, ('inclusive', 'past_entry_years', 'past_exit_years'),
            ('win_mean', 'win_daily', 'mean', 'sharpe', 'win_median')):
        details = []
        for ticker, prices, refs, cutoff in training:
            mappings, pool, report = ready[ticker]
            anchors = mappings[method, precision]
            for ref in refs:
                row = choose(pool, anchors, ref['month'], policy, objective, step, phase)
                actual = report[anchors[row['annual_index']], row['hold_days']] if row else None
                details.append({'ticker': ticker, 'selected_curve_index': row['annual_index'] if row else None,
                                **comparison(ref, actual)})
        trial = {'calendar_mapping': method, 'coordinate_rounding_digits': precision,
                 'entry_step': step, 'entry_phase': phase, 'selection_history': policy,
                 'objective': objective, 'training': counts(details)}
        trials.append(trial)
        if best is None or training_key(trial['training']) > training_key(best[0]['training']):
            best = trial, details
        if len(trials) % 390 == 0:
            print(len(trials), 'normalized curve trials; best', best[0], flush=True)
    winner, details = best
    frozen = {ticker: prices for ticker, prices, refs, cutoff in training}
    holdouts = {}
    for name, tickers, period in [('GLD_10', ['GLD'], 10), ('SPY_QQQ_5', ['SPY', 'QQQ'], 5)]:
        results = []
        for ticker, prices, refs, cutoff in dataset(args.evidence, tickers, period):
            mappings, pool, report = prepared(frozen.get(ticker, prices), sessions, cutoff, period)
            anchors = mappings[winner['calendar_mapping'], winner['coordinate_rounding_digits']]
            for ref in refs:
                row = choose(pool, anchors, ref['month'], winner['selection_history'], winner['objective'],
                             winner['entry_step'], winner['entry_phase'])
                actual = report[anchors[row['annual_index']], row['hold_days']] if row else None
                results.append({'ticker': ticker, 'selected_curve_index': row['annual_index'] if row else None,
                                **comparison(ref, actual)})
        holdouts[name] = {**counts(results), 'details': results}
    write_json(args.out, {'trials': trials, 'iterations': len(trials), 'winner': winner,
                         'training_details': details, 'holdouts': holdouts, 'price_inputs': inputs,
                         'scope': 'Training-only winner; reused diagnostics, not fresh validation',
                         'production_changed': False, 'replication_complete': False})
    print('winner', winner)
    print('held', {name: {key: value for key, value in result.items() if key != 'details'}
                   for name, result in holdouts.items()})


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
    parser.add_argument('--out', default='results/research/annual_curve.json')
    run(parser.parse_args())
