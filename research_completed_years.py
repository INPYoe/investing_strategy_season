"""Compare completed calendar-year selection with current-period reporting.

Selection receives price samples and year boundaries, never reference windows.
The public creator example remains a validation-only observation.
"""
import argparse
import itertools
from dataclasses import replace
from datetime import date, timedelta

from lab import comparison, dataset
from research import counts, training_key
from research_dividends import price_data
from seasonality import Profile, all_windows, evaluate_window, objective_key, summarize, write_json


def completed_stats(row, asof, period, inclusive_oldest=False, require_exit=False):
    first = asof.year-period-(1 if inclusive_oldest else 0)
    samples = [s for s in row['samples'] if first <= s['year'] < asof.year
               and (not require_exit or int(s['exit'][:4]) < asof.year)]
    stats = summarize(samples)
    return {**row, **stats} if stats else None


def choose(pool, cutoff, period, profile, inclusive_oldest, require_exit, origin):
    selected = []
    for row in pool:
        coordinate = row['entry_day']
        if origin == 'month':
            coordinate = (date(2001, 1, 1)+timedelta(days=coordinate-1)).day-1
        if (coordinate-profile.entry_offset) % profile.entry_step:
            continue
        stats = completed_stats(row, cutoff, period, inclusive_oldest, require_exit)
        if stats:
            selected.append((row, stats))
    return max(selected, key=lambda pair: objective_key(pair[1], profile.objective))[0] if selected else None


def evaluate_group(data, period, base, settings, pool_cache, report_cache):
    profile, inclusive_oldest, require_exit, origin = settings
    details = []
    for ticker, prices, refs, cutoff in data:
        for ref in refs:
            key = (ticker, ref['month'], period, base.date_mode, base.roll, base.hold_offset)
            if key not in pool_cache:
                pool_cache[key] = all_windows(prices, ref['month'], cutoff, base, period+1)
            chosen = choose(pool_cache[key], cutoff, period, profile, inclusive_oldest, require_exit, origin)
            actual = None
            if chosen:
                key = (ticker, period, base.date_mode, base.roll, base.hold_offset, chosen['entry_day'], chosen['hold_days'])
                if key not in report_cache:
                    report_cache[key] = evaluate_window(prices, chosen['entry_day'], chosen['hold_days'], cutoff, base, period)
                actual = report_cache[key]
            details.append({'ticker': ticker, **comparison(ref, actual)})
    return details


def run(args):
    training, inputs = price_data(args, dataset(args.evidence, ['SPY', 'QQQ', 'AAPL']))
    trials, best = [], None
    pools, reports = {}, {}
    grids = [(1,0)]+[(7,n) for n in range(7)]
    for dm, roll, hold_offset in itertools.product(('doy','month_day'), ('next','previous'), (0,-1)):
        base = Profile(date_mode=dm, roll=roll, hold_offset=hold_offset)
        for inclusive_oldest, require_exit, origin, (step,phase), objective in itertools.product(
                (False,True), (False,True), ('year','month'), grids, ('win_mean','win_daily','mean','sharpe','win_median')):
            profile = replace(base, entry_step=step, entry_offset=phase, objective=objective)
            settings = profile, inclusive_oldest, require_exit, origin
            details = evaluate_group(training, 10, base, settings, pools, reports)
            metrics = counts(details)
            trial = {'date_mode':dm,'roll':roll,'hold_offset':hold_offset,'step':step,'phase':phase,
                     'objective':objective,'inclusive_oldest':inclusive_oldest,'require_exit':require_exit,
                     'grid_origin':origin,'training':metrics}
            trials.append(trial)
            if best is None or training_key(metrics)>training_key(best[0]['training']):
                best = trial, base, settings, details
        print(len(trials), 'best', best[0], flush=True)
    winner, base, settings, details = best
    frozen = {t:p for t,p,r,c in training}
    held = {}
    for name,tickers,period in [('GLD_10',['GLD'],10),('SPY_QQQ_5',['SPY','QQQ'],5)]:
        data = [(t,frozen.get(t,p),r,c) for t,p,r,c in dataset(args.evidence,tickers,period)]
        rows = evaluate_group(data,period,base,settings,pools,reports)
        held[name] = {**counts(rows),'details':rows}
    write_json(args.out, {'trials':trials,'winner':winner,'training_details':details,'holdouts':held,
                         'price_inputs':inputs,'production_changed':False,'replication_complete':False})
    print('held', {n:{k:v for k,v in r.items() if k!='details'} for n,r in held.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',default='evidence')
    parser.add_argument('--universe',default='config/universe.example.json')
    parser.add_argument('--actions',default='evidence/actions_extended')
    parser.add_argument('--raw-cache',required=True)
    parser.add_argument('--raw-field',default='close')
    parser.add_argument('--price-lookback',type=int,default=11)
    parser.add_argument('--append-raw-tail',action='store_true')
    parser.add_argument('--normalize-vintage',action='store_true')
    parser.add_argument('--out',default='results/research/completed_years.json')
    run(parser.parse_args())
