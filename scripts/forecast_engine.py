#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""예측 엔진 — 운영 명세 5.1 '엔진과 페르소나의 분리'를 그대로 옮긴다.

  기준 확률 p  : 엔진이 낸다. 페르소나 성향이 확률을 만들지 않는다
  편향 δ       : (낙관 − 3) × 4%p. 범위 −8%p ~ +8%p
  발화 확률    : clamp(p + δ, 5%, 95%). 0.5 보다 크면 오른다, 작으면 내린다, 같으면 보류

엔진 규칙 (주간 흐름 엔진 v1, 2026-10-27 확정)
  입력은 한국부동산원 주간 아파트가격 동향의 구별 매매 변동률 하나뿐이다.
  그 주 발표 표의 마지막 4주에서 오른 주 수 u, 내린 주 수 d 를 세어
      p(오른다) = 0.5 + 0.1 × (u − d)          → 0.1 ~ 0.9
  명세가 적은 다른 입력(신고 건수·매물·호가 갭·전세가율)은 쓰지 않는다. 매물·호가는 수집하지 않고(13번),
  신고 건수는 그 주에 무엇이 신고돼 있었는지 되살릴 수 없다(신고일 필드가 없다).

  **이 규칙은 8~10월 결과가 나온 뒤에 정했다.** 그래서 그 기간 적중률은 실력이 아니라
  규칙이 그 기간에 맞았는지를 보여 줄 뿐이다. 규칙을 바꾸면 버전을 올리고 전 구간을 다시 계산한다.
  결과를 보고 몰래 고치지 않는다(명세 5.4).

판정
  다음 발표의 같은 구 변동률이 0보다 크면 오른다, 작으면 내린다, 0.00이면 보합(판정에서 뺀다).

투표 자격 (명세 2장 표가 원본. 명세와 CTO 프롬프트가 어긋나면 명세를 따른다)
  명세가 베팅을 막은 페르소나는 넣지 않는다. 낙관 점수는 명세에 적힌 것이나 대표님이 정한 것만 쓰고,
  둘 다 없으면 중립(3)으로 둔다 — 점수를 지어내지 않는다.

패널이 둘이다 (2026-11-03 대표님 "추천대로", docs/persona-roster-2026-11.md 7장)
  장부 패널 v1  LEDGER_VOTERS. 8/6부터의 AI 예측 장부·소급 기록 글·마켓 소급 표(7/27~10/26 주)·11/2 주 판까지 6명이 매주 냈다.
                **고정이다.** 바꾸면 이미 게시한 장부 이력이 다시 계산된다(명세 5.4). forecast() 기본값이 이 패널이다
  마켓 패널 v2  MARKET_VOTERS. 11/9 주 판부터 서버 마켓 표만 이 패널로 낸다(market_panel). 12명, 빈도는 명세 저/중/고빈도
                  매주   = 판마다
                  격주   = ISO 짝수 주 판 (2026년은 ISO 53주가 있어 12/28·1/4 두 판을 연달아 쉰다)
                  월 1회 = 그달 첫 판(월요일이 1~7일)
                빈도는 미리 정한 날짜 규칙이라 표를 낼지 말지를 결과를 보고 고를 수 없다
  낙관 점수는 동률(p = 0.5)일 때만 방향을 가른다(편향 최대 ±8%p < 엔진 한 칸 10%p).
  표가 실제로 갈리려면 역할별 입력(2단계)이 필요하고, 그건 장부로 미리 돌려 보고한 뒤 켠다
"""

from datetime import date

ENGINE = "주간 흐름 엔진 v1"
LOOKBACK = 4

# 장부 패널 v1 — 고정. (external_id, 화면 이름, 낙관, 낙관 출처)
LEDGER_VOTERS = [
    ("wb-persona-policy-lab", "정책데이터랩", 2, "명세 481줄(낙관 2)"),
    ("wb-persona-real-talk", "현실부동산톡", 2, "명세 481줄(낙관 2)"),
    ("wb-persona-demand-check", "수요밀도체크", 3, "명세에 점수 없음 → 중립"),
    ("wb-persona-num-compare", "숫자비교표", 3, "명세에 없는 페르소나 → 중립"),
    ("wb-persona-cashflow", "현금흐름생활자", 3, "명세에 없는 페르소나 → 중립"),
    ("wb-persona-field-scout", "현장입지파", 3, "명세에 점수 없음 → 중립"),
]
VOTERS = LEDGER_VOTERS   # forecast_ledger·build_forecast_backfill_pack 이 읽는 이름. 장부 이력 때문에 그대로 둔다

# 마켓 패널 v2 — 11/9 주 판부터. (external_id, 화면 이름, 낙관, 낙관 출처, 빈도)
MARKET_V2_FROM = "2026-11-09"
MARKET_VOTERS = [
    ("wb-persona-demand-check", "수요밀도체크", 4, "11/3 대표님 결정(명세 INF-021 '상방 신호 중심'). 장부 패널에서는 3", "weekly"),
    ("wb-persona-num-compare", "숫자비교표", 3, "명세에 없는 페르소나 → 중립", "weekly"),
    ("INF-012", "시장경고등", 1, "명세 225줄(낙관 1)", "weekly"),
    ("wb-persona-policy-lab", "정책데이터랩", 2, "명세 481줄(낙관 2)", "biweekly"),
    ("wb-persona-field-scout", "현장입지파", 3, "명세에 점수 없음 → 중립", "biweekly"),
    ("INF-007", "역발상복덕방", 2, "명세 481줄(낙관 2)", "biweekly"),
    ("INF-003", "가치입지연구소", 4, "11/3 대표님 결정(조사 문서 말투 근거)", "biweekly"),
    ("wb-persona-real-talk", "현실부동산톡", 2, "명세 481줄(낙관 2)", "monthly"),
    ("wb-persona-cashflow", "현금흐름생활자", 3, "명세에 없는 페르소나 → 중립", "monthly"),
    ("INF-001", "길게보는집", 3, "11/3 대표님 결정(중립)", "monthly"),
    ("INF-005", "월급모아한채", 4, "11/3 대표님 결정(조사 문서 말투 근거)", "monthly"),
    ("INF-020", "주거자산플랜", 3, "11/3 대표님 결정(중립)", "monthly"),
]
FREQ_KO = {"weekly": "매주", "biweekly": "격주", "monthly": "월 1회"}


def due(freq, week_start):
    d = date.fromisoformat(week_start)
    if freq == "weekly":
        return True
    if freq == "biweekly":
        return d.isocalendar()[1] % 2 == 0
    if freq == "monthly":
        return d.day <= 7
    raise ValueError(freq)


def market_panel(week_start):
    """그 주 판에 표를 낼 페르소나. 11/9 주 전에는 장부 패널 v1(6명 매주) 그대로다"""
    assert date.fromisoformat(week_start).weekday() == 0, week_start
    if week_start < MARKET_V2_FROM:
        return list(LEDGER_VOTERS)
    return [v[:4] for v in MARKET_VOTERS if due(v[4], week_start)]

# 투표하지 않는 페르소나와 이유. 생성기·투표 스크립트가 이 표로 막는다
NON_VOTERS = {
    "wb-persona-trade-brief": "명세 INF-013: 확정 베팅 없음, 조건부 확률 코멘트만",
    "wb-persona-psy-thermo": "명세 INF-002: 베팅 월 1회 이하, 마켓 쏠림 해설 전담",
    "wb-persona-question-post": "명세 CUR-001: 분석·전망·베팅 금지",
    "wb-persona-tax-oneline": "명세 INF-023: 베팅 없음",
    "wb-persona-tax-scenario": "명세 INF-024: 베팅 없음",
    "wb-persona-appraisal-check": "명세 INF-031 공시가격체크 계열: 판정 이해충돌, 본인 베팅 금지",
    "wb-persona-contrarian": "휴면(전망 소재라 깨우지 않는다)",
    "wb-persona-school-move": "휴면. 11/3 학교 지표 규칙 v2로 깨울 수 있게 됐다(CLAUDE.md 4장). 투표는 별도 결정",
    "INF-004": "보류(11/3) — 경매 자료 축이 생긴 뒤",
    "INF-009": "보류(11/3) — 엔진 값을 해설하는 역할이라 같은 값에 표를 더하면 중복",
    "INF-015": "보류(11/3) — 명세상 전국 피드 전용",
    "INF-010": "명세 INF-010: 베팅 없음(공급 변수 코멘트)",
    "INF-011": "명세 INF-011: 베팅 자제",
    "INF-022": "명세 INF-022: 베팅 없음",
    "INF-025": "명세 INF-025: 베팅 없음",
    "INF-026": "명세 INF-026: 베팅 없음",
}
# 11/3 신규 중 명세에 없는 16명 — 마켓 패널은 작게 둔다(늘려도 엔진 값은 같다). 투입 6명은 MARKET_VOTERS
for _pid in ("wb-persona-supply-count", "wb-persona-host",
             "wb-persona-myth-check", "wb-persona-policy-twosides", "wb-persona-dry-note", "wb-persona-whatif",
             "wb-persona-senior-advice", "wb-persona-retire", "wb-persona-past-cycle", "wb-persona-paradox",
             "wb-persona-abroad", "wb-persona-timeseries", "wb-persona-live-chat", "wb-persona-sure-thing",
             "wb-persona-cheer", "wb-persona-ding-dong"):
    NON_VOTERS.setdefault(_pid, "11/3 신규, 명세에 없는 계정 — 마켓 패널에 넣지 않는다(11/3 대표님 \"추천대로\")")
NON_VOTERS["wb-persona-repair-ledger"] = "11/11 신규(수선통장) — 장기수선충당금 기록 전담, 가격 전망을 하지 않는 계정"

DISTRICTS = ["서초", "강남", "송파", "강동", "마포"]
COMPLEX_GU = {"one-bailey": "서초", "eunma": "강남", "helio-city": "송파", "ricents": "송파",
              "godeok-gracium": "강동", "mapo-raemian-prugio": "마포"}


def week_key(w):
    m, d = w.split(".")
    return int(m), int(d)


def last_weeks(rel, gu, n=LOOKBACK):
    """그 발표 표의 마지막 n주(오래된 것부터). 다른 발표의 값은 섞지 않는다."""
    wk = rel["weeks"][-n:]
    return [(w, rel["gu"][gu]["sale"]["weekly"][w]) for w in wk]


def base_p(values):
    u = sum(1 for v in values if v > 0)
    d = sum(1 for v in values if v < 0)
    return round(0.5 + 0.1 * (u - d), 2), u, d


def vote(p, optimism):
    q = min(max(p + (optimism - 3) * 0.04, 0.05), 0.95)
    q = round(q, 2)
    return ("up" if q > 0.5 else "down" if q < 0.5 else None), q


def outcome(v):
    return "up" if v > 0 else "down" if v < 0 else None


def forecast(rel, gu, voters=None):
    """한 발표(as-of)로 다음 주 한 구의 예측을 낸다. voters 를 안 주면 장부 패널 v1"""
    vals = last_weeks(rel, gu)
    p, u, d = base_p([v for _, v in vals])
    votes = []
    for pid, name, opt, src in (LEDGER_VOTERS if voters is None else voters):
        side, q = vote(p, opt)
        votes.append({"persona": pid, "name": name, "optimism": opt, "optimism_source": src, "q": q, "side": side})
    up = sum(1 for v in votes if v["side"] == "up")
    down = sum(1 for v in votes if v["side"] == "down")
    consensus = "up" if up > down else "down" if down > up else None
    return {"gu": gu, "inputs": vals, "u": u, "d": d, "p": p, "votes": votes,
            "tally": {"up": up, "down": down, "hold": len(votes) - up - down}, "consensus": consensus}


def _selftest():
    assert base_p([-0.1, -0.2, -0.3, -0.4]) == (0.1, 0, 4)
    assert base_p([0.1, 0.0, -0.1, 0.2]) == (0.6, 2, 1)
    assert vote(0.5, 2) == ("down", 0.46) and vote(0.5, 3) == (None, 0.5) and vote(0.9, 5) == ("up", 0.95)
    assert vote(0.1, 1) == ("down", 0.05)
    assert outcome(0.0) is None and outcome(-0.01) == "down"
    assert not {v[0] for v in VOTERS} & set(NON_VOTERS)
    assert not {v[0] for v in MARKET_VOTERS} & set(NON_VOTERS)
    assert [v[0] for v in LEDGER_VOTERS] == ["wb-persona-policy-lab", "wb-persona-real-talk", "wb-persona-demand-check",
                                            "wb-persona-num-compare", "wb-persona-cashflow", "wb-persona-field-scout"]
    assert [v[2] for v in LEDGER_VOTERS] == [2, 2, 3, 3, 3, 3]          # 장부 패널은 고정
    assert len({v[0] for v in MARKET_VOTERS}) == len(MARKET_VOTERS) == 12
    assert market_panel("2026-11-02") == list(LEDGER_VOTERS)            # 이미 낸 판은 옛 패널
    assert [v[1] for v in market_panel("2026-11-09")] == ["수요밀도체크", "숫자비교표", "시장경고등", "정책데이터랩",
                                                          "현장입지파", "역발상복덕방", "가치입지연구소"]   # ISO 46주
    assert len(market_panel("2026-11-16")) == 3 and len(market_panel("2026-12-07")) == 3 + 4 + 5   # 47주 · 50주 첫 판
    assert vote(0.5, 1) == ("down", 0.42) and vote(0.5, 4) == ("up", 0.54)


_selftest()
