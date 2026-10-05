"""Check candidate-date coverage before trying further objective functions.

Reference dates are compared with a price/calendar-derived candidate set. These
are diagnostic coverage counts, never hardcoded candidates or optimizer results.
"""
import argparse
import itertools
from datetime import date, timedelta

from lab import dataset
from research_curve_candidates import curve_anchors
from research_daily_curve import daily_curves
from seasonality import write_json


def candidates(series, cutoff, period, rule):
    if rule['family'] == 'calendar':
        days = set()
        for day in range(1, 366):
            coordinate = day if rule['origin'] == 'year' else (date(2001, 1, 1) + timedelta(days=day - 1)).day - 1
            if coordinate % rule['step'] == rule['phase']:
                days.add(day)
        return days
    curves = daily_curves(series, cutoff, period)
    anchors = curve_anchors(curves, rule['mapping'], rule['precision'])
    return {day for index, day in enumerate(anchors) if day and index % rule['step'] == rule['phase']}


def coverage(data, period, rule):
    details = []
    for ticker, prices, refs, cutoff in data:
        available = candidates(prices, cutoff, period, rule)
        details.extend({'ticker': ticker, 'month': ref['month'], 'entry_day': ref['entry_day'],
                        'in_candidates': ref['entry_day'] in available} for ref in refs)
    return {'cases': len(details), 'covered': sum(row['in_candidates'] for row in details),
            'details': details}


def run(args):
    training = dataset(args.evidence, ['SPY', 'QQQ', 'AAPL'])
    rules = [{'family': 'calendar', 'origin': origin, 'step': 7, 'phase': phase}
             for origin, phase in itertools.product(('year', 'month'), range(7))]
    rules += [{'family': 'annual', 'mapping': method, 'precision': precision, 'step': step, 'phase': phase}
              for method, precision, (step, phase) in itertools.product(
                  ('first_doy', 'last_doy', 'median_doy', 'mean_doy', 'median_md', 'last_md'),
                  (None, 2), [(step, phase) for step in (5, 7) for phase in range(step)])]
    trials = [{'rule': rule, 'training': coverage(training, 10, rule)} for rule in rules]
    winner = max(trials, key=lambda trial: trial['training']['covered'])
    held = {name: coverage(dataset(args.evidence, tickers, period), period, winner['rule'])
            for name, tickers, period in [('GLD_10', ['GLD'], 10), ('SPY_QQQ_5', ['SPY', 'QQQ'], 5)]}
    result = {'trials': trials, 'iterations': len(trials), 'best_coverage_training_only': winner,
              'holdouts': held,
              'scope': 'Diagnostic date coverage upper bound; not optimizer parity or fresh validation',
              'price_basis': 'Only source date arrays used; price levels do not affect calendar mappings',
              'production_changed': False, 'replication_complete': False}
    write_json(args.out, result)
    print('best weekly coverage', winner['rule'], winner['training']['covered'], '/', winner['training']['cases'])
    print('held', {name: (report['covered'], report['cases']) for name, report in held.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', default='evidence')
    parser.add_argument('--out', default='results/research/candidate_geometry.json')
    run(parser.parse_args())
