# 계절성 분석 프로그램

미국 개별주식과 미국 상장 일반 ETF의 일별 가격으로 계절성을 직접 계산합니다.
GitHub 저장소: [INPYoe/investing_strategy_season](https://github.com/INPYoe/investing_strategy_season).
사이트 결과는 비교 기준이며, 독립 분석 실행에는 필요하지 않습니다.

## 현재 상태

이 버전은 연구용 초기 구현입니다. **사이트의 최적 구간 전체 재현은 미완료**입니다.
사이트 값으로 결과를 덮어쓰거나 종목·월별 예외를 넣어 일치를 만들어내지 않습니다.

가격·윤년 경계 실험 결과는 **최적 구간 전체 13/36**, 지정 구간 모든 필드 **36/36 일치**입니다.
주식 가격 기준을 복원하는 가정이 포함돼 있으며 전체 독립 원자료 검증은 미완료입니다.
자세한 근거와 한계는 아래 추가 반복 기록 및 `results/research/year_boundary/comparison.html`을 확인하세요.
아래 9/36은 원본 가격 스냅샷 기준의 재실행 결과입니다.

시도한 계산 방식과 다음 검증 순서는 [재현 조사 계획](REPRODUCTION_PLAN.md)에 정리했습니다.
가격은 사용자의 지침에 따라 상위 `Investing_Researcher`의 기존 CSV·Parquet 캐시를 먼저 사용합니다.
[캐시 조사 결과](results/diagnostics/parent_cache_inventory.json)에 기간·열·해시·마지막 봉의 가격 충돌을 기록했습니다.
최신 [72건 단계별 비교표](results/diagnostics/selection_diagnosis.html)에서는 전체 일치 19건,
후보에 같은 거래 구간이 없는 사례 31건, 후보는 있지만 선택이 다른 사례 22건으로 분류했습니다.
이는 가격·윤년 연구 프로필의 진단이며 원본 생산 프로필을 교체한 결과가 아닙니다.

- SPY·QQQ·AAPL, 각 12개월의 기준 응답과 당시 가격을 보관했습니다.
- 연초 일수/월·일, 휴장일 전·후, 보유 거래일, 진입일 탐색 간격, 최적화 목표를 바꾸어 960개 설정을 비교했습니다.
- 최적 구간 전체 필드 일치: **9/36**. 진입일과 보유기간 동시 일치: **13/36**.
- 사이트 진입일·보유기간을 입력한 수익률 계산: 승률·표본 수 **36/36**, 평균 수익률 **27/36** 정밀 일치. 화면의 소수점 한 자리 평균 표시는 **30/36** 일치합니다.
- 별도 GLD 10년 검증: **0/12** 전체 일치. SPY·QQQ 5년 검증: **5/24** 전체 일치. 따라서 현재 최적화 규칙이 사이트와 같다고 주장할 수 없습니다.
- 원본 파일의 테스트는 28개였으며 실행으로 확인했습니다. 진단·실험·배당·윤년 경계·일별 곡선·자동 반복・수집 오류 검증을 추가한 현재 테스트는 **92개** 통과했습니다. 이전 대화의 32개는 원본 파일 상태에서 확인되지 않았습니다. 테스트 통과는 사이트 일치 또는 투자 수익성 검증과는 다릅니다.

### 접근 복구 후 윤년 경계 연구

가격 기준 변환과 재현 전용 `cross_year_alignment=leap_after_first_year`를 함께 적용하면 지정 구간의 날짜·보유기간·평균·승률·표본은 학습 **36/36**, GLD **12/12**, 별도 5년 **24/24** 모두 기존 허용오차 안에서 일치합니다. 이 규칙은 분석 첫해 이후 윤년에 진입하여 다음 해에 청산할 때 한 거래일을 추가하는 전역 관측 가설입니다. 종목·월별 예외는 없으며, 서버 소스를 확인한 규칙은 아닙니다. 투자 모드는 이 가설을 무시하고 실제 보유 거래일을 사용합니다. 가격 복원의 원자료 한계와 미사용 기간 검증은 남아 있습니다.

최적 구간 선택은 960개 설정의 최고 **13/36**, GLD **0/12**, 별도 5년 **6/24**입니다. 수정된 가격·윤년 가설로 날짜 선택·표시 분리 5,760개 설정을 다시 비교해도 개선되지 않았습니다. 완료 연도 범위를 분리한 2,560개 가설은 11/36, 연중 거래일 지점에서 고르는 1,950개 가설은 6/36으로 기본 선택 규칙을 대체하지 못했습니다.

공개 제작자 설명서의 SPY 2006~2025년 6월 지정 구간은 평균 표시 1.7%·승률 90%가 일치했습니다(`results/research/creator_guide_fixed_window.json`). 이는 구간 선택 검증과 구분합니다.

```bash
python3 research_year_boundary.py --raw-cache ../market_detector/data/cache/prices --append-raw-tail --normalize-vintage
```
- 독립 Yahoo 원자료 확보는 미완료입니다. 아래 네트워크 진단에서 일반 터미널의 사용자 보고와 Codex 실행 결과를 구분합니다. 사이트 가격은 **교정 진단용**으로만 포함합니다.

### 자동 이어가기

미완료 작업과 완료 조건은 `TODO.md`, 상세 인계 기록은 `CONTINUE.md`에 있습니다.
다음 명령으로 Codex 반복 실행을 직접 시작할 수 있습니다.

```bash
./auto-codex.sh 'TODO.md의 미완료 연구를 이어서 진행해줘'
```

스크립트는 설치된 CLI에서 확인한 `--approve-for-me --sandbox workspace-write`를 사용합니다.
이 CLI는 `--full-auto`를 거부했습니다. Git 저장소가 아닌 이 폴더에서 실행할 수 있도록
`--skip-git-repo-check`를 명시합니다. 권한 검토·샌드박스 우회 옵션은 사용하지 않습니다.
[OpenAI 공식 비대화형 실행 문서](https://learn.chatgpt.com/docs/non-interactive-mode)의
JSON 이벤트와 최종 응답 파일을 이용해 새 세션 ID를 고정하여 재개합니다.
프롬프트·도구 출력에 인용된 완료 표식은 완료로 세지 않으며 최종 응답 마지막 줄과
미완료 TODO를 함께 확인합니다. CLI 한도 오류는 30분 후 재시도하고 다른 실행 오류는 중단합니다.
`log.txt`와 `auto-codex-last-message.txt`는 매 실행마다 갱신됩니다.
이 스크립트가 알고리즘 일치 자체를 보장하지는 않습니다. 재현 연구는 아직 미완료입니다.

### 일별 곡선 표시 연구

`research_daily_curve.py`는 보관된 SPY 일별 표시를 가격만으로 재구성합니다.
2016~2025년을 각각 첫 가격 대비 수익률로 정규화하고 252개 지점으로 선형 보간하면
평균 표시 250/252, 일별 상승 승률 표시·표본 수 각 252/252가 일치합니다.
11개 지점의 3차 다항식으로 평활하면 평활 평균 표시 251/252가 일치합니다.
날짜 인덱스를 내림하면 251/252, 보간 좌표를 소수점 둘째 자리로 반올림한 뒤 내림하는
가설은 252/252입니다. 원본 가격은 소수점 넷째 자리 스냅샷이며 남은 표시 차이도 유지합니다.
이는 화면 곡선에 관한 관측 가설이며 서버 소스나 최적 구간 선택을 확인한 것은 아닙니다.
결과와 평활·날짜 가설 전체 시행은 `results/research/daily_curve_audit.json`에 있습니다.

```bash
python3 research_daily_curve.py
```

일별 곡선을 근거로 추가 비교한 가설도 최적 선택을 개선하지 못했습니다.
다음 표의 일치는 진입일·청산일·보유기간·평균·승률·표본 수 전체를 뜻하며,
세 번째 열은 학습 자료만으로 고른 한 설정을 기존 GLD·5년 진단 자료에 적용한 결과입니다.

| 연구 | 전역 설정 수 | 학습 / GLD / 별도 5년 전체 일치 |
|---|---:|---|
| 곡선 저점 진입 후보 | 1,800 | 10/36 · 0/12 · 3/24 |
| 정규화 가격 선택과 내림 날짜 표시 | 2,340 | 5/36 · 0/12 · 3/24 |
| 수익률·승률 점수 평활 및 최근 완료 표본 | 2,560 | 13/36 · 0/12 · 7/24 |
| 곡선 날짜를 주간 후보로 변환 | 2,340 | 8/36 · 0/12 · 4/24 |

결과는 각각 `results/research/curve_candidates.json`, `annual_curve.json`,
`window_smoothing.json`, `curve_grids.json`입니다. 학습 전체 일치가 개선되지 않아
기준 계산을 대체하지 않았습니다. 점수 평활은 보고할 승률·수익률을 변경하지 않습니다.
이미 분석에 쓴 GLD·5년은 미사용 검증으로 세지 않습니다.

후보 날짜 자체도 점검했습니다. 캘린더 7일 간격과 연중 지점 5/7개 간격의
158개 전역 형식 중 최고는 학습 기준 진입일 **24/36**만 후보에 포함합니다
(`results/research/candidate_geometry.json`). 이 수치는 최적 구간 일치가 아닌 후보 포함 여부입니다.
시험한 주간 형식은 점수만 바꾸어 36건 전체를 재현할 수 없으므로 새 후보 생성 근거가 필요합니다.
선택에 사용한 가격 시점과 보고 통계 갱신 시점을 분리한 1,280개 전역 가설도 비교했습니다.
일별 후보를 원본/복원 가격 및 현재/연초/직전 분기/전년 시점에서 선택하고 현재 통계로 보고합니다.
학습에서 고른 설정은 전체 6/36, GLD 1/12, 별도 5년 1/24로 개선되지 않았습니다
(`results/research/selection_vintage.json`). 생산 최적화 규칙은 유지합니다.

### 기존 캐시로 수행한 단계별 진단과 독립 검산

`research_selection_diagnosis.py`는 기준의 명목 날짜뿐 아니라 연도별 실제 진입·청산 벡터도 비교합니다.
지정 구간 모든 필드는 72/72 일치했습니다. 주간 후보로 최적 구간을 독립 선택하면 다음과 같습니다.

| 자료 | 전체 일치 | 같은 거래 구간이 후보에 없음 | 후보 존재·선택 차이 |
|---|---:|---:|---:|
| 학습 36건 | 13 | 12 | 11 |
| GLD 12건 | 0 | 12 | 0 |
| 별도 5년 24건 | 6 | 7 | 11 |
| 합계 72건 | 19 | 31 | 22 |

지정 구간 계산·동률·같은 거래의 표시 차이로 분류된 사례는 없습니다.
이 분류는 현재 연구 프로필에 대한 것이므로 사이트의 내부 후보 생성·점수 규칙을 확인한 것은 아닙니다.
[독립 계산](independent_window_math.py)은 생산 계산과 캐시를 호출하지 않고 13,140개 후보의
연도별 거래·통계를 검산했습니다. 불일치는 0건, 최대 수치 차이는 약 1.39×10⁻¹⁷입니다.
독립 선택 72건과 캐시 사용 전·후 72건도 같습니다. 분석 입력 6개 묶음에는 거래소 달력 대비 누락 세션이 없었습니다.
근거: [상세 JSON](results/diagnostics/selection_diagnosis.json), [비교표](results/diagnostics/selection_diagnosis.html).

선택 시점 연구의 보고 캐시키에서 기준일·가격 입력 누락을 발견해 수정했습니다.
두 회귀 테스트는 수정 전 실패하고 수정 후 통과했습니다. 기존 1,280개 설정을 재실행한 전체 JSON은
수정 전과 같아서 이 버그는 해당 실험의 사이트 불일치 원인이 아닙니다.
[수정 영향 확인](results/diagnostics/cache_recheck.json)에 기록했습니다.

보유 중 최대 낙폭·진입가 대비 손실 제한 66개 전역 설정도 시험했으나
13/36·GLD 0/12·5년 6/24를 개선하지 못해 채택하지 않았습니다.
같은 진입 연도에서 평균·승률과 조사한 위험 지표 모두가 열등하지 않은 다른 후보가 존재하는 기준 구간은 29/72입니다.
따라서 조사한 위험 점수만으로 전체 선택을 설명하기 어렵습니다. 숨은 후보 제약이나 다른 입력까지 배제하지는 않습니다.
[보유 중 위험 연구](results/research/holding_risk.json)는 실제 투자 모드의 최종 수익률 -10% 기준과 구분합니다.

상위 Parquet 7,255개와 가격 CSV 518개의 날짜 범위를 조사했고, 이 두 경로에는 10년 이력을 담은 파일이 없었습니다.
대상 종목의 캐시 내부 누락 세션은 없지만 Parquet의 2026-05-15 종가는 6개 종목에서 CSV와 충돌합니다.
SPY·KO 마지막 Parquet 봉은 OHLC 일관성 검사도 실패했습니다. 두 원본을 보존하고 공급자·수집 시점은 미확인으로 기록했습니다.
근거: [가격 품질](results/diagnostics/existing_price_quality.json),
[Parquet 기간](results/diagnostics/parent_cache_date_ranges.csv), [CSV 기간](results/diagnostics/parent_csv_date_ranges.csv).

새 종목 MSFT·NVDA·KO·JPM의 저장된 Close와 Adj Close를 각각 이용한 2·3년 계산 70,080개와
월별 선택 384건도 독립 구현과 같았습니다. 이 종목의 사이트 기준 응답은 없어 사이트 선택 일치 검증으로 세지 않습니다.
실제 투자 모드 기본 10개 완료 표본으로 검사한 17,520개 구간은 모두 자료 부족으로 반환되지 않았습니다.
[새 종목 검산 결과](results/diagnostics/new_ticker_math.json)에 입력 해시·기간·표본 수를 기록했습니다.
외부 가격 요청 없이 기존 파일만 읽었으며, 기준값·허용오차·투자 모드 정책은 유지했습니다.

```bash
python3 research_selection_diagnosis.py --append-raw-tail --normalize-vintage
python3 research_holding_risk.py
python3 audit_new_ticker_math.py
# Parquet 읽기는 상위 프로젝트의 기존 pyarrow 설치 환경 사용
../.venv/bin/python -B audit_existing_prices.py --survey-all
```

### 2026-10-05 네트워크와 브라우저 진단

사용자는 일반 macOS 터미널에서 Yahoo 호스트 DNS 조회 성공과 curl HTTP/2 429를 보고했습니다.
Codex에서 `socket.getaddrinfo`는 `gaierror(8)`로 실패했고,
`dig +time=2 +tries=1 query1.finance.yahoo.com A`는 `bind: Operation not permitted`
후 종료 코드 10으로 끝났습니다. 후자는 DNS 응답을 받기 전 소켓 바인딩 거부이며 NXDOMAIN이 아닙니다.
이는 실행 환경별 차이이며 Yahoo 전체 DNS 장애로 판단하지 않습니다. 정확한 resolver 실패 원인은 미확정입니다.

기본 `download --provider yahoo`가 사용하는 `/v8/finance/chart/SPY` 주소에
2026-09-28부터 2026-10-03 제외 구간을 **GET 한 번** 요청했습니다.
리디렉션과 자동 재시도는 하지 않았으며 DNS 오류 8로 HTTP 응답을 받지 못했습니다.
따라서 이번 요청의 429 여부와 `Retry-After`는 확인 불가입니다. 이후 실제 Yahoo 요청은 추가하지 않았습니다.
선택 SDK인 `yfinance` 내부 요청을 검사한 것은 아닙니다.
명령 결과·정확한 URL·요청 헤더는 `results/diagnostics/network_environment.json`과
`price_api_probe.json`에 있습니다.

다운로드는 429가 발생하면 다음 종목 요청을 중단하고 기존 CSV를 보존합니다.
`Retry-After`가 있으면 초 또는 HTTP 날짜를 해석해 `download_rate_limit.json`에 저장하고,
같은 출력 폴더에서 그 시각 전에 다시 실행하면 API를 호출하지 않고 종료 코드 2를 반환합니다.
헤더가 없거나 해석 불가하면 자동 재시도 시각을 추측하지 않습니다.
[RFC 9110의 Retry-After 정의](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after)를 따릅니다.
모의 429·캐시 보존·대기 시간 중 호출 금지·정상 CSV 수집을 테스트했습니다.

브라우저 도구의 현재 오류는 `CUA_REPL_ENABLED_SURFACES is required`입니다.
로컬 로그의 과거 MCP 연결 성공과 다른 스레드의 `status=ready` 기록을 확인했지만
현재 오류의 상세 예외 스택은 찾지 못했습니다. 누락된 CUA 필수 설정을 가리키는 오류이며
Yahoo DNS·429와 별개입니다. 정확한 도구 응답과 로그 발췌는
`results/diagnostics/browser_initialization.json`에 보관합니다.
오프라인 재계산은 지정 구간 모든 필드 **72/72**, 원본 evidence 13개 해시 불변입니다.
이는 독립 최적 선택 전체 일치와 구분합니다. 전체 테스트 92개 통과 로그는
`results/diagnostics/unittest.log`에 있습니다.

## 빠른 실행 — 인터넷 없이 비교 재현

압축을 풀고 터미널에서 폴더로 이동합니다. Python 3.10 이상을 사용하세요.

```bash
git clone https://github.com/INPYoe/investing_strategy_season.git
cd investing_strategy_season
python3 -m unittest -v
python3 lab.py calibrate --max-iterations 960
open results/comparison.html
```

`calibrate`와 `compare`는 차이가 남으면 종료 코드 **2**를 반환합니다. 이것은 프로그램 오류가 아니라
재현 미완료를 나타냅니다. 입력 오류는 1, 모든 사례가 일치하면 0입니다.

`results/calibration.json`에는 모든 시행과 필드별 차이가, `results/best_profile.json`에는
가장 잘 맞았던 **임시 계산 설정**이 있습니다. GLD 및 다른 기간 검증은 다음과 같습니다.

```bash
python3 lab.py compare --tickers GLD --profile results/best_profile.json --out results/holdout_GLD.json
python3 lab.py compare --tickers SPY QQQ --period 5 --profile results/best_profile.json --out results/holdout_5year.json
```

## 2026-10-05 실행 검증과 추가 실험

**추가 반복에서 주식 가격 기준 가설이 개선됐습니다.** 공식 배당 이력으로 일반 종가를 복원하고
외부 Close 캐시에 연결한 주식 가격 기준으로 960개 설정을 다시 비교했습니다.
전체 최적 구간 일치는 **13/36**, 지정 평균은 **31/36 정밀 일치·34/36 화면 표시 일치**입니다.
AAPL 지정 구간은 모든 비교 필드가 **12/12** 일치합니다. GLD 전체 0/12, SPY·QQQ 5년 전체 5/24는 아직 그대로입니다.
새 결과는 `results/research/dividends/comparison.html`과 `calibration.json`에 보관했습니다.
기존 `results/comparison.html`·`calibration.json`은 원본 가격 기준 9/36을 확인하는 기록입니다.

복원 계산은 사이트 기준 진입일·수익률을 입력받지 않습니다. Apple 공식 배당 이력과 2020년 분할,
결제 주기 변경 및 비결제일 규칙을 이용한 배당락일 추정이 입력입니다.
복원한 과거 Close를 독립 프로젝트의 598개 가격과 대조한 최대 차이는 약 $0.000079입니다.
다만 그 캐시 이후 차트 가격을 일반 종가로 취급하는 가정이 있으며, 후속 93개 가격 모두 센트 단위라는
관찰만으로 전 기간 독립 가격 검증이 끝났다고 주장하지 않습니다.
ETF는 기존 사이트 차트 가격을 사용합니다. 이 가격 기준 가설은 재현 연구에만 적용하며 투자 모드는 변경하지 않았습니다.

```bash
python3 research_stages.py
python3 research_dividends.py --raw-cache ../market_detector/data/cache/prices --raw-field close --append-raw-tail
```

후자는 이 환경의 기존 캐시 위치를 명시하는 재현 명령입니다. 다른 환경에서는 확보한 일반 종가 CSV 폴더를
사용하세요. `--append-raw-tail`은 검증되지 않은 후속 차트 구간을 일반 종가로 가정한다는 명시적 연구 옵션입니다.
옵션이 없으면 후속 구간을 조용히 대체하지 않고 중단합니다.
원자료 해시와 배당 출처, 캐시 연결 시점, 가정은 결과에 기록합니다.
선택 날짜와 표시 날짜를 분리한 5,760개 설정에서는 기존 전체 일치 9/36을 넘어서는 결과를 찾지 못했습니다.

배당 출처: [Apple 공식 배당·분할 이력](https://investor.apple.com/dividend-history/default.aspx).
배당락일 추정 규칙: [FINRA 결제 주기](https://www.finra.org/investors/insights/understanding-settlement-cycles),
[FINRA 11140](https://www.finra.org/rules-guidance/rulebooks/finra-rules/11140),
[연준 결제 휴일](https://www.federalreserve.gov/aboutthefed/k8.htm).

원본 960개 설정을 다시 실행해 9/36 전체 일치, 13/36 진입일·보유기간 동시 일치,
지정 구간 평균 27/36 정밀 일치 및 30/36 화면 표시 일치를 확인했습니다.
GLD의 12/12는 **지정 구간 승률·표본 수**입니다. 평균은 10/12 정밀 일치·11/12 표시 일치,
최적 구간 전체는 0/12입니다. SPY·QQQ 5년 전체 일치는 5/24입니다.
재실행 원본은 `results/baseline_verified`에 보관했습니다.

```bash
python3 -m unittest -v
python3 research.py
```

`research.py`는 기본 설정, 일별 전수 탐색, 연초/월초 기준 주간 격자,
최적일 주변 1~3일 재탐색, 선택용 과거 기간 변경, 보유 1~30/1~60 거래일 탐색의
25개 전역 가설을 비교합니다. 선택 함수는 기준 진입일·보유기간을 받지 않습니다.
학습 자료만으로 설정을 선택하고, 그 뒤 GLD 10년과 SPY·QQQ 5년을 평가합니다.
이미 사용된 검증 자료이므로 이후에는 새 종목·기간의 미사용 자료로도 검증해야 합니다.
현재 선택 결과는 기존 설정으로 유지되며, 생산용 최적화 계산은 변경하지 않았습니다.
평균 오차 허용 범위와 기준 응답도 바꾸지 않았습니다. 종료 코드 2는 재현 미완료입니다.

`results/research/research.json`에는 전체 실험, 자료 해시, 날짜별 가격·수익률,
현재 격자 포함 여부, 일별 전수 후보 순위, 네 자리 가격 반올림의 가능한 평균 범위가 남습니다.
학습 자료의 12/36 진입일은 기존 격자 밖이며, 평균 불일치 9건은 가격 반올림 범위를 넘어섭니다.
탐색 격자만 바꾸거나 허용 오차를 늘리는 방식으로 해결할 근거가 없습니다.

새 Yahoo 요청은 이 실행 환경에서 DNS 실패로 중단됐습니다.
사이트 공개 화면은 접근했지만 공개 API 직접 요청은 브라우저에서 차단됐습니다.
다른 로컬 프로젝트의 SPY·QQQ·AAPL 가격 캐시로 부분 대조한 결과는
`results/price_audit.json`에 보관했습니다. 종목별 759·759·598 거래일의 겹치는 자료에서
QQQ·AAPL의 사이트 가격은 수정종가와 거의 같고 SPY는 수정종가 대비 비율 약 0.99743이 일정합니다.
확보된 구간의 지정 진입·청산 가격 쌍 35·36·28개에서 수정종가 수익률 차이는
각각 최대 0.0000004762·0.0000003291·0.0000005553입니다.
캐시에 종목별 공급자·수집 시각 기록이 없고 10년 자료가 아니므로 독립 원자료 전체 검증으로 세지 않습니다.
가격을 비율에 맞춰 조정하지 않았습니다. 아래 도구는 직접 확보한 CSV도 대조할 수 있습니다.

```bash
python3 price_audit.py --data data --tickers SPY QQQ AAPL --fields Close 'Adj Close' --source-note '공급자와 수집 시각을 기록하세요'
```

## 사이트 없이 가격을 수집하고 계산

독립 데이터 수집용 선택 의존성을 설치합니다. 분석·비교·CSV 입력 자체는 표준 라이브러리만 사용합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 lab.py download SPY QQQ GLD AAPL --provider yfinance --start 2000-01-01 --end 2026-10-03 --out data
python3 lab.py analyze --prices data/SPY.csv --field 'Adj Close' --asof 2026-10-05 --profile results/best_profile.json --mode investment
```

날짜는 실행하려는 시점에 맞게 바꾸세요. 다운로드 `--end`는 **해당 날짜를 제외**합니다.
파일에는 `Date,Close,Adj Close`가 들어갑니다. CSV를 직접 준비해도 됩니다.
수정종가와 일반 종가 중 무엇을 쓰는지 `--field`로 명시하며, 양쪽을 혼합하지 않습니다.
데이터 공급자 요청이 실패하면 오류를 기록하고, 사이트 가격으로 몰래 대체하지 않습니다.

최초 독립 원자료를 확보한 뒤 해야 할 검증은 종목별 가격 자체 비교 → 지정 구간 수익률 비교 →
독립 최적 구간 비교 → 별도 종목·기간 재검증입니다. 표본별 실제 매수·매도일과 수익률은 분석 JSON에 남습니다.

## 확정된 투자 규칙

`config/strategy.json`이 합의한 규칙을 기록하며 코드가 고정된 v1 규칙을 적용합니다.
이 파일을 수정해도 코드의 상한·필터가 자동으로 변경되지는 않습니다.

| 항목 | 규칙 |
|---|---|
| 자산 | 미국 개별주식, 미국 상장 일반 ETF. 해외 주식·채권·금·원자재 ETF 포함 |
| 제외 | 레버리지·인버스 ETF. 분류를 확인할 수 없는 ETF도 보류 |
| 과거 기록 | 최근 10년 범위에서 완료된 최신 10회 필수 |
| 승률 | ETF 80% 이상, 개별주식 90% 이상. 수익률 0은 승리로 세지 않음 |
| 최악 수익률 | 과거 구간 최종 수익률 −10% 이상. 보유 중 최대 낙폭과 별개 |
| 후보 순위 | 중앙값 내림차순. 동률은 승률, 최악 수익률, 티커 순으로 결정 |
| 보유 수 | 전체 5개 이하, 개별주식 3개 이하 |
| 배분 | 동일 비중. 1개면 100%, 0개면 현금 |
| 매매 | 월별로 후보와 일정을 확정. 진입·청산 때만 비중 조정 |
| 청산 | 최초 확정된 매도일 유지, 추가 매수분도 함께 청산. 중간 손절 없음 |
| 기존 보유 | 새 후보가 더 높은 순위여도 조기 청산하지 않음 |
| 슬롯 부족 | 원래 진입일에 공간이 없으면 그 신호를 건너뜀. 나중에 뒤늦게 진입하지 않음 |

마지막 세부 규칙과 동률 처리는 구현을 위한 명시적 기본값입니다. 변경하면 별도로 검증해야 합니다.

**보유기간에는 투자 규칙상의 하한·상한을 두지 않았습니다.** 현재 비교 프로필의 5·10·15·20·25·30 거래일
검색 격자는 관찰된 사이트 출력에서 출발한 검증 가설입니다. 사이트의 실제 검색 범위는 확인되지 않았습니다.
`Profile.holds`를 어떤 양의 거래일 목록으로도 변경할 수 있습니다. 이 임시 격자를 승인된 투자 제한으로 해석하지 마세요.

## 매매 달력과 월별 계획

거래소 달력은 가격과 분리합니다. 미래 휴장일을 주말만으로 추정하지 않습니다.

```bash
python3 lab.py calendar --start 2015-01-01 --end 2027-03-01 --out calendar.csv
python3 lab.py plan --data data --universe config/universe.example.json --calendar calendar.csv --profile results/best_profile.json --asof 2026-10-01 --year 2026 --month 10 --out results/october_plan.json
```

기존 보유가 있으면 `--positions`에 `{"positions":[...]}` JSON을 전달합니다. 각 보유는 ticker, kind,
entry, exit, median_return, win_rate, worst_return를 포함합니다. 최초 계획의 signal 레코드를 그대로 보관해 사용하면 됩니다.
계획일 전에 진입해 이후에 청산하는 기존 보유만 허용합니다. 캘린더에는 마지막 매도일까지 세션이 필요합니다.

`config/universe.example.json`의 4종목은 작동 예시이며 전체 투자 대상 목록이 아닙니다.
전 시장 자동 스크리닝에는 별도의 전체 티커 목록 및 ETF 분류 데이터가 필요합니다.

## 워크포워드 연구

```bash
python3 lab.py walkforward --data data --universe config/universe.example.json --calendar calendar.csv --profile results/best_profile.json --start 2026-01-01 --end 2026-09-30 --cost-bps 5 --capital 10000 --out results/walkforward.json
```

각 월 1일 이전 가격만으로 그 달의 구간을 선택합니다. 손절을 넣지 않으며, 비중 확대도 실제 시점부터
수익을 계산합니다. 비용은 매수·매도 양쪽 거래금액에 각각 적용하고 비용 이후 동일 비중을 계산합니다.
결과에는 매일 자산, 현금, 거래금액, 비용과 보유 수량을 기록합니다.

현재 연구 시뮬레이터는 소수점 수량·종가 체결을 가정합니다. 실제 주문이나 증권사 연동은 없습니다.
`Adj Close` 사용 시 수량은 수정 가격에 대한 연구용 단위이며 실제 증권사 주식 수량이 아닙니다.
환율·세금·호가 간격은 반영하지 않습니다. 과거 상장폐지 종목을 포함하는 시점별 전체 종목군도 아직 없으므로
현재 티커 목록 백테스트에는 생존 편향이 있습니다. 종료일 이후 청산할 거래는 테스트에서 제외한다고 출력에 명시합니다.
일별 가격이 누락되면 계산을 중단하지만, 입력 가격 시계열 자체에 빠진 거래일이 없는지는 별도 원자료 점검이 필요합니다.

## 다음 반복에서 해결할 차이

1. 독립 공급자 원자료 확보 및 사이트 원자료와 수정 방식·캐시 시점 비교.
2. 구간 선택 검색 격자와 목적 함수 확인. 현재 960개 전역 설정만으로는 재현되지 않습니다.
3. 윤년과 연말 경계, 화면 매도일 산출 방식 확인. 실제 보유 종료 세션과 화면 월·일을 구분합니다.
4. GLD 및 5년 기간에서 검증. 교정에 쓰지 않은 자료에서도 일치해야 재현 완료로 봅니다.
5. 재현 검증 후 독립 분석의 10개 완료 표본 정책을 적용하고 투자 전략 자체를 워크포워드로 검증.

사이트 10년 설정의 11개 표본 정책은 별도 `replica` 모드에만 있습니다. 투자 모드는 10개 완료 표본을 적용합니다.
사이트 수치 재현을 위한 매개변수 교정과 투자 수익을 높이기 위한 최적화는 서로 다른 작업입니다.

## 자료 출처

- 비교 기준 및 가격 스냅샷: https://easyinvesting.app/#/seasonality, 공개 화면 응답. 기준 응답 갱신 시각은 JSON `updated_at`에 보관.
- 독립 공급자 어댑터: https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
- 거래소 캘린더: https://github.com/gerrymanoim/exchange_calendars

원하는 때에만 `capture` 명령으로 새 사이트 기준 응답을 저장할 수 있습니다. 유료 전환 이후에도
이미 저장한 기준값과 독립 분석 프로그램은 사용할 수 있습니다. 새 기준값 접근권한은 별개입니다.

## QQQ 가격 갱신 시점 혼합 연구 (2026-10-05)

Yahoo 공급자 역사표에서 확인한 일반 종가·배당(출처와 표시 정밀도: `evidence/actions/QQQ_vintage.json`)으로 조정 prefix와 명시적 raw tail 가정을 통일했다. 원본 차트와 기준값은 보존했다. 세 가격의 조정 기준 혼합을 해소하면 지정 평균 정밀 일치가 31→33/36이 된다. 960개 전역 설정에서 최적 구간 전체는 13/36, GLD 0/12, 별도 5년 전체는 5→6/24이다. 5년 지정 평균은 20→22/24. 가격 표본 수집 범위가 제한되어 전 기간 독립 검증은 아니다. 생산용 계산과 투자 모드는 변경하지 않았다.

```bash
python3 research_dividends.py --raw-cache ../market_detector/data/cache/prices --raw-field close --append-raw-tail --normalize-vintage --out results/research/vintage
```

## 수익률·손실 점수 가설 추가 비교 (2026-10-05)

`research_scores.py`는 승률 가중 평균, 평균·승률 가중합, 손실 편차, 손익 비율, 기하 평균, 최악 수익률을 날짜·탐색 격자·표본 정책과 함께 864개 전역 설정으로 비교했다. 학습에서만 선택한 최고 가설(평균 수익률 × 승률^10)은 전체14/36. GLD0/12, 별도5년6/24는 가격 기준 수정 후 기본 선택 규칙과 동일하여 독립 개선 증거가 없다. `results/research/scores.json`에 모든 시행과 불일치를 저장했고 생산 규칙으로 채택하지 않았다. 테스트46개 통과. 연말 전용 청산 인덱스 -5..+5 이동은 다섯 평균 불일치 중 하나도 해소하지 못했다(`year_boundary_checks.json`). GLD 2026-01-29 종가495.90은 독립 Yahoo 자료와 일치한다. 다음에는 날짜 후보를 만드는 방식과 연도 경계 계산을 분리해 조사한다.

## 거래일 후보 격자 조사 (2026-10-05)

`research_trading_grid.py`에서 상장 이후 세션 번호·연초·월초의 거래일 간격5/7, 현재/직전/분석 시작 연도 요일, 진입일 표시 변환을 2,322개 전역 가설로 비교했다. 원래 이력 시작일은 가격 복원으로 잘린 분석 prefix와 구분했다. 최선13/36, GLD0/12,5년6/24로 개선 없음. 테스트48개 통과. 결과 `results/research/trading_grid.json`. GLD의12개 기준 중11개는 현재 가격·일별 후보에서는 승률과 평균이 동시에 같거나 더 높은 후보가 존재한다(`GLD_dominance.json`). 이는 공개되지 않은 후보 제약·가격 시점·목적 함수가 필요할 가능성을 보여주며 사이트 오류를 증명하지 않는다. 다음 반복은 임의 점수 탐색보다 실제 사이트 설명/계산 시점/후보 제약을 확보하는 쪽에 집중한다.
