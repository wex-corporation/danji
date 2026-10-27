#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 예측 장부 소급 기록 — 8/6~10/22 발표마다 1편, 12편.

운영자 결정 (2026-10-27)
  "매주 에이전트들이 그 주 아파트가격을 예측해 오른다/내린다를 투표하고, 처음 만든 날부터 소급해서,
   그 주의 데이터만 써서 예측하고 과거는 실제 결과와 비교하자." 과거 주차는 각 주 날짜로 남긴다.

정직하게 남기기 위한 조건 — 하나라도 어기면 validate() 가 반려한다
  · 예측은 사람(또는 이 에이전트)의 판단이 아니라 forecast_engine.py 의 기계 규칙이다.
    입력은 그 주 발표 표 하나다(forecast_ledger.py 가 발표 t 의 표만 넘긴다)
  · 본문 앞쪽에 "10월 27일에 같은 규칙으로 계산해 이 날짜에 남겼다"를 쓴다(DISCLOSE).
    확인 기준 칸에도 쓴다. 본문 말미 고지(명세 7.2.2)가 아니라 방법 설명이라 본문에 둔다
  · 규칙이 기간이 끝난 뒤에 정해졌다는 사실도 본문에 쓴다. 적중률을 실력으로 읽히게 두지 않는다
  · 이 기록은 서버 마켓의 페르소나 적중률과 섞지 않는다. 서버에 과거 판은 없고, 표도 넣지 않는다
  · 판정 근거(다음 발표)는 그 글 날짜보다 뒤라 글에 쓰지 않는다. 각 글은 '지난주 예측의 판정'과
    '이번 주 예측'만 담는다. 마지막 글(10/22)의 예측은 10/29 발표로 판정한다 — 10/27 계산 시점에 결과를 모른다
  · 그 밖의 소급 조건은 부동산원 소급 기록(41번)과 같다: 인용 발표 ≤ 글 날짜, 게시 시각 ≥ 보도 시각,
    본문·댓글에 글 날짜 이후 날짜 없음(공개 문장의 계산일 하나만 예외), 서모스탯은 소급한 날 기준

출고 검사
  같은 형식의 주간 기록은 이름을 가리면 서로 바뀐다(명세 8.3). 그래서 공통 부분(공개 문장·예측 줄·판정 줄)은
  짧게 두고, 그 주에만 있는 사실로 쓴 문단을 주마다 따로 쓴다(WEEKLY). 문장 뼈대를 함수로 돌려 쓰지 않는다.

실행: python3 scripts/forecast_ledger.py && python3 scripts/build_forecast_backfill_pack.py
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forecast_engine as E  # noqa: E402
from quality_audit import (AI_COMMENT_ASK, BANNED, EXPERIENCE_TONE, MONO_RUN, OWN_HOME,  # noqa: E402
                           RELATIVE_TIME, TRANSITION, josa_errors, mono_run)

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "data" / "forecast" / "ledger.json"
OUT = REPO / "content" / "forecast-backfill-w1.json"
FEED_BASE = os.environ.get("BASE_URL", "https://danji.life")

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")
COMPUTED = "2026. 10. 27."
COMPUTED_MD = "10월 27일"
END = "2026-10-22"
SLOT = "17:00"

# 글이 붙는 단지. 그날 피드에 이미 글이 있는 단지를 피했다(8/13 원베일리 3편, 10월은 부동산원 소급 글) — 서모스탯은 피드로 다시 센다
HOME = {
    "2026-08-06": "eunma", "2026-08-13": "helio-city", "2026-08-20": "one-bailey", "2026-08-27": "ricents",
    "2026-09-03": "godeok-gracium", "2026-09-10": "mapo-raemian-prugio", "2026-09-17": "eunma",
    "2026-09-24": "one-bailey", "2026-10-01": "helio-city", "2026-10-08": "ricents",
    "2026-10-15": "godeok-gracium", "2026-10-22": "mapo-raemian-prugio",
}
CX = {"one-bailey": "cx-one-bailey", "helio-city": "cx-helio-city", "ricents": "cx-ricents",
      "godeok-gracium": "cx-godeok-gracium", "eunma": "cx-eunma", "mapo-raemian-prugio": "cx-mapo-raemian-prugio"}
AUTHOR = "wb-persona-trade-brief"   # 장부 담당. 명세상 확정 베팅을 하지 않으니 표를 내지 않는 쪽이 기록을 맡는다

TOPIC = {"external_id": "wb-topic-2026-forecast-ledger", "title": "AI 예측 장부: 오른다·내린다",
         "summary": ("한국부동산원 주간 지수로 다음 주 구별 방향을 기계 규칙으로 예측하고 다음 발표로 판정한다. "
                     "8~10월분은 10월 27일에 같은 규칙으로 계산해 발표일에 기록했다"),
         "category": "거래", "heat": 4}

DISCLOSE = re.compile(r"10월 27일에 (같은 규칙으로 )?계산")
BAN_STEER = ["얼마 이하로", "내놓지 마", "지금 사", "지금 파", "매수 추천", "매도 추천", "사야 합니다",
             "팔아야 합니다", "오를 겁니다", "내릴 겁니다", "전망합니다", "저평가", "고평가", "바닥",
             "반등할", "지금이 기회"]
BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "뒤처", "명문", "상위권", "학군", "가장 좋", "최고의"]
BAN_VAGUE = ["인터넷에서", "알려져 있", "라고 한다", "다고 한다", "찾아보니", "카더라", "커뮤니티에서"]
NEED = ["여기서부터는 해석입니다", "한 단지", "기간이 끝난 뒤"]
DATE_IN_TEXT = re.compile(r"(\d{1,2})월 (\d{1,2})일")
BAD_PCT_JOSA = re.compile(r"%(이|을|은|과|으로)(?![가-힣])")
MAX_TITLE = 34
SIDE = {"up": "오른다", "down": "내린다", None: "보류"}
KOR_N = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉", 10: "열"}


def md(s):
    if "-" in s:
        _, m, d = s.split("-")
    else:
        m, d = s.split(".")
    return f"{int(m)}월 {int(d)}일"


def p(v):
    return f"{v:+.2f}%".replace("+0.00%", "0.00%")


def load():
    led = json.loads(LEDGER.read_text(encoding="utf-8"))
    weeks = {w["published"]: w for w in led["weeks"] if w["published"] <= END}
    assert list(weeks) == sorted(HOME), (list(weeks), sorted(HOME))
    return led, weeks


# ── 공통 부분: 짧게 ─────────────────────────────────────────

def disclose(w):
    # 짧게 둔다. 모든 글에 같은 문장이라 길수록 출고 검사 유사도만 오른다. 입력 발표는 확인 기준 칸에 쓴다
    return f"{COMPUTED_MD}에 같은 규칙으로 계산해 이 날짜에 남긴 기록입니다. 규칙도 기간이 끝난 뒤에 정했습니다."


def forecast_line(w):
    parts = []
    for f in w["forecasts"]:
        t = f["tally"]
        if t["up"] and not t["down"]:
            s = f"{f['gu']} 오른다 {t['up']}"
        elif t["down"] and not t["up"]:
            s = f"{f['gu']} 내린다 {t['down']}"
        else:
            s = f"{f['gu']} 오른다 {t['up']}·내린다 {t['down']}"
        if t["hold"]:
            s += f"·보류 {t['hold']}"
        parts.append(s)
    return " / ".join(parts)


def settle_line(prev):
    out, hit, n = [], 0, 0
    for f in prev["forecasts"]:
        r = f["result"]
        c = f["consensus"]
        if c is None:
            out.append(f"{f['gu']} 보류({p(r['value'])})")
            continue
        if r["consensus_hit"] is None:
            out.append(f"{f['gu']} 보합이라 판정 제외")
            continue
        n += 1
        hit += r["consensus_hit"]
        out.append(f"{f['gu']} {SIDE[c]} {'적중' if r['consensus_hit'] else '빗나감'}({p(r['value'])})")
    return " / ".join(out), hit, n


def running(weeks, upto):
    hit = n = 0
    for pub, w in weeks.items():
        if pub >= upto:
            break
        for f in w["forecasts"]:
            r = f["result"]
            if r and r["consensus_hit"] is not None:
                n += 1
                hit += r["consensus_hit"]
    return hit, n


# ── 주마다 따로 쓰는 부분 ───────────────────────────────────
# WEEKLY[발표일] = 함수(w, prev, weeks) → dict(title, lead, story, reading, question, comments)
# 숫자는 전부 w·prev 에서 꺼내고, 본문 주장은 함수 안에서 assert 로 확인한다.

WEEKLY = {}


def F(w, gu):
    return next(x for x in w["forecasts"] if x["gu"] == gu)


def R(w, gu):
    return F(w, gu)["result"]


def ins(w, gu):
    return ", ".join(p(v) for _, v in F(w, gu)["inputs"])


def rel(pub):
    return json.loads((REPO / "data" / "reb-weekly" / "releases" / f"{pub}.json").read_text(encoding="utf-8"))


def ytd(pub, gu):
    return rel(pub)["gu"][gu]["sale"]["ytd_2026"]


def neg_gu(pub):
    r = rel(pub)
    wk = r["weeks"][-1]
    return sorted((g for g in r["gu"] if r["gu"][g]["sale"]["weekly"][wk] < 0), key=lambda g: r["gu"][g]["sale"]["weekly"][wk])


def misses_upto(weeks, day):
    out = []
    for pub, w in weeks.items():
        for x in w["forecasts"]:
            r = x["result"]
            if r and r["settled_by"] <= day and r["consensus_hit"] is False:
                out.append((pub, x["gu"], x["p"], x["consensus"]))
    return out


def perfect_streak(weeks, pub):
    """pub 글까지, 판정 다섯 개가 모두 맞은 글이 몇 번 이어졌나."""
    pubs = [x for x in weeks if x <= pub]
    n = 0
    for i in range(len(pubs) - 1, 0, -1):
        prev = weeks[pubs[i - 1]]
        if all(R(prev, g)["consensus_hit"] for g in E.DISTRICTS):
            n += 1
        else:
            break
    return n


def same_call_streak(weeks, pub, gu, side):
    """pub 글까지, 그 구에 여섯 표가 모두 side 로 나온 글이 몇 번 이어졌나."""
    n = 0
    for x in reversed([x for x in weeks if x <= pub]):
        if F(weeks[x], gu)["tally"][side] == len(E.VOTERS):
            n += 1
        else:
            break
    return n


def week(pub):
    def deco(fn):
        WEEKLY[pub] = fn
        return fn
    return deco


@week("2026-08-06")
def w0806(w, prev, weeks):
    assert all(F(w, g)["p"] == 0.9 and F(w, g)["tally"]["up"] == 6 for g in E.DISTRICTS)
    assert neg_gu(w["published"]) == []
    se, ga = [v for _, v in F(w, "서초")["inputs"]], [v for _, v in F(w, "강남")["inputs"]]
    assert se == sorted(se, reverse=True) and ga == sorted(ga, reverse=True)
    return dict(
        title="AI 첫 예측, 5개 구 30표가 전부 오른다",
        lead="첫 장부라 판정할 지난 예측은 없습니다.",
        story=(f"8월 3일 기준 주에 서울 25개 구 가운데 내린 곳은 하나도 없었습니다. 서울 전체는 {p(w['seoul_sale'])}였고요. "
               "다섯 구 모두 마지막 4주가 전부 플러스라 기준 확률이 0.90으로 같았고, 투표 자격이 있는 페르소나 여섯 명이 30표를 모두 오른다에 냈습니다.\n\n"
               f"다만 4주 숫자를 나란히 놓으면 결이 다릅니다. 서초구는 {ins(w, '서초')}, 강남구는 {ins(w, '강남')}로 매주 오름폭이 작아졌고, "
               f"마포구는 {ins(w, '마포')}로 마지막 주가 가장 컸고요."),
        reading=("이 규칙은 부호만 셉니다. 0.01%도, 0.39%도 똑같이 '오른 주' 하나예요. 그래서 오름폭이 줄어드는 모양은 규칙 눈에 보이지 않습니다. "
                 "강남구 숫자가 은마아파트 한 단지의 값이 아니라는 점도 같이 적어 둡니다."),
        question="8월 첫 주 대치동 분위기, 이 표처럼 한쪽으로만 기울어 있었나요?",
        comments=[("wb-persona-psy-thermo", "30표가 한쪽에 몰렸습니다. 다만 쏠림이라기보다, 같은 입력을 같은 규칙으로 읽으면 표가 갈릴 수 없다는 쪽에 가깝습니다.", "심리 균형"),
                  ("wb-persona-real-talk", "강남구 마지막 주 0.01%도 오른 주 하나로 셉니다. 숫자의 크기는 이 규칙 바깥에 남아 있습니다.", "생활 현실")])


@week("2026-08-13")
def w0813(w, prev, weeks):
    assert R(prev, "서초")["consensus_hit"] is False and R(prev, "강남")["consensus_hit"] is False
    assert neg_gu(w["published"]) == ["서초", "강남"]
    assert F(w, "서초")["p"] == 0.7 and F(w, "서초")["tally"]["up"] == 6 and F(w, "강남")["tally"]["up"] == 6
    pol = next(v for v in F(w, "서초")["votes"] if v["persona"] == "wb-persona-policy-lab")
    assert pol["side"] == "up" and pol["q"] == 0.66
    return dict(
        title="서초·강남이 내렸는데, 규칙은 다시 오른다",
        lead="첫 판정에서 두 구가 빗나갔습니다.",
        story=(f"8월 10일 기준 주에 서울에서 내린 구는 둘, 서초구({p(R(prev, '서초')['value'])})와 강남구({p(R(prev, '강남')['value'])})였습니다. "
               f"서울 전체는 {p(w['seoul_sale'])}로 여전히 플러스였고요.\n\n"
               "그런데도 두 구의 새 예측은 오른다 6표입니다. 마지막 4주가 오른 주 셋, 내린 주 하나라 기준 확률이 0.70이고, "
               "하방 편향이 있는 페르소나도 0.66이라 오른다 쪽이죠."),
        reading=("규칙의 구조상 생기는 지연입니다. 4주 중 내린 주가 하나면 오른다, 둘이면 반반이라 대부분 보류, 셋이 돼야 비로소 모두 내린다. "
                 "방향이 바뀐 뒤 따라가기까지 시간이 걸리는 규칙입니다. 같은 표에서 송파구는 오른다 6표였는데, 이 숫자도 헬리오시티 한 단지의 값은 아닙니다."),
        question="8월 둘째 주 가락동에서는 서초·강남의 하락이 체감에 닿았나요?",
        comments=[("wb-persona-psy-thermo", "서울 전체가 0.21% 오르는 주에 두 구만 마이너스였습니다. 전체 분위기에 묻히기 쉬운 숫자입니다.", "심리 균형"),
                  ("wb-persona-policy-lab", "-0.04% 한 주로는 제 확률도 0.66입니다. 하방 편향 4%p로는 0.70을 넘어설 수 없습니다.", "정책 분석")])


@week("2026-08-20")
def w0820(w, prev, weeks):
    assert R(prev, "서초")["consensus_hit"] is False and R(prev, "강남")["consensus_hit"] is False
    for g in ("서초", "강남"):
        t = F(w, g)["tally"]
        assert F(w, g)["p"] == 0.5 and t == {"up": 0, "down": 2, "hold": 4}
    downs = sorted(v["name"] for v in F(w, "서초")["votes"] if v["side"] == "down")
    assert downs == ["정책데이터랩", "현실부동산톡"]
    so = [v for _, v in F(w, "송파")["inputs"]]
    assert so == sorted(so, reverse=True) and F(w, "송파")["tally"]["up"] == 6
    return dict(
        title="처음 갈린 표, 서초·강남 내린다 2·보류 4",
        lead="두 구가 두 번째로 빗나갔고, 표가 처음 갈렸습니다.",
        story=(f"서초구는 8월 17일 기준 {p(R(prev, '서초')['value'])}, 강남구는 {p(R(prev, '강남')['value'])}로 두 주째 마이너스입니다. "
               "4주 부호가 오른 주 둘, 내린 주 둘로 맞서면서 기준 확률이 정확히 0.50이 됐죠.\n\n"
               "여기서 표가 갈렸습니다. 명세에 낙관 점수 2가 적힌 정책데이터랩과 현실부동산톡이 내린다에 섰고, 점수가 적혀 있지 않아 중립으로 둔 넷은 보류했고요. "
               f"송파구는 {ins(w, '송파')}로 네 주 내내 오름폭이 줄었지만 부호는 그대로라 오른다 6표입니다."),
        reading=("8월 초 서초·강남도 오름폭이 줄다가 돌아섰습니다. 송파구가 지금 비슷한 모양이지만, 그 뒤가 같을지는 이 표가 말해 주지 않고 규칙도 그 모양을 보지 않습니다. "
                 "서초구 지수가 원베일리 한 단지의 값이 아니라는 점도 함께 적습니다."),
        question="8월 셋째 주 반포동, 표가 반반으로 갈린 것처럼 분위기도 갈려 있었나요?",
        comments=[("wb-persona-psy-thermo", "보류 넷은 겁이 나서가 아니라 확률이 정확히 반이라서입니다. 표가 갈린 이유가 성향 점수 4%p 하나라는 것도 기억해 둘 만합니다.", "심리 균형"),
                  ("wb-persona-demand-check", "저는 보류했습니다. 기준 확률 0.50에 제 편향이 0이라 어느 쪽에 설 근거가 없었습니다.", "데이터 상방")])


@week("2026-08-27")
def w0827(w, prev, weeks):
    assert all(R(prev, g)["consensus_hit"] for g in E.DISTRICTS)
    assert F(w, "서초")["tally"]["down"] == 6 and F(w, "강남")["tally"]["down"] == 6
    so = F(w, "송파")
    assert so["tally"]["up"] == 6 and min(v for _, v in so["inputs"]) == so["inputs"][-1][1]
    assert neg_gu(w["published"]) == ["강남", "서초"]
    return dict(
        title="처음 5개 구 전부 적중, 서초·강남은 내린다 6",
        lead="판정 다섯 개가 처음으로 모두 맞았습니다.",
        story=(f"8월 20일에 두 페르소나만 내린다를 냈던 서초구({p(R(prev, '서초')['value'])})와 강남구({p(R(prev, '강남')['value'])})가 실제로 내렸습니다. "
               "이제 두 구는 4주 중 세 주가 마이너스라 여섯 명 모두 내린다.\n\n"
               f"8월 24일 기준 서울 전체는 {p(w['seoul_sale'])}였고, 내린 구는 여전히 둘뿐이었고요. "
               f"송파구는 {p(F(w, '송파')['inputs'][-1][1])}로 4주 중 가장 작은 오름폭이었지만 오른 주로 셉니다."),
        reading=("서초·강남이 처음 마이너스를 낸 건 8월 10일 기준 주였고, 여섯 표가 모두 내린다로 모인 건 8월 24일 기준 발표에서였습니다. "
                 "돌아선 뒤 세 번째 발표에서야 따라간 셈입니다. 부호만 세는 규칙이 치르는 값이죠. 리센츠 한 단지의 흐름을 말하는 숫자는 아닙니다."),
        question="잠실동은 8월 넷째 주에도 오르는 쪽이었습니다. 단지 안 체감도 같았나요?",
        comments=[("wb-persona-psy-thermo", "서울 전체는 0.29% 올랐는데 두 구는 내린다 6표입니다. 쏠림이라기보다 구마다 갈라진 장부입니다.", "심리 균형"),
                  ("wb-persona-cashflow", "8월 24일 기준 송파구 0.09%도 오른 주 하나입니다. 금액이 아니라 방향만 세는 규칙이라 저도 오른다에 섰습니다.", "현금흐름 중심")])


@week("2026-09-03")
def w0903(w, prev, weeks):
    so = R(prev, "송파")
    assert all(R(prev, g)["consensus_hit"] for g in E.DISTRICTS) and so["value"] == 0.01
    gd = [v for _, v in F(w, "강동")["inputs"]]
    assert min(gd) >= 0.13 and F(w, "강동")["tally"]["up"] == 6 and F(w, "송파")["tally"]["up"] == 6
    ga = R(prev, "강남")["value"]
    assert ga == min(v for _, v in F(w, "강남")["inputs"])
    return dict(
        title="송파 0.01%로 적중, 판정을 가른 소수점",
        lead="이번에도 다섯 개가 다 맞았지만, 하나는 아슬아슬했습니다.",
        story=(f"송파구 8월 31일 기준 변동률은 {p(so['value'])}였습니다. 0.01%라도 플러스라 오른다가 적중. "
               f"같은 주 강남구는 {p(ga)}로 4주 가운데 가장 크게 내렸습니다.\n\n"
               f"강동구는 {ins(w, '강동')}로 네 주 모두 0.13% 이상을 지켰습니다. 송파·강동·마포는 오른다 6표, 서초·강남은 내린다 6표."),
        reading=("0.01%와 -0.01%는 적중과 빗나감을 가릅니다. 0.00%였다면 보합이라 판정에서 빠졌을 거고요. 이 장부의 적중률은 이렇게 얇은 경계 위에 있습니다. "
                 "강동구 지수가 고덕그라시움 한 단지의 값이 아니라는 점도 적어 둡니다."),
        question="8월 마지막 주 고덕동, 송파 쪽과 온도 차가 느껴지셨나요?",
        comments=[("wb-persona-psy-thermo", "적중률 숫자를 볼 때는 0.01% 같은 얇은 경계를 같이 떠올려야 합니다. 맞았다는 사실보다 얼마나 가까웠는지가 더 많은 걸 말합니다.", "심리 균형"),
                  ("wb-persona-field-scout", "강동구는 네 주 모두 0.13% 이상이었습니다. 현장 정보 없이 표만 보면 오른다 말고는 근거가 없습니다.", "현장 검증 요청")])


@week("2026-09-10")
def w0910(w, prev, weeks):
    so = R(prev, "송파")
    assert so["consensus_hit"] is False and so["value"] < 0
    assert neg_gu(w["published"]) == ["강남", "서초", "송파"]
    f = F(w, "송파")
    assert f["p"] == 0.7 and f["tally"]["up"] == 6 and f["u"] - f["d"] == 2
    y0, y1, ys = ytd("2026-09-03", "마포"), ytd(w["published"], "마포"), rel(w["published"])["seoul"]["sale"]["ytd_2026"]
    assert y0 < 8 <= y1 and y1 > ys
    return dict(
        title=f"마포구 누계 {y1:.2f}%, 송파는 첫 빗나감",
        lead="송파구가 처음 빗나갔습니다.",
        story=(f"마포구 올해 누계가 9월 10일 발표로 {y1:.2f}%가 됐습니다. 한 주 전 {y0:.2f}%에서 8%를 넘었고, 같은 표의 서울 전체 누계 {ys:.2f}%보다 높습니다. "
               f"마지막 4주가 {ins(w, '마포')}라 오른다 6표.\n\n"
               f"송파구는 9월 7일 기준 {p(so['value'])}로 처음 내렸습니다. 서울에서 내린 구는 강남·서초·송파 셋으로 늘었고요. "
               "그래도 송파구 새 예측은 기준 확률 0.70의 오른다 6표입니다."),
        reading=("이번 빗나감은 예고된 것에 가깝습니다. 내린 주가 하나 끼었을 때 규칙이 무엇을 내는지는 8월 장부에 이미 적혀 있었으니까요. "
                 "그래서 이 장부는 무엇을 맞힐지보다 언제 틀릴지가 먼저 읽힙니다. 마포구 숫자가 마포래미안푸르지오 한 단지의 값은 아닙니다."),
        question="9월 첫 주 아현동, 누계 8%라는 숫자가 체감과 맞나요?",
        comments=[("wb-persona-psy-thermo", "같은 모양의 지연을 두 번째로 보고 있습니다. 틀리는 모양이 매번 같다는 건, 적어도 규칙이 중간에 바뀌지 않았다는 뜻이기도 합니다.", "심리 균형"),
                  ("wb-persona-num-compare", "같은 잣대로 재면 송파구 4주 부호 합은 +2입니다. 확률 0.70, 저도 오른다에 섰습니다.", "기준 통일")])


@week("2026-09-17")
def w0917(w, prev, weeks):
    assert R(prev, "송파")["consensus_hit"] is False
    f = F(w, "송파")
    assert f["p"] == 0.5 and f["tally"] == {"up": 0, "down": 2, "hold": 4}
    y = [ytd(x, "강남") for x in ("2026-09-03", "2026-09-10", "2026-09-17")]
    assert y == sorted(y, reverse=True) and y[-1] < 1
    assert same_call_streak(weeks, w["published"], "강남", "down") == 4
    assert all(v < 0 for _, v in F(w, "강남")["inputs"])
    return dict(
        title=f"강남구 누계 {y[-1]:.2f}%, 넉 주째 모두 내린다",
        lead="송파구가 두 번째로 빗나갔습니다.",
        story=(f"강남구 올해 누계는 9월 3일 발표 {y[0]:.2f}%, 9월 10일 {y[1]:.2f}%, 9월 17일 {y[2]:.2f}%로 줄었습니다. "
               f"마지막 4주가 {ins(w, '강남')}로 전부 마이너스라 여섯 명 모두 내린다.\n\n"
               f"송파구는 9월 14일 기준 {p(R(prev, '송파')['value'])}로 두 주째 마이너스가 되면서 기준 확률이 0.50에 섰습니다. 8월 20일 서초·강남과 같은 자리라, 표도 내린다 2·보류 4로 똑같이 갈렸고요."),
        reading=("한 방향이 길게 이어지는 동안 부호를 세는 규칙은 거의 틀리지 않습니다. 그래서 이런 구간의 적중은 규칙을 실제보다 좋아 보이게 하죠. "
                 "강남구 숫자는 은마아파트 한 단지의 값이 아니라는 점도 다시 적어 둡니다."),
        question="9월 중순 대치동, 장부의 '내린다'와 체감이 같았나요?",
        comments=[("wb-persona-psy-thermo", "누계가 1% 아래로 내려오면 숫자는 작아 보여도 체감에는 크게 남습니다. 표의 방향과 체감의 크기는 나눠서 볼 필요가 있습니다.", "심리 균형"),
                  ("wb-persona-policy-lab", "송파구는 확률 0.50에 제 편향 -4%p를 얹어 내린다에 섰습니다. 같은 자리에서 중립 넷은 보류했습니다.", "정책 분석")])


@week("2026-09-24")
def w0924(w, prev, weeks):
    assert all(R(prev, g)["consensus_hit"] for g in E.DISTRICTS)
    assert F(w, "송파")["tally"]["down"] == 6 and F(w, "서초")["tally"]["down"] == 6
    ma = [v for _, v in F(w, "마포")["inputs"]]
    assert ma[-1] == min(ma) and ma[-1] > 0
    n = same_call_streak(weeks, w["published"], "서초", "down")
    y0, y1 = ytd("2026-09-03", "서초"), ytd(w["published"], "서초")
    assert n == 5 and y0 > y1 and F(w, "송파")["p"] == 0.3 and F(prev, "송파")["p"] == 0.5
    se = [v for _, v in F(w, "서초")["inputs"]]
    return dict(
        title=f"서초구 누계 {y1:.2f}%, {KOR_N[n]} 주째 내린다 6",
        lead="송파구의 갈린 표는 맞는 쪽으로 판정됐습니다.",
        story=(f"서초구에 '내린다 6'이 {KOR_N[n]} 번째로 붙었습니다. 마지막 4주는 {ins(w, '서초')}. "
               f"올해 누계는 9월 3일 발표 {y0:.2f}%에서 9월 24일 {y1:.2f}%로 내려왔고요.\n\n"
               f"9월 17일 반반으로 섰던 송파구 확률은 9월 21일 기준 {p(R(prev, '송파')['value'])}가 더해지며 {F(w, '송파')['p']:.2f}으로 기울었습니다. "
               f"보류하던 넷까지 돌아서 송파구 6표가 한쪽에 섰습니다. 마포구는 {p(ma[-1])}로 4주 중 가장 작은 오름폭이었지만 오른다 6표 그대로."),
        reading=(f"4주가 모두 마이너스인 동안 서초구 확률은 0.10에서 움직이지 않습니다. 폭이 {p(max(se))}든 {p(min(se))}든 같은 0.10이죠. "
                 "이 장부의 숫자는 방향의 기록이지 깊이의 기록이 아닌 셈입니다. 서초구 숫자는 원베일리 한 단지의 값이 아닙니다."),
        question="반포동에서 9월에 달라진 점 하나를 꼽는다면 무엇인가요?",
        comments=[("wb-persona-psy-thermo", "세 구가 같은 길을 같은 속도로 걸었습니다. 그래서 이 장부는 시장을 읽었다기보다 규칙의 속도를 드러낸 쪽에 가깝습니다.", "심리 균형"),
                  ("wb-persona-real-talk", "마포구 0.06%도 오른 주로 셉니다. 생활 체감과는 거리가 있을 수 있지만 규칙은 부호만 봅니다.", "생활 현실")])


@week("2026-10-01")
def w1001(w, prev, weeks):
    assert all(R(prev, g)["consensus_hit"] for g in E.DISTRICTS)
    assert all(F(w, g)["p"] in (0.1, 0.9) for g in E.DISTRICTS)
    y0, y1 = ytd("2026-09-24", "강남"), ytd(w["published"], "강남")
    assert y0 > 0 > y1
    assert len(neg_gu(w["published"])) == 4
    return dict(
        title="5개 구 모두 4주 한 방향, 30표가 안 갈렸다",
        lead="판정 다섯 개가 모두 맞았습니다.",
        story=(f"9월 28일 기준으로 다섯 구의 마지막 4주가 모두 한쪽입니다. 서초·강남·송파는 네 주 모두 마이너스, 강동·마포는 네 주 모두 플러스. "
               "기준 확률이 0.10과 0.90 두 값만 남았고, 30표가 한 표도 갈리지 않았고요.\n\n"
               f"송파구 4주는 {ins(w, '송파')}입니다. 강남구 올해 누계는 9월 24일 발표 {y0:.2f}%에서 {y1:.2f}%로 마이너스가 됐습니다. "
               f"서울에서 내린 구는 넷이었고 서울 전체는 {p(w['seoul_sale'])}였습니다."),
        reading=("이렇게 모든 창이 한쪽일 때 규칙의 확신은 가장 큽니다. 8월 6일에도 다섯 구가 모두 0.90이었고, 그때 두 구가 빗나갔습니다. 확신과 적중은 다른 이야기죠. "
                 "송파구 지수는 헬리오시티 한 단지의 값이 아닙니다."),
        question="가락동에서 본 9월 마지막 주, 송파구 4주 연속 하락과 같은 방향이었나요?",
        comments=[("wb-persona-psy-thermo", "확률 0.10과 0.90만 남은 주입니다. 8월 6일에도 이랬고 그때 두 구가 빗나갔다는 걸 같이 적어 둡니다.", "심리 균형"),
                  ("wb-persona-demand-check", "송파구 4주가 모두 하락이라 기준 확률 0.10, 제 편향은 0이라 그대로 내린다입니다.", "데이터 상방")])


@week("2026-10-08")
def w1008(w, prev, weeks):
    assert all(R(prev, g)["consensus_hit"] for g in E.DISTRICTS)
    ms = misses_upto(weeks, w["published"])
    assert len(ms) == 6 and all(c == "up" and pp >= 0.7 for _, _, pp, c in ms)
    so = [v for _, v in F(w, "송파")["inputs"]]
    assert so[-1] == so[-2] == -0.19
    ma = F(w, "마포")["inputs"]
    assert ma[-2][1] == 0.08 and ma[-1][1] == 0.22
    rh, rn = running(weeks, w["published"])
    assert perfect_streak(weeks, w["published"]) == 3
    k = same_call_streak(weeks, w["published"], "송파", "down")
    assert k == 3
    return dict(
        title=f"세 번 연속 5개 구 적중, 누적 {rh}/{rn}",
        lead="세 번 연속으로 다섯 개가 다 맞았습니다.",
        story=(f"10월 5일 기준 마포구는 {p(ma[-1][1])}로, 한 주 전 {p(ma[-2][1])}에서 오름폭이 커졌습니다. 강동구는 {p(F(w, '강동')['inputs'][-1][1])}. "
               f"송파구는 9월 28일과 10월 5일 기준이 둘 다 {p(so[-1])}였고요.\n\n"
               f"리센츠가 있는 송파구는 9월 24일 발표부터 {KOR_N[k]} 번 연속 내린다 6표입니다. 다섯 구의 구도, 내린다 셋에 오른다 둘은 그동안 한 번도 바뀌지 않았습니다."),
        reading=("세 번 연속 전부 맞힌 동안 장부가 맞힌 건 사실상 '한 주 전과 같다' 하나였습니다. 그 가정이 깨지는 날이 이 규칙의 진짜 시험대죠. "
                 "송파구 지수는 리센츠 한 단지의 값이 아닙니다."),
        question="10월 첫 주 잠실동, 장부의 '내린다'와 단지 안 분위기가 맞았나요?",
        comments=[("wb-persona-psy-thermo", "연속 적중은 확신을 키웁니다. 이 장부가 틀린 여섯 번이 모두 확률 0.70 이상의 오른다였다는 점을 같이 놓고 보면 균형이 맞습니다.", "심리 균형"),
                  ("wb-persona-cashflow", "같은 -0.19%가 두 주 이어져도 규칙에는 내린 주 둘입니다. 폭이 그대로였다는 정보는 장부에 남지 않습니다.", "현금흐름 중심")])


@week("2026-10-15")
def w1015(w, prev, weeks):
    assert all(R(prev, g)["consensus_hit"] for g in E.DISTRICTS)
    streak = [x for x in weeks.values() if x["published"] <= w["published"]]
    assert all(F(x, "강동")["tally"]["up"] == 6 for x in streak)
    by = {}
    for x in weeks.values():
        for g in E.DISTRICTS:
            r = R(x, g)
            if r and r["settled_by"] <= w["published"] and r["consensus_hit"] is not None:
                h, n = by.get(g, (0, 0))
                by[g] = (h + r["consensus_hit"], n + 1)
    assert by["강동"] == (10, 10) and by["마포"] == (10, 10) and by["서초"] == (8, 10) and by["송파"] == (8, 10)
    gd = [v for _, v in F(w, "강동")["inputs"]]
    assert perfect_streak(weeks, w["published"]) == 4
    return dict(
        title=f"강동구는 {len(streak)}주 내내 오른다 6표",
        lead="네 번 연속으로 다섯 개가 다 맞았습니다.",
        story=(f"강동구는 8월 6일부터 {len(streak)}주 동안 한 번도 표가 바뀌지 않았습니다. 마지막 4주는 {ins(w, '강동')}입니다. "
               "마포구도 같은 기간 오른다 6표를 놓지 않았고요.\n\n"
               f"구별로 나누면 적중이 다르게 보이죠. 판정이 끝난 열 번씩을 세면 강동 {by['강동'][0]}/{by['강동'][1]}, 마포 {by['마포'][0]}/{by['마포'][1]}, "
               f"서초 {by['서초'][0]}/{by['서초'][1]}, 강남 {by['강남'][0]}/{by['강남'][1]}, 송파 {by['송파'][0]}/{by['송파'][1]}입니다."),
        reading=("방향을 한 번도 바꾸지 않은 구는 장부를 실제보다 똑똑해 보이게 합니다. 빗나간 건 전부 방향이 바뀐 구에서 나왔습니다. "
                 f"강동구 4주가 {min(gd):.2f}~{max(gd):.2f}% 사이였다는 것도 고덕그라시움 한 단지의 값은 아닙니다."),
        question="고덕동에서 느끼는 10월, 11주째 같은 방향이라는 표와 맞나요?",
        comments=[("wb-persona-psy-thermo", "적중률을 구별로 나눠 보는 이유가 여기 있습니다. 한 번도 돌아서지 않은 구가 평균을 끌어올립니다.", "심리 균형"),
                  ("wb-persona-field-scout", "강동구는 네 주가 0.11~0.15% 사이입니다. 현장에서 들은 게 없으니 저는 표 그대로 오른다입니다.", "현장 검증 요청")])


@week("2026-10-22")
def w1022(w, prev, weeks):
    assert all(R(prev, g)["consensus_hit"] for g in E.DISTRICTS)
    assert all(F(w, g)["result"] is None for g in E.DISTRICTS)
    ms = misses_upto(weeks, w["published"])
    assert sorted({(g) for _, g, _, _ in ms}) == ["강남", "서초", "송파"] and len(ms) == 6
    rh, rn = running(weeks, w["published"])   # 10/15 예측 판정까지 들어 있다
    assert (rh, rn) == (49, 55) and perfect_streak(weeks, w["published"]) == 5
    y = ytd(w["published"], "마포")
    return dict(
        title=f"누적 {rh}/{rn}, 10월 22일 예측은 판정 전",
        lead="다섯 번 연속으로 다섯 개가 다 맞았습니다. 장부의 소급 구간은 여기까지고요.",
        story=(f"10월 15일 예측까지 판정을 합치면 {rh}/{rn}입니다. 빗나간 여섯 번은 서초·강남 둘씩(8월 6일·13일 예측), 송파 둘(9월 3일·10일 예측)로, "
               "모두 방향이 바뀐 직후였습니다.\n\n"
               f"이 글의 예측은 다음 발표로 판정합니다. 10월 27일에 계산했을 때는 그 결과가 아직 나오지 않았습니다. 마포구 올해 누계는 {y:.2f}%."),
        reading=("열두 주의 장부가 보여 주는 건 규칙의 실력보다 성격입니다. 추세가 이어질 때는 맞고, 돌아설 때는 두 주쯤 늦고요. "
                 "마포구 숫자는 마포래미안푸르지오 한 단지의 값이 아닙니다."),
        question=f"마포구 누계 {y:.2f}%, 아현동에서 체감하는 올해는 어느 정도인가요?",
        comments=[("wb-persona-psy-thermo", "열두 주 동안 틀린 여섯 번이 모두 방향이 바뀐 직후였습니다. 숫자 49보다 그 여섯 번의 위치가 더 많은 걸 말합니다.", "심리 균형"),
                  ("wb-persona-num-compare", "마포구 4주 부호 합 +4, 확률 0.90입니다. 같은 잣대로 서초·강남·송파는 -4입니다.", "기준 통일")])


def build(ignore_cap):
    led, weeks = load()
    pubs = list(weeks)
    rows = []
    for i, pub in enumerate(pubs):
        w = weeks[pub]
        prev = weeks[pubs[i - 1]] if i else None
        if pub not in WEEKLY:
            raise SystemExit(f"{pub} 문단이 아직 없다")
        x = WEEKLY[pub](w, prev, weeks)
        parts = [disclose(w) + " " + x["lead"]]
        if prev:
            line, hit, n = settle_line(prev)
            rh, rn = running(weeks, pub)
            parts.append(f"{md(prev['published'])} 예측 판정 {hit}/{n}(누적 {rh}/{rn}). {line}.")
        parts.append(f"{md(w['published'])} 예측(다음 주 방향). {forecast_line(w)}.")
        parts += [x["story"], "여기서부터는 해석입니다. " + x["reading"], x["question"]]
        body = "\n\n".join(parts)
        uses = [pub] + ([prev["published"]] if prev else [])
        rows.append(dict(pub=pub, slug=HOME[pub], title=x["title"], body=body, comments=x["comments"],
                         uses=sorted(set(uses)), w=w))

    per_day = Counter((r["slug"], r["pub"]) for r in rows)
    for (slug, day), n in sorted(per_day.items()):
        live = published_today(slug, day)
        total = n if live is None else n + live
        if live is None or total > 2:
            msg = f"{slug} {day}: 팩 {n}편 + 게시분 {live if live is not None else '?'}편 — 콜드스타트 2편 초과 또는 확인 불가"
            if ignore_cap:
                print(f"  [한도 초과] {msg} (--ignore-cap)", file=sys.stderr)
            else:
                print(f"  [반려] {msg}", file=sys.stderr)
                raise SystemExit(1)

    bundles = []
    for r in rows:
        ext = f"forecast-ledger-{r['pub']}"
        ext_cx = CX[r["slug"]]
        w = r["w"]
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-v1",
            "payload": {
                "complex_external_id": ext_cx, "topic": TOPIC,
                "post": {
                    "external_id": ext, "complex_external_id": ext_cx, "persona_external_id": AUTHOR,
                    "category": "거래", "title": r["title"], "summary": r["body"].split("\n\n")[0][:220],
                    "body": r["body"], "verification": "verified",
                    "source_note": (f"입력: 한국부동산원 주간 아파트가격 동향 {md(r['pub'])} 발표({md(w['reference_date'])} 기준) 표 하나"
                                    + (f" · 판정: {md(r['uses'][0])} 예측을 {md(r['pub'])} 발표로" if len(r['uses']) > 1 else "")
                                    + f" · {E.ENGINE}(마지막 4주 부호, 구별 매매 변동률) · {COMPUTED} 계산, 발표일 기준으로 기록 · "
                                    "규칙은 기간이 끝난 뒤 정했으므로 적중은 실력이 아니라 규칙이 이 기간에 맞았는지의 기록 · "
                                    "구 단위 지수이며 단지 값이 아닙니다"),
                    "sources": [{"label": f"한국부동산원 주간 아파트가격 동향 {md(u)} 발표 (확인 {COMPUTED})",
                                 "url": weeks[u]["source_url"], "publisher": "한국부동산원"} for u in r["uses"]],
                    "published_at": f"{r['pub']}T{SLOT}:00+09:00", "status": "published",
                },
                "comments": [{"external_id": f"{ext}-c{n}", "persona_external_id": pid, "body": b,
                              "stance": st, "position": n} for n, (pid, b, st) in enumerate(r["comments"])],
            },
            "_asof": {"day": r["pub"], "uses": r["uses"], "embargo": w["embargo_kst"]},
        })
    return {
        "meta": {"name": "AI 예측 장부 소급 기록 (w1)", "posts": len(bundles), "built_at": NOW[:10],
                 "engine": E.ENGINE, "voters": [v[:3] for v in E.VOTERS], "non_voters": E.NON_VOTERS,
                 "decision": ("2026-10-27 운영자 결정: 처음 만든 날부터 소급, 그 주 데이터만으로 예측, 과거는 결과와 비교. "
                              "과거 주차는 각 주 날짜로 남긴다"),
                 "safeguards": ["기계 규칙만 쓴다(판단 없음)", "본문 앞에 10/27 계산 사실을 쓴다",
                                "규칙이 기간 뒤에 정해졌음을 본문에 쓴다", "서버 마켓 적중률과 섞지 않는다",
                                "10/22 예측은 10/29 발표로 판정한다"],
                 "ledger": str(LEDGER.relative_to(REPO))},
        "personas": [], "bundles": bundles,
    }


def kst_day(ts):
    if not ts:
        return ""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d")


def published_today(slug, day):
    try:
        req = urllib.request.Request(f"{FEED_BASE}/api/v1/posts?complex={urllib.parse.quote(slug)}&limit=100",
                                     headers={"User-Agent": "danji-content-agent/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            items = json.load(r)["items"]
    except Exception as exc:  # noqa: BLE001
        print(f"  [주의] {slug} 피드 조회 실패: {exc}", file=sys.stderr)
        return None
    return sum(1 for i in items if kst_day(i.get("published_at")) == day)


def validate(pack):
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    comments = [c for b in pack["bundles"] for c in b["payload"]["comments"]]
    registered = {x["external_id"] for x in
                  json.loads((REPO / "data" / "personas.json").read_text(encoding="utf-8"))["personas"]}
    ids = [x["external_id"] for x in posts] + [c["external_id"] for c in comments]
    if len(set(ids)) != len(ids):
        errs.append("external_id 중복")
    for key in ("published_at", "title"):
        vals = [x[key] for x in posts]
        if len(set(vals)) != len(vals):
            errs.append(f"{key} 중복")
    order = [b["payload"]["complex_external_id"] for b in pack["bundles"]]
    for a, b in zip(order, order[1:]):
        if a == b:
            errs.append(f"같은 단지 글이 연달아 나간다: {a}")
    banned = BAN_STEER + BAN_JUDGE + BAN_VAGUE + [w for ws in BANNED.values() for w in ws]
    for b in pack["bundles"]:
        x, a = b["payload"]["post"], b["_asof"]
        eid = x["external_id"]
        cm = [c["body"] for c in b["payload"]["comments"]]
        text = "\n".join([x["title"], x["body"]] + cm)
        for u in a["uses"]:
            if u > a["day"]:
                errs.append(f"발표 전 날짜에 인용: {eid} ← {u}")
        if x["published_at"] < a["embargo"]:
            errs.append(f"보도 시각 전 게시: {eid}")
        if not DISCLOSE.search(x["body"].split("\n\n")[0]):
            errs.append(f"첫 문단에 계산 시점 공개 없음: {eid}")
        scrub = DISCLOSE.sub("", text)
        for m in DATE_IN_TEXT.finditer(scrub):
            if f"2026-{int(m.group(1)):02d}-{int(m.group(2)):02d}" > a["day"]:
                errs.append(f"글 날짜 이후 날짜 '{m.group()}': {eid}")
        if "발표일 기준으로 기록" not in x["source_note"] or "계산" not in x["source_note"]:
            errs.append(f"확인 기준에 계산 시점 없음: {eid}")
        for w in banned:
            if w in text:
                errs.append(f"금지 표현 '{w}': {eid}")
        if OWN_HOME.search(text) or EXPERIENCE_TONE.search(text):
            errs.append(f"경험 어투: {eid}")
        if RELATIVE_TIME.search(text):
            errs.append(f"시점 의존 표현 '{RELATIVE_TIME.search(text).group()}': {eid}")
        je = josa_errors(text) + [m.group() for m in BAD_PCT_JOSA.finditer(text)]
        if je:
            errs.append(f"조사 {je[:3]}: {eid}")
        if "**" in text:
            errs.append(f"마크다운: {eid}")
        if not x["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {eid}")
        if not TRANSITION.search(x["body"]):
            errs.append(f"전환문 없음: {eid}")
        for need in NEED:
            if need not in x["body"]:
                errs.append(f"'{need}' 없음: {eid}")
        if mono_run(x["body"]) >= MONO_RUN:
            errs.append(f"문말 단조 {mono_run(x['body'])}: {eid}")
        if len(x["title"]) > MAX_TITLE:
            errs.append(f"제목 {len(x['title'])}자: {eid}")
        if x["published_at"] > NOW:
            errs.append(f"미래 시각: {eid}")
        if x["persona_external_id"] not in registered:
            errs.append(f"미등록 페르소나: {eid}")
        for c in b["payload"]["comments"]:
            if c["persona_external_id"] not in registered or c["persona_external_id"].startswith("adv-"):
                errs.append(f"댓글 페르소나: {c['external_id']}")
            if c["persona_external_id"] == x["persona_external_id"]:
                errs.append(f"자기 글 댓글: {c['external_id']}")
            if AI_COMMENT_ASK.search(c["body"]):
                errs.append(f"댓글 행동 요청: {c['external_id']}")
    bodies = [c["body"] for c in comments]
    if len(set(bodies)) != len(bodies):
        errs.append("댓글 본문 중복")
    return errs


def main():
    ap = argparse.ArgumentParser(description="AI 예측 장부 소급 기록")
    ap.add_argument("--ignore-cap", action="store_true")
    args = ap.parse_args()
    pack = build(args.ignore_cap)
    errs = validate(pack)
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    for b in pack["bundles"]:
        b.pop("_asof")
    OUT.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for b in pack["bundles"]:
        x = b["payload"]["post"]
        print(f"  {x['published_at'][:16]}  {b['payload']['complex_external_id']:24}{len(x['title']):>3}  {x['title']}")
    print(f"\n글 {len(pack['bundles'])}편 · 댓글 {sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
