"""Test whether the reconstructed daily curve restricts optimal entry candidates.

Candidate curves, calendar mappings, and low points depend only on price data.
Reference rows are read solely by the comparison step. This is replica research;
it never changes the investment optimizer or uses ticker/month exception tables.
"""
import argparse
import itertools
from datetime import date, timedelta
from statistics import mean, median

from lab import comparison, dataset
from research import counts, training_key
from research_daily_curve import daily_curves, label_position, polynomial_smooth
from research_dividends import price_data
from seasonality import Profile, evaluate_window, objective_key, selection_stats, write_json


def curve_anchors(curves, method, precision, size=252):
    anchors = []
    for index in range(size):
        dates = [curve['dates'][label_position(len(curve['dates']), index, size, precision)]
                 for year, curve in sorted(curves.items())]
        doy = [day.timetuple().tm_yday for day in dates]
        md = [date(2001, day.month, min(day.day, 28) if day.month == 2 else day.day).timetuple().tm_yday
              for day in dates]
        if method == 'first_doy':
            anchor = doy[0]
        elif method == 'last_doy':
            anchor = doy[-1]
        elif method == 'median_doy':
            anchor = int(median(doy))
        elif method == 'mean_doy':
            anchor = int(mean(doy))
        elif method == 'median_md':
            anchor = int(median(md))
        elif method == 'last_md':
            anchor = md[-1]
        else:
            raise ValueError('Unknown curve calendar mapping')
        anchors.append(anchor if 1 <= anchor <= 365 else None)
    return anchors


def candidate_indexes(values, anchors, month, rule, radius=1):
    indexes = [index for index, anchor in enumerate(anchors)
               if anchor and (date(2001, 1, 1) + timedelta(days=anchor - 1)).month == month]
    if rule == 'all':
        return indexes
    if rule in ('annual_grid_5', 'annual_grid_7'):
        step = int(rule.rsplit('_', 1)[1])
        return [index for index in indexes if index % step == radius]
    if rule == 'month_min':
        return [min(indexes, key=lambda index: (values[index], index))] if indexes else []
    if rule != 'local_min':
        raise ValueError('Unknown curve restriction')
    # Include neighbors from adjoining months; ties choose the first low point.
    return [index for index in indexes if index == min(
        range(max(0, index - radius), min(len(values), index + radius + 1)),
        key=lambda neighbor: (values[neighbor], neighbor))]


def choose(views, anchors, month, rule, radius, smoothed, price_rows, policy, objective):
    averages = views[smoothed]
    indexes = candidate_indexes(averages, anchors, month, rule, radius)
    options = []
    for index in indexes:
        for hold in (5, 10, 15, 20, 25, 30):
            row = price_rows.get((anchors[index], hold))
            stats = row['selection'][policy] if row else None
            if stats:
                options.append((row, stats, index))
    return max(options, key=lambda item: objective_key(item[1], objective)) if options else None


def prepared(series, cutoff, period):
    curves = daily_curves(series, cutoff, period)
    if not curves:
        raise ValueError('No complete annual curves')
    mappings = {(method, precision): curve_anchors(curves, method, precision)
                for method in ('first_doy', 'last_doy', 'median_doy', 'mean_doy', 'median_md', 'last_md')
                for precision in (None, 2)}
    days = {day for anchors in mappings.values() for day in anchors if day}
    profile = Profile(cross_year_alignment='leap_after_first_year')
    rows = {(day, hold): evaluate_window(series, day, hold, cutoff, profile, period)
            for day in days for hold in profile.holds}
    rows = {key: {**row, 'selection': {policy: selection_stats(row, policy)
                                      for policy in ('inclusive', 'past_entry_years', 'past_exit_years')}}
            if row else None for key, row in rows.items()}
    average = [mean(curve['returns'][index] for curve in curves.values()) for index in range(252)]
    views = {False: average, True: polynomial_smooth(average)}
    return views, mappings, rows


def run(args):
    training, inputs = price_data(args, dataset(args.evidence, ['SPY', 'QQQ', 'AAPL']))
    ready = {ticker: prepared(prices, cutoff, 10) for ticker, prices, refs, cutoff in training}
    trials, best = [], None
    if args.grids_only:
        restrictions = [('all', 1)] + [(f'annual_grid_{step}', phase) for step in (5, 7) for phase in range(step)]
    else:
        restrictions = [('all', 1), ('month_min', 1)] + [('local_min', radius) for radius in (1, 3, 5)]
    for (method, precision), (rule, radius), smooth, policy, objective in itertools.product(
            ready['SPY'][1], restrictions, (False,) if args.grids_only else (False, True),
            ('inclusive', 'past_entry_years', 'past_exit_years'),
            ('win_mean', 'win_daily', 'mean', 'sharpe', 'win_median')):
        details = []
        for ticker, prices, refs, cutoff in training:
            curves, mappings, rows = ready[ticker]
            for ref in refs:
                selected = choose(curves, mappings[method, precision], ref['month'], rule, radius,
                                  smooth, rows, policy, objective)
                details.append({'ticker': ticker, 'selected_curve_index': selected[2] if selected else None,
                                **comparison(ref, selected[0] if selected else None)})
        trial = {'calendar_mapping': method, 'coordinate_rounding_digits': precision,
                 'curve_restriction': rule, 'radius': radius, 'smoothed': smooth,
                 'selection_history': policy, 'objective': objective, 'training': counts(details)}
        trials.append(trial)
        if best is None or training_key(trial['training']) > training_key(best[0]['training']):
            best = trial, details
        if len(trials) % 300 == 0:
            print(len(trials), 'curve candidate trials; best', best[0], flush=True)
    winner, details = best
    frozen = {ticker: prices for ticker, prices, refs, cutoff in training}
    holdouts = {}
    for name, tickers, period in [('GLD_10', ['GLD'], 10), ('SPY_QQQ_5', ['SPY', 'QQQ'], 5)]:
        results = []
        for ticker, prices, refs, cutoff in dataset(args.evidence, tickers, period):
            curves, mappings, rows = prepared(frozen.get(ticker, prices), cutoff, period)
            anchors = mappings[winner['calendar_mapping'], winner['coordinate_rounding_digits']]
            for ref in refs:
                selected = choose(curves, anchors, ref['month'], winner['curve_restriction'], winner['radius'],
                                  winner['smoothed'], rows, winner['selection_history'], winner['objective'])
                results.append({'ticker': ticker, 'selected_curve_index': selected[2] if selected else None,
                                **comparison(ref, selected[0] if selected else None)})
        holdouts[name] = {**counts(results), 'details': results}
    result = {'trials': trials, 'iterations': len(trials), 'winner': winner, 'training_details': details,
              'holdouts': holdouts, 'price_inputs': inputs, 'selection': 'Training only',
              'scope': 'Existing diagnostics reused; no fresh holdout or confirmed server formula',
              'restriction_parameter': 'Annual grid phase when annual_grid; otherwise local minimum radius',
              'production_changed': False, 'replication_complete': False}
    write_json(args.out, result)
    print('winner', winner)
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
    parser.add_argument('--grids-only', action='store_true')
    parser.add_argument('--out', default='results/research/curve_candidates.json')
    run(parser.parse_args())
