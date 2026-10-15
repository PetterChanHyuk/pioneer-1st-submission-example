# 2주차 · 국내상품 전략 구현

**제출일: 2026/10/30(금)** · 마감 시각 미정

코스피200 선물 1분봉에서 EMA 교차 전략을 구현하고, 앱 시뮬레이션으로 실행한 기록을 근거로 보고서를 썼습니다.

> 이 실행은 **앱 시뮬레이션**입니다. 실전 시세로 판정하지만 계좌에 주문을 내지 않았고, 체결은 앱의 종이 체결 모형이 계산한 값입니다. 모의계좌 체결이 아닙니다.

## 과제 요약

국내 선물·옵션 상품 하나에 대한 규칙 기반 전략을 NH선물 Open API 로 구현하고, 실제로 실행한 기록으로 결과를 분석합니다.
수익률이 아니라 전략 실행·API 작동·결과 분석·오류와 개선을 봅니다. 자세한 내용은 [과제 안내](과제안내.md)에 있습니다.

## 전략

코스피200 선물 2026년 12월물(`A016C000`)의 1분봉 마감에서 EMA(5)가 EMA(20)을 상향 교차하면 매수, 하향 교차하면 매도로 진입합니다.
반대 교차·손절 8틱·익절 16틱으로 청산하고, 세션 끝 10분 전에 전량 정리합니다. 시장가 1계약, 최대 보유 1계약, 일일 손실 한도 500,000원입니다.
지난 봉 백테스트(4세션 1,470봉)에서는 거래 52건, 승률 23.1%, 순손익 −2,250,000원이었으며, 그 까닭을 [보고서](report.md) 6절에서 분석했습니다.

## 결과물

| 항목 | 위치 |
| --- | --- |
| 과제 안내 | [과제안내.md](과제안내.md) |
| 소스 | [src/](src/) — [전략 설정 strategy.json](src/strategy.json) · [기록 요약 스크립트](src/summarize_journal.py) |
| 실행 방법 | [src/README.md](src/README.md) · 보고서 [4절](report.md#4-실행환경과-실행-방법) |
| 보고서 | [report.md](report.md) |
| 실행 근거 | [results/](results/) — [백테스트 요약](results/백테스트_요약.md) · [주간 실행 요약](results/주간실행_요약.md) · 원본 JSON |
| 화면 캡처 | [screenshots/](screenshots/) · 목록은 보고서 [5-5절](report.md#5-5-화면-캡처) |
| 오류·한계·개선 | 보고서 [6절](report.md#6-결과-해석과-한계) · [7절](report.md#7-오류-및-개선사항) |

국내 주간 실행 결과는 장 마감 뒤 확정해 보고서 5-3절에 채웁니다. 그전의 [주간 실행 요약](results/주간실행_요약.md)은 진행 중 상태의 중간 기록입니다.

## 실행 방법

1. **앱 설치** — [NH FUTURES API](https://github.com/NHFutures-OpenAPI/nh-futures-open-api) 저장소의 설치 안내를 따라 설치하고, 국내 APP Key·Secret Key 를 앱 설정 화면에 입력합니다.
2. **전략 재현** — 전략주문 탭에서 [src/README.md](src/README.md) 의 조건으로 전략을 만들거나, [strategy.json](src/strategy.json) 을 저장 API(`PUT /api/strategy/versions/{id}`)로 넣습니다.
3. **실행** — 「백테스트」로 지난 봉을 돌려 보고, 「전략 검증」에서 앱 시뮬레이션 실행을 세웁니다.
4. **요약** — 장이 끝난 뒤 기록을 표로 만듭니다.

```bash
python src/summarize_journal.py --journal "%USERPROFILE%/NHFutures/state/strategy-trades.jsonl" --run run-pioneer-w2-day-20261015 --out results/주간실행_요약.md
python src/summarize_journal.py --backtest results/backtest_all_20261015_135033.json --out results/백테스트_요약.md
```

인증정보와 계좌 식별정보는 이 폴더 어디에도 담지 않았습니다.

[보고서 작성 틀](../templates/report-template.md) · [전체 일정으로](../README.md)
