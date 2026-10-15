"""전략 실행 기록과 백테스트 결과를 Markdown 요약으로 바꿉니다.

표준 라이브러리만 씁니다. 두 가지 입력을 받습니다.

1. 앱의 실행 기록 파일 (``strategy-trades.jsonl``)
   한 줄이 한 사건(JSON)입니다. 여러 실행의 줄이 섞여 있으므로 ``runId`` 로 거릅니다.
   줄 갈래(``kind``)는 다음과 같습니다.

   - ``fill``  체결 한 건 (앱 시뮬레이션이면 종이 체결)
   - ``order`` 끝난 주문 한 건의 결과
   - ``trade`` 진입부터 청산까지 닫힌 거래 한 건 (``grossPl``·``fee``·``netPl``)
   - ``day``   거래일을 넘길 때의 잔고
   - ``event`` 그 밖의 사건 (신호·상태·준비 봉·공백·세션 등)

2. 앱의 백테스트 답 JSON (``--backtest``)
   ``trades``·``pl``·``wins``·``losses``·``maxDrawdown``·``assumptions`` 를 그대로 옮깁니다.

손익은 파일에 적힌 값(``netPl``·``grossPl``·``fee``, 백테스트는 ``pl``)만 씁니다.
여기서 손익을 다시 셈하지 않습니다. 합계·최대 낙폭은 그 값들을 더해서 냅니다.

실행 예::

    python src/summarize_journal.py --journal %USERPROFILE%/NHFutures/state/strategy-trades.jsonl \\
        --run run-pioneer-w2-day-20261015 --out results/주간실행_요약.md
    python src/summarize_journal.py --backtest results/backtest_all_20261015_135033.json \\
        --out results/백테스트_요약.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

KST = timezone(timedelta(hours=9))

#: 기록 갈래 → 보고서에 쓰는 이름. 앱 시뮬레이션의 체결은 계좌 체결이 아닙니다.
RECORD_LABELS = {
    "paper": "앱 시뮬레이션 (종이 체결 — 계좌 주문 없음)",
    "sim": "모의 계좌 거래",
    "real": "실전 계좌 거래",
}

SIDE_LABELS = {"buy": "매수", "sell": "매도"}
INTENT_LABELS = {"entry": "진입", "exit": "청산"}
REASON_LABELS = {
    "signal": "규칙 신호",
    "stop": "손절",
    "take": "익절",
    "trail": "추적 청산",
    "session": "세션 끝 정리",
    "sessionEnd": "세션 끝 정리",
    "manual": "수동",
    "rule": "청산 규칙",
    "exit": "청산 규칙",
}

#: 실행이 끝났음을 알리는 이벤트 글. 있으면 요약에 시각을 적습니다.
END_TEXTS = ("실행을 끝냈습니다", "세션이 끝났습니다")


# ---------------------------------------------------------------- 공통 도우미


def kst(ms: Any, with_date: bool = True) -> str:
    """밀리초 epoch → KST 문자열. 값이 없거나 0 이면 빈 칸."""
    if not ms:
        return ""
    moment = datetime.fromtimestamp(float(ms) / 1000, KST)
    return moment.strftime("%Y-%m-%d %H:%M:%S" if with_date else "%H:%M:%S")


def won(value: Any) -> str:
    """원 단위 반올림 + 천 단위 쉼표. 값이 없으면 빈 칸."""
    if value is None:
        return ""
    return f"{round(float(value)):,}"


def price(value: Any) -> str:
    """가격 표시. 부동소수 꼬리(1021.9499999…)를 소수 둘째 자리로 정리합니다."""
    if value is None:
        return ""
    return f"{float(value):.2f}"


def duration(ms: float) -> str:
    """밀리초 → 「N분 M초」."""
    seconds = int(round(ms / 1000))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}시간 {minutes}분 {secs}초"
    if minutes:
        return f"{minutes}분 {secs}초"
    return f"{secs}초"


def label(table: dict[str, str], key: Any) -> str:
    if key in (None, ""):
        return ""
    return table.get(str(key), str(key))


def cell(value: Any) -> str:
    """표 칸 안에서 줄바꿈·세로줄이 표를 깨지 않게 합니다."""
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def md_table(headers: list[str], rows: Iterable[list[Any]]) -> list[str]:
    rows = list(rows)
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(cell(v) for v in row) + " |")
    if not rows:
        lines.append("| " + " | ".join(["(없음)"] + [""] * (len(headers) - 1)) + " |")
    return lines


def pl_of(trade: dict[str, Any]) -> float:
    """거래 한 건의 순손익. 실행 기록은 ``netPl``, 백테스트는 ``pl`` 칸입니다."""
    for key in ("netPl", "pl"):
        if trade.get(key) is not None:
            return float(trade[key])
    return 0.0


def hold_ms(t: dict[str, Any], by_bar: bool) -> float | None:
    """보유시간(밀리초). 백테스트는 봉 시각이라 분 단위로 내림해 셉니다."""
    if not (t.get("closedAt") and t.get("openedAt")):
        return None
    if by_bar:
        return (int(t["closedAt"]) // 60000 - int(t["openedAt"]) // 60000) * 60000.0
    return float(t["closedAt"]) - float(t["openedAt"])


def trade_stats(trades: list[dict[str, Any]], by_bar: bool = False) -> dict[str, Any]:
    """닫힌 거래 목록의 요약. 손익은 파일 값을 더하기만 합니다.

    최대 낙폭은 닫힌 거래 순서대로 순손익을 누적한 곡선(0에서 출발)의
    고점 대비 가장 깊은 하락입니다 — 실현 기준이라 보유 중 평가손익은 들지 않습니다.
    """
    ordered = sorted(trades, key=lambda t: (t.get("closedAt") or 0, t.get("openedAt") or 0))
    pls = [pl_of(t) for t in ordered]
    wins = sum(1 for v in pls if v > 0)
    losses = sum(1 for v in pls if v < 0)
    curve, peak, drawdown = 0.0, 0.0, 0.0
    for v in pls:
        curve += v
        peak = max(peak, curve)
        drawdown = max(drawdown, peak - curve)
    holds = [h for h in (hold_ms(t, by_bar) for t in ordered) if h is not None]
    win_pls = [v for v in pls if v > 0]
    loss_pls = [v for v in pls if v < 0]
    return {
        "count": len(ordered),
        "wins": wins,
        "losses": losses,
        "flat": len(ordered) - wins - losses,
        "net": sum(pls),
        "gross": sum(float(t.get("grossPl") or 0) for t in ordered),
        "fee": sum(float(t.get("fee") or 0) for t in ordered),
        "maxDrawdown": drawdown,
        "avgHold": (sum(holds) / len(holds)) if holds else None,
        "avgWin": (sum(win_pls) / len(win_pls)) if win_pls else None,
        "avgLoss": (sum(loss_pls) / len(loss_pls)) if loss_pls else None,
        "reasons": Counter(str(t.get("reason") or "") for t in ordered if t.get("reason")),
        "ordered": ordered,
        "byBar": by_bar,
    }


def trade_rows(ordered: list[dict[str, Any]], *, with_run: bool, by_bar: bool = False) -> list[list[Any]]:
    rows = []
    for i, t in enumerate(ordered, 1):
        held = hold_ms(t, by_bar)
        hold = "" if held is None else ("같은 봉" if by_bar and held == 0 else duration(held))
        row = [
            i,
            kst(t.get("openedAt")),
            kst(t.get("closedAt")),
            label(SIDE_LABELS, t.get("side")),
            t.get("quantity", ""),
            price(t.get("avgEntry", t.get("entryPrice"))),
            price(t.get("avgExit", t.get("exitPrice"))),
        ]
        row.append(label(REASON_LABELS, t.get("reason")))
        row += [won(t.get("grossPl")), won(t.get("fee")), won(pl_of(t)), hold]
        if with_run:
            row.append(t.get("runId", ""))
        rows.append(row)
    return rows


def summary_lines(stats: dict[str, Any]) -> list[str]:
    decided = stats["wins"] + stats["losses"]
    rate = f"{stats['wins'] / decided * 100:.1f}%" if decided else "-"
    lines = md_table(
        ["항목", "값"],
        [
            ["닫힌 거래 수", stats["count"]],
            ["승 / 패 / 본전", f"{stats['wins']} / {stats['losses']} / {stats['flat']}"],
            ["승률 (본전 제외)", rate],
            ["총손익 합 (원)", won(stats["gross"])],
            ["수수료 합 (원)", won(stats["fee"])],
            ["순손익 합 (원)", won(stats["net"])],
            ["최대 낙폭 (원, 실현 누적 기준)", won(stats["maxDrawdown"])],
            ["평균 이익 거래 (원)", won(stats["avgWin"])],
            ["평균 손실 거래 (원)", won(stats["avgLoss"])],
            [
                "평균 보유시간" + (" (봉 시각 기준, 분 단위)" if stats.get("byBar") else ""),
                "-"
                if stats["avgHold"] is None
                else (f"{stats['avgHold'] / 60000:.2f}분" if stats.get("byBar") else duration(stats["avgHold"])),
            ],
            [
                "청산 까닭별 건수",
                ", ".join(f"{label(REASON_LABELS, k)} {v}" for k, v in stats["reasons"].most_common())
                or "-",
            ],
        ],
    )
    return lines


# ---------------------------------------------------------------- 실행 기록


def read_journal(path: Path, run_ids: set[str]) -> list[dict[str, Any]]:
    """기록 파일에서 그 실행의 줄만 읽습니다. 앞 파일(``.jsonl.old``)이 있으면 먼저 읽습니다.

    파일은 읽기만 합니다. 깨진 줄은 건너뛰고 개수를 셉니다.
    """
    rows: list[dict[str, Any]] = []
    broken = 0
    sources = [path.with_suffix(".jsonl.old"), path]
    for source in sources:
        if not source.exists():
            continue
        with source.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    broken += 1
                    continue
                if row.get("runId") in run_ids:
                    rows.append(row)
    if broken:
        print(f"[알림] 읽지 못한 줄 {broken}개를 건너뛰었습니다", file=sys.stderr)
    return rows


def row_time(row: dict[str, Any]) -> float:
    return float(row.get("time") or row.get("at") or row.get("closedAt") or row.get("endedAt") or 0)


def journal_markdown(rows: list[dict[str, Any]], run_ids: list[str], journal: Path, status: str | None) -> str:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        kind = row.get("kind")
        key = kind if kind in ("fill", "trade", "order", "day") else "event"
        by_kind.setdefault(key, []).append(row)
    fills = sorted(by_kind.get("fill", []), key=row_time)
    orders = sorted(by_kind.get("order", []), key=lambda r: r.get("placedAt") or 0)
    # 거래 줄에는 청산 까닭이 없어, 청산 시각과 같은 시각의 청산 체결에서 가져옵니다.
    exit_reason = {
        (f.get("runId"), f.get("time")): f.get("reason")
        for f in by_kind.get("fill", [])
        if f.get("intent") == "exit"
    }
    trades = [
        {**t, "reason": t.get("reason") or exit_reason.get((t.get("runId"), t.get("closedAt")))}
        for t in by_kind.get("trade", [])
    ]
    days = sorted(by_kind.get("day", []), key=row_time)
    events = sorted(by_kind.get("event", []), key=row_time)
    many = len(run_ids) > 1

    times = [row_time(r) for r in rows if row_time(r)]
    ended = [e for e in events if any(text in str(e.get("text", "")) for text in END_TEXTS)]
    records = sorted({str(r.get("record") or "paper") for r in rows})
    models = sorted({str(r.get("model")) for r in rows if r.get("model")})
    first = rows[0] if rows else {}

    if status is None:
        status = "진행 중 — 아래 수치는 기록 마지막 줄 시각까지의 값이며 확정 전입니다"

    out: list[str] = []
    out.append(f"# 실행 기록 요약 — {', '.join(run_ids)}")
    out.append("")
    out.append(f"> 상태: **{status}**")
    out.append("")
    out.append("이 문서는 `src/summarize_journal.py` 가 앱의 실행 기록 파일에서 만든 것입니다.")
    out.append("손익은 기록에 적힌 `grossPl`·`fee`·`netPl` 을 그대로 옮기고 더하기만 했습니다.")
    out.append("표의 금액은 원 단위로 반올림해 표시하며, 합계는 반올림 전 값을 더한 뒤 반올림합니다.")
    out.append("")
    out.append("## 실행 정보")
    out.append("")
    out += md_table(
        ["항목", "값"],
        [
            ["실행 id", ", ".join(run_ids)],
            ["전략 버전 id", first.get("versionId", "")],
            ["시장 / 종목코드 / 세션", f"{first.get('market', '')} / {first.get('code', '')} / {first.get('session', '')}"],
            ["기록 갈래", ", ".join(RECORD_LABELS.get(r, r) for r in records) or "-"],
            ["체결 모형", ", ".join(models) or "-"],
            ["통화", first.get("currency", "")],
            ["기록 첫 줄 시각 (KST)", kst(min(times)) if times else "-"],
            ["기록 마지막 줄 시각 (KST)", kst(max(times)) if times else "-"],
            ["종료 기록", ", ".join(f"{kst(row_time(e))} {e.get('text')}" for e in ended) or "아직 없음"],
            ["원본 파일", journal.name],
            ["요약을 만든 시각 (KST)", datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")],
        ],
    )
    if "paper" in records:
        out.append("")
        out.append("체결은 모두 **종이 체결**입니다. 앱이 실시간 시세로 「그때 냈으면 어떻게 채워졌을까」를")
        out.append("모형으로 계산한 값이며, 계좌에 주문을 내지 않았고 모의계좌 체결도 아닙니다.")

    stats = trade_stats(trades)
    out.append("")
    out.append("## 요약")
    out.append("")
    out += summary_lines(stats)

    out.append("")
    out.append("## 거래 (진입 ~ 청산)")
    out.append("")
    headers = ["#", "진입 시각", "청산 시각", "방향", "수량", "진입가", "청산가", "청산 까닭", "총손익", "수수료", "순손익", "보유시간"]
    if many:
        headers.append("실행")
    out += md_table(headers, trade_rows(stats["ordered"], with_run=many))

    out.append("")
    out.append("## 체결")
    out.append("")
    fill_headers = ["시각", "방향", "수량", "가격", "진입/청산", "까닭", "신호 봉 종가 (진입만)", "주문 id"]
    if many:
        fill_headers.append("실행")
    fill_rows = []
    for f in fills:
        snap = (f.get("snapshot") or {}).get("values") or {}
        row = [
            kst(f.get("time")),
            label(SIDE_LABELS, f.get("side")),
            f.get("quantity", ""),
            price(f.get("price")),
            label(INTENT_LABELS, f.get("intent")),
            label(REASON_LABELS, f.get("reason")),
            price(snap.get("close")) if f.get("intent") == "entry" and snap.get("close") is not None else "",
            f.get("orderId", ""),
        ]
        if many:
            row.append(f.get("runId", ""))
        fill_rows.append(row)
    out += md_table(fill_headers, fill_rows)

    out.append("")
    out.append("## 주문 결과")
    out.append("")
    order_rows = []
    for o in orders:
        order_rows.append(
            [
                kst(o.get("placedAt")),
                kst(o.get("endedAt")),
                label(SIDE_LABELS, o.get("side")),
                label(INTENT_LABELS, o.get("intent")),
                label(REASON_LABELS, o.get("reason")),
                o.get("orderType", ""),
                o.get("quantity", ""),
                o.get("filled", ""),
                o.get("outcome", ""),
                o.get("why") or o.get("serverMessage") or "",
            ]
        )
    out += md_table(
        ["낸 시각", "끝난 시각", "방향", "진입/청산", "까닭", "유형", "수량", "채운 수량", "결과", "사유"],
        order_rows,
    )

    if days:
        out.append("")
        out.append("## 거래일 잔고")
        out.append("")
        out += md_table(
            ["거래일", "기록 시각", "실현", "수수료", "평가", "합계", "보유", "종가"],
            [
                [
                    d.get("day", ""),
                    kst(d.get("time")),
                    won(d.get("realized")),
                    won(d.get("fee")),
                    won(d.get("unrealized")),
                    won(d.get("equity")),
                    d.get("position", ""),
                    price(d.get("closePrice")),
                ]
                for d in days
            ],
        )

    out.append("")
    out.append("## 이벤트")
    out.append("")
    event_headers = ["시각", "갈래", "글"]
    if many:
        event_headers.append("실행")
    event_rows = []
    for e in events:
        row = [kst(row_time(e)), e.get("event") or e.get("kind", ""), e.get("text", "")]
        if many:
            row.append(e.get("runId", ""))
        event_rows.append(row)
    out += md_table(event_headers, event_rows)
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- 백테스트


ASSUMPTION_LABELS = {
    "delay": "체결 지연(초)",
    "slippageTicks": "슬리피지(틱, 불리한 쪽)",
    "limitFill": "지정가 체결 조건",
    "sameBarStopFirst": "한 봉에 손절·익절이 함께 닿으면 손절",
    "path": "봉 안의 가격 경로",
    "sessionEnd": "세션 끝 처리",
    "sessionEndFlat": "세션 끝 정리",
    "dailyOrders": "일봉 신호 주문 시점",
    "dailyPriceBasis": "일봉 신호 가격 기준",
    "expiryBlock": "신규 진입 막는 만기일",
    "feePerContract": "계약당 수수료",
    "evalBasis": "판정 기준",
    "unjudged": "판정하지 못한 조건",
    "dailyEntryWindow": "일봉 진입 시간",
    "budgetUnchecked": "증거금 예산 검사 건너뜀",
    "budgetUncheckedWhy": "건너뛴 까닭",
}


def backtest_markdown(data: dict[str, Any], source: Path) -> str:
    trades = list(data.get("trades") or [])
    stats = trade_stats(trades, by_bar=True)
    bars = data.get("bars") or {}

    out: list[str] = []
    out.append("# 백테스트 요약")
    out.append("")
    out.append("이 문서는 `src/summarize_journal.py --backtest` 가 앱의 백테스트 답 JSON 에서 만든 것입니다.")
    out.append("백테스트는 지난 1분봉에 규칙을 대 본 계산이며 주문을 내지 않습니다.")
    out.append("손익은 JSON 의 `pl`·`grossPl`·`fee` 를 그대로 옮겼고, 표의 금액은 원 단위로 반올림해 표시합니다.")
    out.append("")
    out.append("## 앱이 낸 요약 (JSON 값 그대로)")
    out.append("")
    win_rate = data.get("winRate")
    out += md_table(
        ["항목", "값"],
        [
            ["체결 모형", data.get("model", "")],
            ["봉 범위 (KST)", f"{kst(bars.get('from'))} ~ {kst(bars.get('to'))}"],
            ["판정에 쓴 봉 / 받은 봉 / 지표 준비에 필요한 봉", f"{bars.get('count', '')} / {bars.get('have', '')} / {bars.get('need', '')}"],
            ["세션 수", bars.get("sessions", "")],
            ["봉이 충분했는가", "예" if data.get("enough") else "아니오"],
            ["신호 수", data.get("signals", "")],
            ["체결 수", data.get("fills", "")],
            ["거래 수", len(trades)],
            ["승 / 패", f"{data.get('wins', '')} / {data.get('losses', '')}"],
            ["승률", f"{win_rate * 100:.1f}%" if isinstance(win_rate, (int, float)) else ""],
            ["순손익 (원)", won(data.get("pl"))],
            ["수수료 (원)", won(data.get("fee"))],
            ["최대 낙폭 (원)", won(data.get("maxDrawdown"))],
            ["끝에 남은 보유", "없음" if not data.get("openPosition") else json.dumps(data["openPosition"], ensure_ascii=False)],
            ["통화", data.get("currency", "")],
        ],
    )

    out.append("")
    out.append("## 거래 목록에서 다시 센 값")
    out.append("")
    out.append("아래 표는 `trades` 목록만으로 다시 셈한 값입니다. 위의 앱 요약과 맞는지 대조하는 용도입니다.")
    out.append("백테스트의 진입·청산 시각은 봉 시각(분 단위)이라 보유시간도 분 단위로 셉니다. 같은 봉에서 닫힌 거래는 0분입니다.")
    out.append("")
    out += summary_lines(stats)

    same_bar = sum(1 for t in trades if t.get("openedAt") and t.get("closedAt") and int(t["closedAt"]) // 60000 == int(t["openedAt"]) // 60000)
    out.append("")
    out.append(f"진입한 봉 안에서 바로 청산된 거래: **{same_bar} / {len(trades)}건**")

    per_day: dict[str, list[dict[str, Any]]] = {}
    for t in stats["ordered"]:
        per_day.setdefault(kst(t.get("closedAt"))[:10], []).append(t)
    out.append("")
    out.append("## 거래일별")
    out.append("")
    day_rows = []
    for day, items in per_day.items():
        s = trade_stats(items, by_bar=True)
        day_rows.append([day, s["count"], s["wins"], s["losses"], won(s["net"])])
    out += md_table(["거래일 (청산 기준)", "거래", "승", "패", "순손익 (원)"], day_rows)

    out.append("")
    out.append("## 가정 (`assumptions`)")
    out.append("")
    assumption_rows = []
    for key, value in (data.get("assumptions") or {}).items():
        shown = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict, bool)) or value is None else value
        assumption_rows.append([ASSUMPTION_LABELS.get(key, key), f"`{key}`", shown])
    out += md_table(["뜻", "키", "값"], assumption_rows)

    out.append("")
    out.append("## 거래 목록")
    out.append("")
    out += md_table(
        ["#", "진입 봉", "청산 봉", "방향", "수량", "진입가", "청산가", "청산 까닭", "총손익", "수수료", "순손익", "보유시간"],
        trade_rows(stats["ordered"], with_run=False, by_bar=True),
    )
    out.append("")
    out.append(f"원본: `{source.name}` · 요약을 만든 시각(KST): {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- 진입점


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="전략 실행 기록·백테스트 결과를 Markdown 요약으로 만듭니다.")
    parser.add_argument("--journal", type=Path, help="실행 기록 파일 (strategy-trades.jsonl) 경로")
    parser.add_argument("--run", action="append", default=[], help="요약할 실행 id. 여러 번 줄 수 있습니다")
    parser.add_argument("--backtest", type=Path, help="백테스트 답 JSON 경로")
    parser.add_argument("--out", type=Path, required=True, help="출력 Markdown 경로")
    parser.add_argument("--status", help="요약 맨 위 상태 문구 (기본: 진행 중 표시)")
    args = parser.parse_args(argv)

    if args.backtest:
        data = json.loads(args.backtest.read_text(encoding="utf-8"))
        text = backtest_markdown(data, args.backtest)
    elif args.journal and args.run:
        rows = read_journal(args.journal, set(args.run))
        text = journal_markdown(rows, args.run, args.journal, args.status)
        print(f"{len(rows)}줄을 읽었습니다 ({', '.join(args.run)})")
    else:
        parser.error("--journal 과 --run, 또는 --backtest 중 하나가 필요합니다")
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"썼습니다: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
