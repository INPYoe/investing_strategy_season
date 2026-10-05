"""Target-free global scoring hypotheses on reconciled diagnostic prices.

Training chooses a rule; held-out outcomes never enter that choice.
"""
import argparse
from dataclasses import replace
from statistics import mean

from lab import comparison, dataset
from research import counts, training_key
from research_dividends import price_data
from seasonality import Profile, all_windows, selection_stats, write_json


def score(row, rule):
    name, weight = rule
    avg, win = row['avg_return'], row['win_rate']
    if name == 'mean_win':
        return avg + weight*win
    if name == 'weighted_mean':
        return avg*win**weight
    if name == 'downside':
        downside = mean(min(s['return'], 0)**2 for s in row['samples'])**.5
        return avg/max(downside, 1e-12)
    if name == 'profit_factor':
        rates = [s['return'] for s in row['samples']]
        return sum(max(r, 0) for r in rates)/max(-sum(min(r, 0) for r in rates), 1e-12)
    if name == 'geometric':
        import math
        return mean(math.log1p(s['return']) for s in row['samples'])
    if name == 'worst':
        return row['worst_return'], avg
    raise ValueError('Unknown score')


def choose(pool, profile, rule):
    scored = [(row, selection_stats(row, profile.selection_history)) for row in pool
              if (row['entry_day']-profile.entry_offset) % profile.entry_step == 0]
    scored = [(row, stats) for row, stats in scored if stats]
    return max(scored, key=lambda pair: score(pair[1], rule))[0] if scored else None


def run(args):
    training, inputs = price_data(args, dataset(args.evidence, ['SPY', 'QQQ', 'AAPL']))
    rules = [('mean_win', w) for w in (0, .01, .025, .05, .1, .25, .5, 1, 2)]
    rules += [('weighted_mean', w) for w in (1, 2, 3, 5, 10)]
    rules += [(name, 0) for name in ('downside', 'profit_factor', 'geometric', 'worst')]
    trials, best = [], None
    for date_mode in ('doy', 'month_day'):
        base = Profile(date_mode=date_mode)
        pools = {(ticker, ref['month']): all_windows(prices, ref['month'], cutoff, base)
                 for ticker, prices, refs, cutoff in training for ref in refs}
        for policy in ('inclusive', 'past_entry_years', 'past_exit_years'):
            for step, offset in [(1, 0)]+[(7, n) for n in range(7)]:
                profile = replace(base, selection_history=policy, entry_step=step, entry_offset=offset)
                for rule in rules:
                    details = [{'ticker': ticker, **comparison(ref, choose(pools[ticker, ref['month']], profile, rule))}
                               for ticker, prices, refs, cutoff in training for ref in refs]
                    metrics = counts(details)
                    trial = {'date_mode': date_mode, 'policy': policy, 'step': step, 'offset': offset,
                             'rule': rule, 'training': metrics}
                    trials.append(trial)
                    if best is None or training_key(metrics) > training_key(best[0]['training']):
                        best = trial, profile, rule, details
        print(date_mode, len(trials), 'best', best[0], flush=True)
    winner, profile, rule, details = best
    frozen = {ticker: prices for ticker, prices, refs, cutoff in training}
    holdouts = {}
    for name, tickers, period in [('GLD_10', ['GLD'], 10), ('SPY_QQQ_5', ['SPY', 'QQQ'], 5)]:
        rows = []
        for ticker, prices, refs, cutoff in dataset(args.evidence, tickers, period):
            prices = frozen.get(ticker, prices)
            for ref in refs:
                pool = all_windows(prices, ref['month'], cutoff, replace(profile, entry_step=1), period)
                rows.append({'ticker': ticker, **comparison(ref, choose(pool, profile, rule))})
        holdouts[name] = {**counts(rows), 'details': rows}
    write_json(args.out, {'trials': trials, 'winner': winner, 'training_details': details,
                         'holdouts': holdouts, 'price_inputs': inputs, 'production_changed': False,
                         'replication_complete': False})
    print('holdouts', {name: {k:v for k,v in r.items() if k != 'details'} for name,r in holdouts.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', default='evidence')
    parser.add_argument('--universe', default='config/universe.example.json')
    parser.add_argument('--actions', default='evidence/actions')
    parser.add_argument('--raw-cache', required=True)
    parser.add_argument('--raw-field', default='close')
    parser.add_argument('--append-raw-tail', action='store_true')
    parser.add_argument('--normalize-vintage', action='store_true')
    parser.add_argument('--out', default='results/research/scores.json')
    run(parser.parse_args())
