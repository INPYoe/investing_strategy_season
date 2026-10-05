"""Select annual trading-index windows, then report on an observed calendar date.

Motivation: the frozen public daily seasonality response has 252 points, including
fractional/interpolated win statistics. No reference dates enter candidate creation.
"""
import argparse
import bisect
import calendar
import csv
import itertools
import math
from dataclasses import replace
from datetime import date, timedelta

from lab import comparison, dataset
from research import counts, training_key
from research_dividends import price_data
from research_stages import displayed_anchor
from seasonality import Profile, evaluate_window, objective_key, selection_stats, summarize, write_json


def point(prices, sessions, year, coordinate, mode, size=252):
    """Raw ordinal or linear interpolation onto a fixed annual point count."""
    dates = [d for d in sessions if d.year == year]
    if not dates:
        return None
    position = coordinate if mode == 'ordinal' else coordinate*(len(dates)-1)/(size-1)
    lower, upper = math.floor(position), math.ceil(position)
    if lower < 0 or upper >= len(dates):
        return None
    if dates[lower] not in prices or dates[upper] not in prices:
        return None
    fraction = position-lower
    price = prices[dates[lower]]*(1-fraction)+prices[dates[upper]]*fraction
    day = dates[lower]+timedelta(days=round((dates[upper]-dates[lower]).days*fraction))
    return day, price


def annual_pool(series, sessions, cutoff, period, mode):
    prices = {d:p for d,p in zip(series.dates,series.prices) if d < cutoff}
    yearly = {year:[d for d in sessions if d.year==year] for year in range(cutoff.year-period,cutoff.year+2)}
    rows = []
    for index, hold in itertools.product(range(252), (5,10,15,20,25,30)):
        samples = []
        for year in range(cutoff.year-period,cutoff.year+1):
            first = point(prices,yearly[year],year,index,mode)
            length = len(yearly[year]) if mode=='ordinal' else 252
            end_index, end_year = index+hold, year
            if end_index >= length:
                end_index -= length
                end_year += 1
            last = point(prices,yearly.get(end_year,[]),end_year,end_index,mode)
            if not first or not last:
                continue
            samples.append({'year':year,'entry':first[0].isoformat(),'exit':last[0].isoformat(),
                            'return':last[1]/first[1]-1})
        stats = summarize(samples)
        if not stats:
            continue
        row = {'annual_index':index,'hold_days':hold,'asof_year':cutoff.year,**stats}
        row['entry_day'] = displayed_anchor(row,'median_doy')
        rows.append(row)
    return rows


def choose(rows, month, profile, method, step, phase):
    options = []
    for row in rows:
        if row['annual_index'] % step != phase:
            continue
        day = displayed_anchor(row,method)
        if not day or (date(2001,1,1)+timedelta(days=day-1)).month != month:
            continue
        stats = selection_stats(row,profile.selection_history)
        if stats:
            options.append((row,stats,day))
    return max(options,key=lambda x:objective_key(x[1],profile.objective)) if options else None


def run(args):
    training, inputs = price_data(args,dataset(args.evidence,['SPY','QQQ','AAPL']))
    with open(args.calendar) as stream:
        sessions = [date.fromisoformat(row['Date']) for row in csv.DictReader(stream)]
    methods = ('median_doy','mean_doy','first_doy','last_doy','median_md')
    grids = [(1,0)]+[(step,phase) for step in (5,7) for phase in range(step)]
    trials,best = [],None
    refreshed = {}
    for mode in ('ordinal','normalized'):
        pools = {t:annual_pool(p,sessions,c,10,mode) for t,p,r,c in training}
        for policy,objective,method,(step,phase) in itertools.product(
                ('inclusive','past_entry_years','past_exit_years'),
                ('win_mean','win_daily','mean','sharpe','win_median'), methods, grids):
            profile = Profile(selection_history=policy,objective=objective)
            details = []
            for ticker,prices,refs,cutoff in training:
                for ref in refs:
                    choice = choose(pools[ticker],ref['month'],profile,method,step,phase)
                    actual = None
                    if choice:
                        row,_,day = choice
                        key = ticker,day,row['hold_days']
                        if key not in refreshed:
                            refreshed[key] = evaluate_window(prices,day,row['hold_days'],cutoff,Profile())
                        actual = refreshed[key]
                    details.append({'ticker':ticker,**comparison(ref,actual)})
            trial = {'annual_mapping':mode,'policy':policy,'objective':objective,'display':method,
                     'step':step,'phase':phase,'training':counts(details)}
            trials.append(trial)
            if best is None or training_key(trial['training'])>training_key(best[0]['training']):
                best = trial,profile,details
        print(mode,len(trials),'best',best[0],flush=True)
    winner,profile,details = best
    frozen = {t:p for t,p,r,c in training}
    held = {}
    for name,tickers,period in [('GLD_10',['GLD'],10),('SPY_QQQ_5',['SPY','QQQ'],5)]:
        rows = []
        for ticker,prices,refs,cutoff in dataset(args.evidence,tickers,period):
            prices = frozen.get(ticker,prices)
            pool = annual_pool(prices,sessions,cutoff,period,winner['annual_mapping'])
            for ref in refs:
                choice = choose(pool,ref['month'],profile,winner['display'],winner['step'],winner['phase'])
                actual = evaluate_window(prices,choice[2],choice[0]['hold_days'],cutoff,Profile(),period) if choice else None
                rows.append({'ticker':ticker,**comparison(ref,actual)})
        held[name] = {**counts(rows),'details':rows}
    write_json(args.out,{'trials':trials,'winner':winner,'training_details':details,'holdouts':held,
                         'price_inputs':inputs,'production_changed':False,'replication_complete':False})
    print('held',{n:{k:v for k,v in r.items() if k!='details'} for n,r in held.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',default='evidence')
    parser.add_argument('--universe',default='config/universe.example.json')
    parser.add_argument('--actions',default='evidence/actions')
    parser.add_argument('--calendar',default='calendar.csv')
    parser.add_argument('--raw-cache',required=True)
    parser.add_argument('--raw-field',default='close')
    parser.add_argument('--append-raw-tail',action='store_true')
    parser.add_argument('--normalize-vintage',action='store_true')
    parser.add_argument('--out',default='results/research/annual_index.json')
    run(parser.parse_args())
