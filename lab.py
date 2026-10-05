#!/usr/bin/env python3
"""CLI: price acquisition, independent optimization, parity loops, plans, backtests."""
from __future__ import annotations

import argparse
import csv
import html
import itertools
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from acquisition import failure_info, json_request, yahoo_chart_url

from seasonality import (Profile, PriceSeries, all_windows, equal_weights, evaluate_window,
                        event_schedule, md, objective_key, optimize, profile_from_json,
                        rejection_reasons, schedule_row, selection_stats, simulate, write_json)

ROOT = Path(__file__).resolve().parent
FIELDS = ("entry_day", "exit_day", "hold_days", "avg_return", "win_rate", "sample_count")


def get_json(url, body=None):
    req = json_request(url, body)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def download(args):
    """Independent Yahoo source. Reference website is never a price fallback."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    cooldown_path = out / 'download_rate_limit.json'
    if cooldown_path.exists():
        cooldown = json.loads(cooldown_path.read_text())
        until = cooldown.get('retry_after', {}).get('not_before_utc')
        if until and datetime.fromisoformat(until) > datetime.now(timezone.utc):
            print(f"Yahoo Retry-After: wait until {until}; download stopped, existing files preserved", file=sys.stderr)
            return 2

    def record_failure(ticker, error):
        detail = {'ticker': ticker, **failure_info(error)}
        errors.append(detail)
        print(f"{ticker}: acquisition failed ({detail['kind']}): {error}", file=sys.stderr)
        if detail['kind'] in ('http_429', 'sdk_rate_limit', 'suspected_rate_limit'):
            write_json(cooldown_path, detail)
            print(f"Yahoo requests stopped; Retry-After={detail['retry_after']['raw']!r}; no automatic retry", file=sys.stderr)
        return detail['kind'] in ('http_429', 'sdk_rate_limit', 'suspected_rate_limit', 'dns_error', 'permission_error')
    for ticker in args.tickers:
        path = out / f"{ticker.upper()}.csv"
        if args.provider == "yfinance":
            try:
                import yfinance as yf
            except ImportError as exc:
                raise SystemExit("Install the optional provider: python3 -m pip install -r requirements.txt") from exc
            try:
                frame = yf.Ticker(ticker).history(start=args.start, end=args.end, auto_adjust=False,
                                                 actions=False, repair=False, raise_errors=True)
                if frame.empty:
                    raise ValueError(f"No Yahoo data for {ticker}")
                if frame[["Close", "Adj Close"]].isna().any().any():
                    raise ValueError("Missing daily prices; do not silently remove trading sessions")
                records = [{"Date": idx.date().isoformat(), "Close": float(row["Close"]),
                            "Adj Close": float(row["Adj Close"])} for idx, row in frame.iterrows()]
            except Exception as exc:
                if record_failure(ticker, exc):
                    break
                continue
        else:
            url = yahoo_chart_url(ticker, args.start, args.end)
            try:
                obj = get_json(url)
                if obj["chart"].get("error"):
                    raise ValueError(str(obj["chart"]["error"]))
                data = obj["chart"]["result"][0]
                timestamps = data["timestamp"]
                closes = data["indicators"]["quote"][0]["close"]
                adjusted = data["indicators"]["adjclose"][0]["adjclose"]
                tz = ZoneInfo(data["meta"]["exchangeTimezoneName"])
                records = []
                for ts, close, adj in zip(timestamps, closes, adjusted):
                    if close is None or adj is None:
                        raise ValueError("Missing daily prices; do not silently remove trading sessions")
                    records.append({"Date": datetime.fromtimestamp(ts, tz).date().isoformat(), "Close": close, "Adj Close": adj})
            except Exception as exc:
                if record_failure(ticker, exc):
                    break
                continue
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["Date", "Close", "Adj Close"])
            writer.writeheader()
            writer.writerows(records)
        # Validate output and record provenance without substituting site prices.
        series = PriceSeries.load(path, ticker, "Adj Close")
        write_json(path.with_suffix(".metadata.json"), {"provider": args.provider, "downloaded_at": datetime.now().isoformat(),
                   "end_exclusive": args.end, "sha256": series.sha256, "records": len(series.dates)})
        print(f"{ticker}: {len(series.dates)} daily records -> {path}")
    if errors:
        write_json(out / "download_errors.json", errors)
        return 2
    return 0


def capture(args):
    """Optional public reference snapshot. Not used by independent analysis."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for ticker in args.tickers:
        for period in args.periods:
            url = f"https://easyinvesting.app/api/seasonality/optimal-ticker/{urllib.parse.quote(ticker, safe='')}?period={period}"
            obj = get_json(url)
            path = out / f"{ticker.upper()}_optimal_{period}.json"
            write_json(path, obj)
            manifest.append({"path": str(path.name), "url": url, "captured_at": datetime.now().isoformat()})
        if args.include_chart:
            url = "https://easyinvesting.app/api/stock/chart?" + urllib.parse.urlencode({"ticker": ticker})
            obj = get_json(url)
            obj["source"] = "easyinvesting public chart snapshot; calibration only"
            path = out / f"{ticker.upper()}_chart.json"
            write_json(path, obj)
            manifest.append({"path": path.name, "url": url, "captured_at": datetime.now().isoformat()})
    write_json(out / "capture_manifest.json", manifest)
    return 0


def comparison(expected, actual):
    checks = {}
    for field in FIELDS:
        if actual is None:
            checks[field] = False
        elif field == "avg_return":
            # Explicit numerical tolerance: ~four-decimal input price rounding.
            checks[field] = abs(actual[field] - expected[field]) <= 0.000002
        elif field == "win_rate":
            checks[field] = abs(actual[field] - expected[field]) <= 1e-12
        else:
            checks[field] = actual[field] == expected[field]
    displayed = bool(actual) and (f"{actual['avg_return'] * 100:.1f}" == f"{expected['avg_return'] * 100:.1f}")
    return {"month": expected["month"], "expected": {k: expected[k] for k in FIELDS},
            "actual": {k: actual[k] for k in FIELDS} if actual else None, "checks": checks,
            "displayed_average_match": displayed, "all_match": all(checks.values())}


def dataset(evidence, tickers, period=10):
    result = []
    for ticker in tickers:
        prices = PriceSeries.load(Path(evidence) / f"{ticker}_chart.json", ticker)
        reference = json.loads((Path(evidence) / f"{ticker}_optimal_{period}.json").read_text())
        # Freeze to the precomputation date, even if chart contains newer prices.
        stamp = reference["rows"][0]["updated_at"][:10]
        result.append((ticker, prices, reference["rows"], date.fromisoformat(stamp)))
    return result


def evaluate_profile(data, profile, period=10):
    results = []
    fixed_results = []
    for ticker, prices, refs, cutoff in data:
        for expected in refs:
            actual = optimize(prices, expected["month"], cutoff, profile, period, "replica")
            results.append({"ticker": ticker, **comparison(expected, actual)})
            fixed = evaluate_window(prices, expected["entry_day"], expected["hold_days"], cutoff, profile, period, "replica")
            fixed_results.append({"ticker": ticker, **comparison(expected, fixed)})
    counts = {field: sum(r["checks"][field] for r in results) for field in FIELDS}
    return {"profile": asdict(profile), "mode": "replica", "cases": len(results), "field_matches": counts,
            "price_inputs": [{"ticker": ticker, "source": prices.source, "price_field": prices.price_field,
                              "sha256": prices.sha256, "cutoff_exclusive": cutoff.isoformat()}
                             for ticker, prices, refs, cutoff in data],
            "window_matching_cases": sum(r["checks"]["entry_day"] and r["checks"]["hold_days"] for r in results),
            "fully_matching_cases": sum(r["all_match"] for r in results),
            "fixed_window_formula": {"cases": len(fixed_results),
                "average_matches": sum(r["checks"]["avg_return"] for r in fixed_results),
                "displayed_average_matches": sum(r["displayed_average_match"] for r in fixed_results),
                "win_matches": sum(r["checks"]["win_rate"] for r in fixed_results),
                "sample_matches": sum(r["checks"]["sample_count"] for r in fixed_results), "details": fixed_results},
            "details": results,
            "replication_complete": bool(results) and all(r["all_match"] for r in results)}


def report_html(path, report):
    details = report.get("details", [])
    body = []
    for row in details:
        expected, actual = row["expected"], row["actual"]
        cells = [row["ticker"], str(row["month"])]
        for field in FIELDS:
            e = expected[field]
            a = actual[field] if actual else "없음"
            if field in ("avg_return", "win_rate"):
                e = f"{e * 100:.4f}%"
                a = f"{a * 100:.4f}%" if actual else a
            cells.append(f"{e} / {a}")
        cells.append("일치" if row["all_match"] else "차이 있음")
        body.append("<tr>" + "".join("<td>" + html.escape(s) + "</td>" for s in cells) + "</tr>")
    f = report.get("fixed_window_formula", {})
    sources = report.get("price_inputs", [])
    source_note = "사이트 가격 스냅샷으로 계산 방식만 대조했습니다. 독립 가격 공급자 검증과는 별개입니다." if any("easyinvesting" in s.get("source", "") for s in sources) else "가격 출처는 아래 입력 기록을 확인하세요."
    hypothesis = report.get("price_basis_hypothesis")
    hypothesis_note = "<p>이 연구 비교에는 공식 배당 이력으로 복원한 주식 종가 추정값이 포함됩니다. 독립 가격 캐시 이후 차트 가격을 일반 종가로 취급하는 가정이 있으며, 전체 독립 원자료 검증은 미완료입니다.</p><details><summary>가격 기준 가설과 부분 검증</summary><code>" + html.escape(json.dumps(hypothesis, ensure_ascii=False, indent=2)) + "</code></details>" if hypothesis else ""
    alignment_note = "<p>재현용 윤년 경계 가설: 분석 첫해 이후 윤년에 진입하고 다음 해에 청산하는 표본은 한 거래일을 추가합니다. 관측 응답을 설명하는 가설이며 사이트 서버 산식은 확인하지 못했습니다. 투자 모드는 실제 보유 거래일을 유지합니다.</p>" if report.get("profile", {}).get("cross_year_alignment") == "leap_after_first_year" else ""
    text = f"""<!doctype html><html lang='ko'><meta charset='utf-8'><title>계절성 비교 결과</title>
<style>body{{font:15px system-ui;margin:35px;color:#15213a;background:#f7f9fc}}main{{max-width:1400px;margin:auto}}
table{{border-collapse:collapse;background:white;width:100%}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #dde3ee;font-size:13px}}
.cards{{display:flex;gap:18px;flex-wrap:wrap}}.card{{background:white;padding:20px;border-radius:12px}}code{{white-space:pre-wrap}}h1{{font-size:28px}}
</style><main><h1>사이트 기준값과 재현 모드 계산 비교</h1>
<p>상태: {'재현 검증 통과' if report.get('replication_complete') else '재현 미완료 — 차이를 아래에 기록'}.</p>
<p>{html.escape(source_note)}</p>
{hypothesis_note}
{alignment_note}
<div class='cards'><div class='card'>전체 최적화 일치<br><strong>{report.get('fully_matching_cases',0)} / {report.get('cases',0)}</strong></div>
<div class='card'>진입일·보유기간 동시 일치<br><strong>{report.get('window_matching_cases',0)} / {report.get('cases',0)}</strong></div>
<div class='card'>지정 구간 평균 수익률 정밀 일치<br><strong>{f.get('average_matches',0)} / {f.get('cases',0)}</strong></div>
<div class='card'>지정 구간 평균 화면 표시 일치<br><strong>{f.get('displayed_average_matches',0)} / {f.get('cases',0)}</strong></div>
<div class='card'>지정 구간 승률 계산 일치<br><strong>{f.get('win_matches',0)} / {f.get('cases',0)}</strong></div></div>
<p>각 칸은 사이트 값 / 독립 계산 값. 수익률 허용 오차는 0.0002%p, 날짜·기간·표본 수는 정확히 비교.
지정 구간 계산은 사이트의 날짜를 입력받은 진단이며, 최적 구간을 독립적으로 찾았다는 뜻이 아닙니다.</p>
<p>프로필: <code>{html.escape(json.dumps(report.get('profile'),ensure_ascii=False))}</code></p>
<details><summary>가격 출처·파일 해시·계산 기준일</summary><code>{html.escape(json.dumps(sources,ensure_ascii=False,indent=2))}</code></details>
<div style='overflow:auto'><table><thead><tr>{''.join('<th>'+x+'</th>' for x in ['종목','월','진입 연초 일수','청산 연초 일수','보유 거래일','평균 수익률','승률','표본','결과'])}</tr></thead>
<tbody>{''.join(body)}</tbody></table></div></main></html>"""
    Path(path).write_text(text, encoding="utf-8")


def calibrate(args):
    data = dataset(args.evidence, args.tickers)
    trials = []
    best = None
    objectives = ("win_mean", "win_daily", "mean", "sharpe", "win_median")
    grids = [(1, 0)] + [(7, x) for x in range(7)]
    count = 0
    # Finite hypothesis loop. No per-ticker exceptions or target-value copying.
    for date_mode, roll, hold_offset in itertools.product(("doy", "month_day"), ("next", "previous"), (0, -1)):
        base = Profile(date_mode=date_mode, roll=roll, hold_offset=hold_offset)
        rows = {}
        for ticker, prices, refs, cutoff in data:
            for expected in refs:
                rows[ticker, expected["month"]] = all_windows(prices, expected["month"], cutoff, base)
        scoring = {(ticker, month, policy): [(r, selection_stats(r, policy)) for r in pool]
                   for (ticker, month), pool in rows.items()
                   for policy in ("inclusive", "past_entry_years", "past_exit_years")}
        for policy, (step, offset), objective in itertools.product(("inclusive", "past_entry_years", "past_exit_years"), grids, objectives):
            profile = replace(base, entry_step=step, entry_offset=offset, objective=objective, selection_history=policy)
            details = []
            for ticker, prices, refs, cutoff in data:
                for expected in refs:
                    pool = [(r, score) for r, score in scoring[ticker, expected["month"], policy]
                            if score and (r["entry_day"] - offset) % step == 0]
                    actual = max(pool, key=lambda pair: objective_key(pair[1], objective))[0] if pool else None
                    details.append({"ticker": ticker, **comparison(expected, actual)})
            matched = sum(r["all_match"] for r in details)
            windows = sum(r["checks"]["entry_day"] and r["checks"]["hold_days"] for r in details)
            fields = sum(sum(r["checks"].values()) for r in details)
            # Report the chosen fit transparently; do not conceal mismatches.
            score = (matched, windows, fields)
            trial = {"iteration": count + 1, "profile": asdict(profile), "full_cases": matched,
                     "window_matches": windows, "field_matches": fields}
            trials.append(trial)
            if best is None or score > best[0]:
                best = (score, profile)
            count += 1
            if count % 40 == 0:
                print(f"iteration {count}: best full/window/fields = {best[0]}", flush=True)
            if count >= args.max_iterations or matched == len(details):
                break
        if count >= args.max_iterations or best[0][0] == sum(len(x[2]) for x in data):
            break
    final = evaluate_profile(data, best[1])
    final["iterations"] = count
    final["training_tickers"] = args.tickers
    final["data_dependency"] = "Frozen website chart prices used only to isolate formula mismatch. Independent provider parity still required."
    final["trials"] = trials
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "calibration.json", final)
    write_json(out / "best_profile.json", {"profile": asdict(best[1]), "replication_complete": final["replication_complete"]})
    report_html(out / "comparison.html", final)
    print(f"{count} iterations; complete parity: {final['fully_matching_cases']}/{final['cases']}")
    print("fixed-window formula:", {k: v for k, v in final["fixed_window_formula"].items() if k != "details"})
    return 0 if final["replication_complete"] else 2


def compare(args):
    report = evaluate_profile(dataset(args.evidence, args.tickers, args.period), profile_from_json(args.profile), args.period)
    write_json(args.out, report)
    report_html(Path(args.out).with_suffix(".html"), report)
    print(f"complete parity: {report['fully_matching_cases']}/{report['cases']}")
    return 0 if report["replication_complete"] else 2


def analyze(args):
    profile = profile_from_json(args.profile) if args.profile else Profile()
    prices = PriceSeries.load(args.prices, args.ticker, args.field)
    cutoff = date.fromisoformat(args.asof)
    rows = [optimize(prices, month, cutoff, profile, 10, args.mode) for month in range(1, 13)]
    write_json(args.out, {"ticker": prices.ticker, "mode": args.mode, "asof_exclusive": args.asof,
                        "source": prices.source, "price_field": prices.price_field, "price_sha256": prices.sha256,
                        "profile": asdict(profile), "rows": [r for r in rows if r]})
    print(f"{prices.ticker}: {sum(r is not None for r in rows)} months -> {args.out}")
    return 0


def load_sessions(path):
    records = list(csv.DictReader(Path(path).read_text().splitlines()))
    sessions = [date.fromisoformat(r["Date"]) for r in records]
    if sessions != sorted(set(sessions)):
        raise ValueError("Calendar must be sorted and unique")
    return sessions


def calendar_command(args):
    try:
        import exchange_calendars as xc
    except ImportError as exc:
        raise SystemExit("Install optional exchange calendar: python3 -m pip install -r requirements.txt") from exc
    cal = xc.get_calendar("XNYS", start=args.start, end=args.end)
    dates = cal.sessions
    with Path(args.out).open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Date"])
        writer.writerows([[d.date().isoformat()] for d in dates])
    return 0


def monthly_signals(prices, assets, sessions, target_year, month, cutoff, profile):
    signals, excluded = [], []
    for ticker, asset in assets.items():
        if ticker not in prices:
            excluded.append({"ticker": ticker, "reasons": ["price file missing"]})
            continue
        row = optimize(prices[ticker], month, cutoff, profile, mode="investment")
        if row is None:
            excluded.append({"ticker": ticker, "reasons": ["10 completed observations unavailable"]})
            continue
        reasons = rejection_reasons(row, asset)
        if reasons:
            excluded.append({"ticker": ticker, "reasons": reasons})
            continue
        row.update(kind=asset["kind"], decision_date=cutoff.isoformat())
        scheduled = schedule_row(row, target_year, sessions, profile)
        if scheduled["entry"] < cutoff.isoformat():
            excluded.append({"ticker": ticker, "reasons": ["original entry date has passed"]})
            continue
        signals.append(scheduled)
    return signals, excluded


def load_universe(args):
    assets = json.loads(Path(args.universe).read_text())["assets"]
    prices = {}
    for ticker in assets:
        path = Path(args.data) / f"{ticker}.csv"
        if path.exists():
            prices[ticker] = PriceSeries.load(path, ticker, args.field)
    return assets, prices


def plan(args):
    assets, prices = load_universe(args)
    profile = profile_from_json(args.profile)
    sessions = load_sessions(args.calendar)
    cutoff = date.fromisoformat(args.asof)
    signals, excluded = monthly_signals(prices, assets, sessions, args.year, args.month, cutoff, profile)
    incumbents = json.loads(Path(args.positions).read_text())["positions"] if args.positions else []
    for position in incumbents:
        if not position["entry"] < args.asof < position["exit"]:
            raise ValueError("Incumbent must be held across the plan asof date")
    all_signals = incumbents + signals
    events = [e for e in event_schedule(all_signals) if e["date"] >= args.asof]
    write_json(args.out, {"asof_exclusive": args.asof, "profile": asdict(profile), "signals": signals,
                        "incumbents": incumbents, "excluded": excluded, "events": events,
                        "status": "research prototype; exact website optimization not yet verified"})
    print(f"eligible signals: {len(signals)}; scheduled portfolio events: {len(events)}")
    return 0


def walkforward(args):
    assets, prices = load_universe(args)
    profile = profile_from_json(args.profile)
    sessions = load_sessions(args.calendar)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    signals = []
    decisions = []
    current = date(start.year, start.month, 1)
    while current <= end:
        # The current month's observations cannot affect its own selection.
        cutoff = current
        month_signals, excluded = monthly_signals(prices, assets, sessions, current.year, current.month, cutoff, profile)
        signals.extend(s for s in month_signals if start.isoformat() <= s["entry"] <= end.isoformat() and s["exit"] <= end.isoformat())
        decisions.append({"asof_exclusive": cutoff.isoformat(), "eligible": len(month_signals), "excluded": excluded})
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    events = event_schedule(signals)
    result = simulate(events, prices, args.capital, args.cost_bps)
    result.update(signals=signals, decisions=decisions, events=events,
                  requested_start=args.start, requested_end=args.end,
                  coverage_note="Trades whose exits extend beyond the requested end are omitted, not force-liquidated.",
                  universe_note="User-supplied current universe; no historical delisted-security universe. Survivorship bias remains.")
    write_json(args.out, result)
    print(f"return={result['return']:.2%}, max drawdown={result['max_drawdown']:.2%}; events={len(events)}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("download")
    p.add_argument("tickers", nargs="+"); p.add_argument("--start", default="2000-01-01")
    p.add_argument("--end", required=True); p.add_argument("--out", default="data")
    p.add_argument("--provider", choices=["yahoo", "yfinance"], default="yahoo"); p.set_defaults(func=download)
    p = sub.add_parser("capture")
    p.add_argument("tickers", nargs="+"); p.add_argument("--periods", nargs="+", type=int, default=[10])
    p.add_argument("--out", default="evidence"); p.add_argument("--include-chart", action="store_true"); p.set_defaults(func=capture)
    p = sub.add_parser("calibrate")
    p.add_argument("--evidence", default=str(ROOT / "evidence")); p.add_argument("--tickers", nargs="+", default=["SPY", "QQQ", "AAPL"])
    p.add_argument("--max-iterations", type=int, default=960); p.add_argument("--out", default=str(ROOT / "results")); p.set_defaults(func=calibrate)
    p = sub.add_parser("compare")
    p.add_argument("--evidence", default=str(ROOT / "evidence")); p.add_argument("--tickers", nargs="+", required=True)
    p.add_argument("--period", type=int, default=10); p.add_argument("--profile", required=True)
    p.add_argument("--out", default="results/holdout.json"); p.set_defaults(func=compare)
    p = sub.add_parser("analyze")
    p.add_argument("--prices", required=True); p.add_argument("--ticker"); p.add_argument("--field", default="Close")
    p.add_argument("--asof", required=True); p.add_argument("--profile"); p.add_argument("--mode", choices=["replica", "investment"], default="investment")
    p.add_argument("--out", default="results/analysis.json"); p.set_defaults(func=analyze)
    p = sub.add_parser("calendar")
    p.add_argument("--start", required=True); p.add_argument("--end", required=True); p.add_argument("--out", default="calendar.csv"); p.set_defaults(func=calendar_command)
    for command in ("plan", "walkforward"):
        p = sub.add_parser(command)
        p.add_argument("--universe", default="config/universe.example.json"); p.add_argument("--data", default="data")
        p.add_argument("--field", default="Adj Close"); p.add_argument("--calendar", required=True)
        p.add_argument("--profile", required=True); p.add_argument("--out", default=f"results/{command}.json")
        if command == "plan":
            p.add_argument("--asof", required=True); p.add_argument("--year", type=int, required=True); p.add_argument("--month", type=int, required=True)
            p.add_argument("--positions"); p.set_defaults(func=plan)
        else:
            p.add_argument("--start", required=True); p.add_argument("--end", required=True)
            p.add_argument("--capital", type=float, default=10000); p.add_argument("--cost-bps", type=float, default=5); p.set_defaults(func=walkforward)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
