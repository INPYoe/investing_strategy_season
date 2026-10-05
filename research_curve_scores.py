"""Test curve-derived window scores; report ordinary per-trade statistics.

The site publishes cumulative mean curves. A curve's change differs from the
mean trade return when years have different starting price levels.
"""
import argparse
import bisect
import itertools
from dataclasses import replace
from datetime import date,timedelta
from statistics import mean

from lab import comparison,dataset
from research import counts,training_key
from research_dividends import price_data
from seasonality import Profile,all_windows,selection_stats,write_json


def attach_prices(row,series):
    prices=dict(zip(series.dates,series.prices))
    samples=[]
    for sample in row['samples']:
        year=sample['year']
        index=bisect.bisect_left(series.dates,date(year,1,1))
        samples.append({**sample,'entry_price':prices[date.fromisoformat(sample['entry'])],
                        'exit_price':prices[date.fromisoformat(sample['exit'])],
                        'year_base':series.prices[index]})
    return {**row,'samples':samples}


def curve_score(row,name,win_first):
    samples=row['samples']
    if name=='cash_pnl':
        value=mean(s['exit_price']-s['entry_price'] for s in samples)
    elif name=='price_ratio':
        value=sum(s['exit_price'] for s in samples)/sum(s['entry_price'] for s in samples)-1
    elif name=='annual_pnl':
        value=mean((s['exit_price']-s['entry_price'])/s['year_base'] for s in samples)
    elif name=='annual_ratio':
        value=sum(s['exit_price']/s['year_base'] for s in samples)/sum(s['entry_price']/s['year_base'] for s in samples)-1
    else:
        raise ValueError('Unknown curve score')
    return (row['win_rate'],value) if win_first else value


def choose(pool,profile,name,win_first,origin):
    options=[]
    for row in pool:
        coordinate=row['entry_day'] if origin=='year' else (date(2001,1,1)+timedelta(days=row['entry_day']-1)).day-1
        if (coordinate-profile.entry_offset)%profile.entry_step:
            continue
        stats=selection_stats(row,profile.selection_history)
        if stats:
            options.append((row,stats))
    return max(options,key=lambda pair:curve_score(pair[1],name,win_first))[0] if options else None


def run(args):
    training,inputs=price_data(args,dataset(args.evidence,['SPY','QQQ','AAPL']))
    trials,best=[],None
    grids=[(1,0)]+[(7,n) for n in range(7)]
    for dm in ('doy','month_day'):
        base=Profile(date_mode=dm,cross_year_alignment='leap_after_first_year')
        pools={(t,r['month']):[attach_prices(row,p) for row in all_windows(p,r['month'],c,base)]
               for t,p,refs,c in training for r in refs}
        for policy,origin,(step,phase),name,win_first in itertools.product(
                ('inclusive','past_entry_years','past_exit_years'),('year','month'),grids,
                ('cash_pnl','price_ratio','annual_pnl','annual_ratio'),(False,True)):
            profile=replace(base,selection_history=policy,entry_step=step,entry_offset=phase)
            details=[{'ticker':t,**comparison(ref,choose(pools[t,ref['month']],profile,name,win_first,origin))}
                     for t,p,refs,c in training for ref in refs]
            trial={'date_mode':dm,'policy':policy,'origin':origin,'step':step,'phase':phase,
                   'curve_score':name,'win_first':win_first,'training':counts(details)}
            trials.append(trial)
            if best is None or training_key(trial['training'])>training_key(best[0]['training']):
                best=trial,profile,details
        print(dm,len(trials),'best',best[0],flush=True)
    winner,profile,details=best
    frozen={t:p for t,p,refs,c in training}
    held={}
    for group,tickers,period in [('GLD_10',['GLD'],10),('SPY_QQQ_5',['SPY','QQQ'],5)]:
        rows=[]
        for t,p,refs,c in dataset(args.evidence,tickers,period):
            p=frozen.get(t,p)
            for ref in refs:
                pool=[attach_prices(row,p) for row in all_windows(p,ref['month'],c,replace(profile,entry_step=1),period)]
                rows.append({'ticker':t,**comparison(ref,choose(pool,profile,winner['curve_score'],winner['win_first'],winner['origin']))})
        held[group]={**counts(rows),'details':rows}
    write_json(args.out,{'trials':trials,'winner':winner,'training_details':details,'holdouts':held,
                        'price_inputs':inputs,'production_changed':False,'replication_complete':False})
    print('held',{n:{k:v for k,v in r.items() if k!='details'} for n,r in held.items()})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',default='evidence')
    parser.add_argument('--universe',default='config/universe.example.json')
    parser.add_argument('--actions',default='evidence/actions')
    parser.add_argument('--raw-cache',required=True)
    parser.add_argument('--raw-field',default='close')
    parser.add_argument('--append-raw-tail',action='store_true')
    parser.add_argument('--normalize-vintage',action='store_true')
    parser.add_argument('--out',default='results/research/curve_scores.json')
    run(parser.parse_args())
