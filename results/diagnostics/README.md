# 2026-10-05 환경 진단과 오프라인 재검증

| 검사 | 결과 | 근거 |
|---|---|---|
| 일반 macOS 터미널 | 사용자가 DNS 성공·curl HTTP/2 429를 보고함. 정확한 경로·헤더는 미제공 | [환경 비교](network_environment.json) |
| Codex Python resolver | `socket.getaddrinfo`가 `gaierror(8)`로 실패 | [환경 비교](network_environment.json) |
| Codex dig | 소켓 `bind: Operation not permitted`, 종료 코드 10. DNS 응답 전 실패 | [환경 비교](network_environment.json) |
| 실제 기본 가격 API 단일 GET | DNS 오류 8. HTTP 응답을 받지 못해 429와 Retry-After 확인 불가 | [요청 주소·헤더·결과](price_api_probe.json) |
| CUA 브라우저 초기화 | `CUA_REPL_ENABLED_SURFACES is required`. 상세 예외 스택은 찾지 못함 | [도구 응답·과거 연결 로그](browser_initialization.json) |
| 전체 테스트 | 92개 통과. 수집 테스트는 모두 모의 응답 | [실행 로그](unittest.log) |
| 저장된 가격의 지정 구간 재계산 | 학습 36/36·GLD 12/12·5년 24/24, 전체 필드 72/72 | [재계산·원본 13개 해시 확인](offline_recheck.json) |

기본 가격 주소는 `https://query1.finance.yahoo.com/v8/finance/chart/SPY`이다.
조회 범위는 뉴욕 자정 기준 2026-09-28부터 2026-10-03 제외이며 정확한 epoch 쿼리는 요청 결과에 있다.
가격 API에 실제 GET 한 번만 요청했고 리디렉션·자동 재시도·후속 실제 Yahoo 요청을 하지 않았다.
이 검사는 기본 `--provider yahoo` 어댑터의 공유 URL·요청 빌더를 사용한다.
선택 어댑터인 yfinance 내부 요청을 검사한 결과는 아니다.

일반 터미널과 Codex 결과의 차이를 Yahoo 전체 DNS 장애로 해석하지 않는다.
dig 결과는 환경의 소켓 바인딩 제한을 보여주며, Python resolver 실패의 정확한 원인은 미확정이다.
브라우저의 필수 설정 오류는 이 가격 요청의 DNS 결과와 별개다.
발췌된 MCP ready·연결 성공 로그는 과거 다른 스레드의 기록이므로 현재 브라우저 준비 완료를 증명하지 않는다.

다운로드는 429에서 다음 종목 요청을 중단하고 기존 CSV를 보존한다.
Retry-After의 초/HTTP 날짜를 해석해 출력 폴더에 대기 기한을 저장하며 기한 전 실행은 API를 호출하지 않는다.
헤더가 없거나 유효하지 않으면 자동 재시도 시각을 추측하지 않는다.
형식 근거: [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after).
모의 429 테스트의 로그는 실제 Yahoo에서 429를 수신했다는 증거가 아니다.

선택 시점·가격 기준과 현재 보고 통계를 분리한 1,280개 전역 가설도 오프라인으로 비교했다.
학습에서 고른 한 설정의 최적 구간 전체 일치는 6/36·GLD 1/12·5년 1/24로 기존 방식보다 낮아 기각했다.
근거: [전체 시행과 불일치](../research/selection_vintage.json).
현재 가격·윤년 실험의 독립 최적 선택은 13/36·GLD 0/12·5년 6/24다.
원래 생산 비교는 9/36이며 최적화 규칙과 투자 모드는 변경하지 않았다.
지정 구간 72/72는 기준 진입일·보유기간을 입력한 계산 검증으로, 독립 최적 선택 재현 완료를 뜻하지 않는다.

## 기존 자료의 입력·선택 단계 검증

| 검사 | 결과 | 근거 |
|---|---|---|
| 72건 선택 단계 | 전체 일치 19·같은 거래 후보 없음 31·후보 존재/선택 차이 22. 지정 계산·동률·표시 차이 분류는 0 | [비교표](selection_diagnosis.html), [상세](selection_diagnosis.json) |
| 독립 단순 계산 | 13,140개 구간 불일치 0, 최대 수치 차이 약 1.39×10⁻¹⁷. 선택 72건·캐시 전후 72건 동일 | [상세](selection_diagnosis.json) |
| 보고 캐시 오류 수정 | 가격 객체·기준일을 키에 추가. 회귀 테스트 수정 전 실패·수정 후 통과. 1,280개 기존 실험의 전체 JSON 수정 전후 동일 | [영향 재검사](cache_recheck.json), [수정 전 로그](cache_before_fix.log) |
| 기존 캐시 날짜 범위 | Parquet 7,255개·CSV 518개, 조사 실패 0. 이 두 경로에는 10년 이력 파일이 없음 | [품질 결과](existing_price_quality.json), [Parquet](parent_cache_date_ranges.csv), [CSV](parent_csv_date_ranges.csv) |
| 마지막 봉 품질 | 6종목 2026-05-15 Parquet/CSV 종가 충돌, SPY·KO Parquet OHLC 불일치. 공급자·수집 상태 미확인, 원본 보존 | [품질 결과](existing_price_quality.json) |
| 보유 중 위험 제약 | 66개 전역 설정, 최적 전체 13/36·GLD 0/12·5년 6/24로 개선 없음 | [위험 연구](../research/holding_risk.json) |
| 새 종목 계산 | MSFT·NVDA·KO·JPM Close/Adj Close 2·3년 계산 70,080개·선택 384건 독립 검산, 차이 0 | [검산 결과](new_ticker_math.json) |
| 기본 투자 표본 | 새 종목의 17,520개 구간 모두 10개 완료 표본 부족으로 반환되지 않음. 기본 규칙 유지 | [검산 결과](new_ticker_math.json) |
| 공개 계산 설명 | 공식 홈페이지·제작자 사용 설명서의 추출/검색 텍스트에서 후보 간격·점수 산식 미확인. 기존 SPY20년 예시만 확인, 새 검증 건수 아님 | [확인 범위](public_description_check.json), [제작자 설명](https://fanding.kr/en/@kangcfa/post/209655/) |

이 단계에서는 외부 가격 요청 없이 기존 파일을 직접 읽었다.
독립 검산은 선언한 날짜·가격 가설을 다른 코드로 계산한 결과다. 사이트 비공개 산식과 가격 출처를 증명하지 않는다.
새 종목에는 사이트 최적 구간 기준 응답이 없으므로 사이트 일치 검증 건수는 0이며 재현은 미완료다.
