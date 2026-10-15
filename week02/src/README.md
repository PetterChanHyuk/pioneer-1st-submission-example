# 2주차 소스

| 파일 | 내용 |
| --- | --- |
| [strategy.json](strategy.json) | 앱에 저장한 전략 설정 그대로 (`version`·`draft`) |
| [summarize_journal.py](summarize_journal.py) | 실행 기록·백테스트 결과를 Markdown 요약으로 바꾸는 스크립트 (Python 표준 라이브러리만 사용) |

전략 판정·종이 체결·백테스트는 [NH FUTURES API](https://github.com/NHFutures-OpenAPI/nh-futures-open-api) 앱의 전략주문 탭이 수행합니다.
이 폴더에는 그 앱에 넣은 설정과, 앱이 남긴 기록을 보고서용 표로 바꾸는 스크립트만 둡니다.

## 요약 스크립트 사용법

`week02/` 폴더에서 실행합니다. Python 3.10 이상이면 추가 설치가 필요 없습니다.

```bash
# 1) 실행 기록 요약 — 실행 id 를 여러 번 주면 함께 요약합니다
python src/summarize_journal.py --journal "%USERPROFILE%/NHFutures/state/strategy-trades.jsonl" --run run-pioneer-w2-day-20261015 --out results/주간실행_요약.md

# 2) 백테스트 요약 — 앱에서 받은 백테스트 답 JSON
python src/summarize_journal.py --backtest results/backtest_all_20261015_135033.json --out results/백테스트_요약.md

# 3) 장 마감 뒤 확정본 — 맨 위 상태 문구를 바꿉니다
python src/summarize_journal.py --journal "%USERPROFILE%/NHFutures/state/strategy-trades.jsonl" --run run-pioneer-w2-day-20261015 --status "확정 — 국내 주간 세션 마감 뒤 기록" --out results/주간실행_요약.md
```

- 실행 기록 파일은 **읽기만** 합니다. 다른 실행의 줄이 섞여 있어도 `--run` 으로 거릅니다.
- 손익은 기록에 적힌 `grossPl`·`fee`·`netPl`(백테스트는 `pl`)을 그대로 쓰고 더하기만 합니다.
- 시각은 모두 한국 시간(KST)으로 바꿔 적습니다.

## 앱에서 이 전략을 재현하는 방법

### 방법 1. 전략 설정 탭에서 같은 조건을 넣기

전략주문 탭에서 새 전략을 만들고 아래 값을 넣은 뒤 저장합니다.

| 항목 | 값 |
| --- | --- |
| 전략 이름 | Pioneer_2주차_코스피200_EMA교차 |
| 시장 / 종목 | 국내 / 코스피200 선물 2026년 12월물 (A016C000) |
| 기준 봉 / 판정 | 1분봉 / 마감 |
| 매수 진입 | EMA(5) 가 EMA(20) 을 상향 교차 |
| 매도 진입 | EMA(5) 가 EMA(20) 을 하향 교차 |
| 매수 청산 | EMA(5) 가 EMA(20) 을 하향 교차 |
| 매도 청산 | EMA(5) 가 EMA(20) 을 상향 교차 |
| 손절 / 익절 | 8틱 / 16틱 |
| 세션 끝 정리 | 켬, 끝 10분 전 |
| 주문 | 시장가, FAS, 1계약 |
| 최대 보유 | 1계약 (보유 중 추가 진입 안 함) |
| 일일 손실 한도 | 500,000원 |
| 증거금 예산 | 100,000,000원 |

그다음 「백테스트」에서 받은 만큼의 지난 봉으로 돌려 보고, 「전략 검증」에서 **앱 시뮬레이션**으로 실행을 세웁니다.
앱 시뮬레이션은 실전 시세로 판정하지만 계좌에 주문을 내지 않습니다.

### 방법 2. `strategy.json` 을 저장 API 로 넣기

앱이 켜져 있을 때, 앱의 로컬 주소에 `strategy.json` 을 그대로 보냅니다.
주소의 포트는 앱 창의 주소에서 확인합니다(아래 `8000` 은 예시).

```bash
curl -X PUT "http://127.0.0.1:8000/api/strategy/versions/pioneer-w2-k200-ema-20261015" \
  -H "Content-Type: application/json" \
  --data-binary @src/strategy.json
```

저장되면 전략 목록에 같은 이름으로 나타납니다. `strategy.json` 은 특정 월물 코드 대신 품목(코스피200 선물)만 들고 있고,
종목코드는 앱이 그때의 종목 마스터에서 찾습니다. 이 보고서의 실행은 2026년 12월물(`A016C000`)로 돌았습니다.
월물이 바뀐 뒤에 재현하면 다른 월물로 돌게 되므로, 결과는 이 보고서의 수치와 달라집니다.
