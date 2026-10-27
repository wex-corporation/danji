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
  명세가 베팅을 막은 페르소나는 넣지 않는다. 낙관 점수는 명세에 적힌 것만 쓰고,
  적혀 있지 않으면 중립(3)으로 둔다 — 점수를 지어내지 않는다.
"""

ENGINE = "주간 흐름 엔진 v1"
LOOKBACK = 4

# (external_id, 화면 이름, 낙관, 낙관 출처)
VOTERS = [
    ("wb-persona-policy-lab", "정책데이터랩", 2, "명세 481줄(낙관 2)"),
    ("wb-persona-real-talk", "현실부동산톡", 2, "명세 481줄(낙관 2)"),
    ("wb-persona-demand-check", "수요밀도체크", 3, "명세에 점수 없음 → 중립"),
    ("wb-persona-num-compare", "숫자비교표", 3, "명세에 없는 페르소나 → 중립"),
    ("wb-persona-cashflow", "현금흐름생활자", 3, "명세에 없는 페르소나 → 중립"),
    ("wb-persona-field-scout", "현장입지파", 3, "명세에 점수 없음 → 중립"),
]
# 투표하지 않는 페르소나와 이유. 생성기·투표 스크립트가 이 표로 막는다
NON_VOTERS = {
    "wb-persona-trade-brief": "명세 INF-013: 확정 베팅 없음, 조건부 확률 코멘트만",
    "wb-persona-psy-thermo": "명세 INF-002: 베팅 월 1회 이하, 마켓 쏠림 해설 전담",
    "wb-persona-question-post": "명세 CUR-001: 분석·전망·베팅 금지",
    "wb-persona-tax-oneline": "명세 INF-023: 베팅 없음",
    "wb-persona-tax-scenario": "명세 INF-024: 베팅 없음",
    "wb-persona-appraisal-check": "명세 INF-031 공시가격체크 계열: 판정 이해충돌, 본인 베팅 금지",
    "wb-persona-contrarian": "휴면(전망 소재라 깨우지 않는다)",
    "wb-persona-school-move": "휴면(학군 소재라 깨우지 않는다)",
}

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


def forecast(rel, gu):
    """한 발표(as-of)로 다음 주 한 구의 예측을 낸다."""
    vals = last_weeks(rel, gu)
    p, u, d = base_p([v for _, v in vals])
    votes = []
    for pid, name, opt, src in VOTERS:
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


_selftest()
