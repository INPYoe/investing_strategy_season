"""Verify the observed leap-year cross-boundary alignment on reconciled prices.

This is a global replica hypothesis, not an independently known server formula.
Its first-year exception is an analysis-boundary condition, not a ticker/date table.
Investment calculations ignore this alignment.
"""
import argparse
from dataclasses import asdict
from pathlib import Path

from lab import dataset, evaluate_profile, report_html
from research_dividends import calibrate, price_data
from seasonality import write_json


def run(args):
    data, inputs = price_data(args, dataset(args.evidence,['SPY','QQQ','AAPL']))
    # Reuse the ordinary global configuration calibration on the new convention.
    profile, trials = calibrate(data, cross_year_alignment='leap_after_first_year')
    training = evaluate_profile(data,profile)
    training.update(price_basis_hypothesis=inputs, trials=trials, iterations=len(trials),
                    production_optimizer_changed=False, full_independent_validation=False,
                    alignment_status='observed global hypothesis; unpublished server source not confirmed')
    frozen={t:p for t,p,r,c in data}
    held={}
    for name,tickers,period in [('GLD_10',['GLD'],10),('SPY_QQQ_5',['SPY','QQQ'],5)]:
        rows=[(t,frozen.get(t,p),r,c) for t,p,r,c in dataset(args.evidence,tickers,period)]
        held[name]=evaluate_profile(rows,profile,period)
    out=Path(args.out)
    write_json(out/'calibration.json',training)
    report_html(out/'comparison.html',training)
    for name,result in held.items():
        write_json(out/f'{name}.json',result)
        report_html(out/f'{name}.html',result)
    write_json(out/'profile.json',{'profile':asdict(profile),'price_basis_hypothesis':inputs,
                                  'replication_complete':False,'scope':'replica research only'})
    print('training',training['fully_matching_cases'],'fixed',training['fixed_window_formula']['average_matches'])
    print('held',{name:(r['fully_matching_cases'],r['fixed_window_formula']['average_matches']) for name,r in held.items()})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',default='evidence')
    parser.add_argument('--universe',default='config/universe.example.json')
    parser.add_argument('--actions',default='evidence/actions')
    parser.add_argument('--raw-cache',required=True)
    parser.add_argument('--raw-field',default='close')
    parser.add_argument('--append-raw-tail',action='store_true')
    parser.add_argument('--normalize-vintage',action='store_true')
    parser.add_argument('--out',default='results/research/year_boundary')
    run(parser.parse_args())
