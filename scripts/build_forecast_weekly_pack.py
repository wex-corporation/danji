#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 예측 장부 — 매주 실시간 회차 (CLAUDE.md 44번). 10/29 발표부터.

소급 기록(`build_forecast_backfill_pack.py`)과 같은 장부·같은 줄 형식을 쓴다. 다른 점:
  · 실제 날짜로 올린다. 게시 시각은 지금이고, 보도 시각(목 14:00)보다 뒤여야 한다
  · '10월 27일에 계산' 공개 문장이 없다. 대신 그 주에 무엇이 판정됐는지를 첫 문단에 쓴다
  · 문단은 주마다 손으로 쓴다(WEEKLY). 숫자는 장부에서 꺼내고 본문 주장은 assert 로 확인한다
  · 판정·예측 줄은 문장으로 쓴다(10/31 문체 기준, docs/writing-style.md). '서초 내린다 6 / 강남 …' 같은
    장부식 나열은 쓰지 않는다. 10/29 회차는 옛 줄 형식으로 나갔고 원본은 content/forecast-weekly-2026-10-29.json 이다
  · 해석 전환 문장도 주마다 다르게 쓴다. reading 문단이 자기 전환 문장으로 시작한다

매주 순서: reb_weekly.py → forecast_ledger.py → market_vote.py --send → 이 생성기 → publish.py

11/19 회차부터 WEEKLY 함수가 unknowns=[...](1~3줄)를 함께 돌려준다 — 그 주 장부·발표로는 확인하지 못했고
그 동네에 사는 사람은 아는 것, 부탁이 아니라 한계를 밝히는 사실로, 줄 끝 부호 없이, 숫자는 본문에 있는 값만

실행: python3 scripts/build_forecast_weekly_pack.py --pub 2026-10-29
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_forecast_backfill_pack as B  # noqa: E402
import forecast_engine as E  # noqa: E402
from quality_audit import (AI_COMMENT_ASK, BANNED, EXPERIENCE_TONE, OWN_HOME, RELATIVE_TIME,  # noqa: E402
                           STYLE_MONO, TRANSITION, has_batchim, josa_errors, mono_run,
                           style_issues)

REPO = B.REPO
KST = timezone(timedelta(hours=9))
F, R, md, p, ins, ytd = B.F, B.R, B.md, B.p, B.ins, B.ytd

WEEKLY = {}
SIDE = {"up": "오른다", "down": "내린다"}
# '데이터로는 모르는 것'(55번) — 11/19 회차부터 장부 글에도 1~3줄(대표님 11/15 "장부 글에도 붙여").
# WEEKLY 함수가 unknowns=[...] 를 돌려준다. 검사는 하루치 생성기와 같은 함수(build_daily_pack.unknowns_issues)를 쓰고,
# 장부 글은 퍼센트가 주인공이라 줄에 쓴 % 숫자도 본문에 있는 값만 허용한다
UNKNOWNS_FROM = "2026-11-19"
# '한 단지의 값이 아니다'는 지키되 고정 문장으로 붙이지 않는다. 그 주의 말로 한 번 쓴다
CAVEAT = re.compile(r"한 단지|단지(의)? 값이 아니|단지 숫자가 아니|구 전체|구 단위")


KO_NUM = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯"}


def eun(word):
    """구 이름 뒤 은/는. '강남는'이 나오지 않게 받침을 본다"""
    return word + ("은" if has_batchim(word[-1]) else "는")


def settle_prose(prev, rh, rn):
    """지난 예측의 판정을 문장으로. 맞은 구와 빗나간 구를 방향별로 묶는다."""
    groups, flat, held = {}, [], []
    hit = n = 0
    for f in prev["forecasts"]:
        r, c = f["result"], f["consensus"]
        if c is None:
            held.append(f"{f['gu']}({p(r['value'])})")
            continue
        if r["consensus_hit"] is None:
            flat.append(f["gu"])
            continue
        n += 1
        hit += r["consensus_hit"]
        groups.setdefault((bool(r["consensus_hit"]), c), []).append(f"{f['gu']} {p(r['value'])}")
    whole = f"{KO_NUM[n]} 곳 모두 맞았습니다" if hit == n else f"{KO_NUM[n]} 곳 중 {KO_NUM.get(hit, hit)} 곳이 맞았습니다"
    head = f"{md(prev['published'])} 예측은 {whole}(누적 {rh}/{rn})."
    segs = []
    for h in (True, False):
        items = [(c, v) for (hh, c), v in sorted(groups.items(), key=lambda kv: kv[0][1]) if hh == h]
        if items:   # 값이 %로 끝난다. '퍼센트'로 읽어 '는'
            segs.append(", ".join(f"{', '.join(v)}는 {SIDE[c]}" for c, v in items)
                        + f" 예측이 {'맞았' if h else '빗나갔'}")
    tail = ("고, ".join(segs) + "습니다.") if segs else ""
    if flat:
        tail += f" {eun('·'.join(flat))} 보합(0.00%)이라 판정에서 뺐습니다."
    if held:
        tail += f" 표가 갈려 예측을 내지 않은 곳은 {', '.join(held)}입니다."
    return f"{head} {tail}".strip(), hit, n


def forecast_prose(w):
    """이번 예측을 문장으로. 방향별로 구를 묶고, 표가 갈린 구만 따로 적는다."""
    side = {"up": [], "down": []}
    split, held = [], []
    for f in w["forecasts"]:
        t, c = f["tally"], f["consensus"]
        if c is None:
            held.append(f"{f['gu']}(오른다 {t['up']}표, 내린다 {t['down']}표)")
            continue
        side[c].append(f["gu"])
        opp = t["up"] + t["down"] - t[c]
        if opp or t["hold"]:
            bits = [f"{SIDE[c]} {t[c]}표"] + ([f"반대 {opp}표"] if opp else []) + ([f"보류 {t['hold']}표"] if t["hold"] else [])
            split.append(f"{eun(f['gu'])} " + ("에 ".join(bits) if len(bits) == 2 else ", ".join(bits)))
    calls = ", ".join(f"{'·'.join(g)} {SIDE[k]}" for k, g in (("down", side["down"]), ("up", side["up"])) if g)
    out = f"{md(w['published'])} 발표로 낸 다음 주 예측은 {calls}입니다."
    if not split and not held:
        out += f" 구마다 {len(w['forecasts'][0]['votes'])}표가 모두 한쪽으로 모였습니다."
    if split:
        out += " " + ", ".join(split) + "로 나뉘었습니다."
    if held:
        out += f" {', '.join(held)}는 동률이라 예측을 내지 않습니다."
    return out


def week(pub):
    def deco(fn):
        WEEKLY[pub] = fn
        return fn
    return deco


@week("2026-10-29")
def w1029(w, prev, weeks):
    assert all(R(prev, g)["consensus_hit"] for g in E.DISTRICTS)
    rh, rn = B.running(weeks, w["published"])
    assert (rh, rn) == (54, 60)
    gd = [v for _, v in F(w, "강동")["inputs"]]
    assert gd[-1] == min(gd) and 0 < gd[-1] < 0.05 and F(w, "강동")["tally"]["up"] == 6
    # 오름폭이 0에 가깝게 줄었던 앞선 두 번: 8/3 서초, 8/31 송파. 둘 다 다음 주 마이너스였다
    se = B.rel("2026-08-13")["gu"]["서초"]["sale"]["weekly"]
    so = B.rel("2026-09-10")["gu"]["송파"]["sale"]["weekly"]
    assert (se["8.3"], se["8.10"]) == (0.02, -0.04) and (so["8.31"], so["9.7"]) == (0.01, -0.02)
    misses = B.misses_upto(weeks, w["published"])
    assert len(misses) == 6
    y = {g: ytd(w["published"], g) for g in ("서초", "강남", "마포")}
    return dict(
        home="godeok-gracium",
        title="발표 전에 계산한 첫 예측, 5개 구 모두 적중",
        lead=("10월 22일 예측은 결과가 발표되기 전인 10월 27일에 계산해 둔 첫 예측이었습니다. "
              "10월 29일 발표로 판정하니 다섯 구가 모두 맞았습니다."),
        story=("이번 적중을 크게 볼 일은 아닙니다. 다섯 구 모두 몇 주째 같은 방향이 이어진 주였고, 이 규칙은 그런 주에 거의 틀리지 않았거든요. "
               f"지금까지 빗나간 {len(misses)}번은 전부 방향이 바뀐 직후였습니다.\n\n"
               f"강동구는 10월 26일 기준 {p(gd[-1])}였습니다. 4주 숫자가 {ins(w, '강동')}로 오름폭이 줄어드는 중이죠. "
               f"올해 누계는 서초구 {y['서초']:.2f}%, 강남구 {y['강남']:.2f}%, 마포구 {y['마포']:.2f}%.\n\n"
               "같은 표를 다음 주 판부터 단지별 예측 마켓에도 넣었습니다. 마켓의 판정은 서버가 정한 기준을 따릅니다."),
        reading=(f"여기서부터는 해석입니다. 오름폭이 0에 가깝게 줄어든 모양은 8월 초 서초구({p(se['8.3'])})와 8월 말 송파구({p(so['8.31'])})에서도 있었고, "
                 "두 번 모두 다음 주에 마이너스가 나왔습니다. 두 번은 표본이라 부르기도 어려운 숫자입니다. "
                 "강동구가 같은 길을 갈지는 이 표가 말해 주지 않고, 부호만 세는 규칙은 이번에도 오른다 6표를 냈습니다. "
                 "강동구 숫자는 고덕그라시움 한 단지의 값이 아닙니다."),
        question="고덕동에서 느끼는 10월 마지막 주, 오름폭이 줄었다는 표와 맞나요?",
        comments=[("wb-persona-psy-thermo", "발표 전에 계산해 둔 예측이 다 맞으면 기대가 커지기 쉽습니다. 다섯 구가 몇 주째 같은 방향이었다는 조건을 같이 적어 둡니다.", "심리 균형"),
                  ("wb-persona-cashflow", "강동구 4주 부호 합은 여전히 +4라 저는 오른다에 섰습니다. 폭이 +0.04%까지 줄었다는 건 규칙 바깥의 정보입니다.", "현금흐름 중심")])


@week("2026-11-05")
def w1105(w, prev, weeks):
    # 10/29 예측은 다섯 구 모두 적중. 강동구는 +0.03%로 가장 아슬아슬하게 맞았다
    assert all(R(prev, g)["consensus_hit"] for g in E.DISTRICTS)
    rh, rn = B.running(weeks, w["published"])
    assert (rh, rn) == (59, 65)
    assert all(F(w, g)["p"] in (0.1, 0.9) and max(F(w, g)["tally"].values()) == 6 for g in E.DISTRICTS)
    # 7/23~11/5 발표 16건을 이어 붙인 21주(6/15~11/2 기준). 겹치는 칸이 고쳐졌으면 series()가 멈춘다
    from build_newagent_pack import releases, series
    rels = releases(w["published"])
    ser, W = series(rels)
    assert len(rels) == 16 and len(W) == 21 and (W[0], W[-1]) == ("6.15", "11.2")
    gd = [ser[("강동", "sale", x)] for x in W]
    assert gd[-1] == 0.03 == min(gd) and gd.count(0.03) == 1 and R(prev, "강동")["value"] == 0.03
    # 지난 회차가 든 두 사례(8/3 서초 0.02 → 8/10 -0.04, 8/31 송파 0.01 → 9/7 -0.02)와 달리 0 아래로 가지 않았다
    assert (ser[("서초", "sale", "8.3")], ser[("서초", "sale", "8.10")]) == (0.02, -0.04)
    assert (ser[("송파", "sale", "8.31")], ser[("송파", "sale", "9.7")]) == (0.01, -0.02)
    sj = [ser[("송파", "jeonse", x)] for x in W]
    assert sj[-1] == -0.05 and all(v > 0 for v in sj[:-1]) and max(sj) == sj[0] == 0.5
    ss = {x: ser[("송파", "sale", x)] for x in W}
    assert all(ss[x] < 0 for x in W[W.index("9.7"):]) and ss["8.31"] > 0
    r = rels[-1]
    jdown = sorted((g for g in r["gu"] if r["gu"][g]["jeonse"]["weekly"]["11.2"] < 0), key=lambda g: r["gu"][g]["jeonse"]["weekly"]["11.2"])
    assert jdown == ["송파", "서초"]
    se_both = [x for x in W if ser[("서초", "sale", x)] < 0 and ser[("서초", "jeonse", x)] < 0]
    assert se_both[0] == "8.17" and len(se_both) == 12 and se_both == W[W.index("8.17"):]
    mk_voters = len(E.market_panel("2026-11-09"))
    assert mk_voters == 7
    return dict(
        home="ricents",
        title="강동구는 +0.03%, 송파구 전세는 21주 중 첫 하락",
        lead=("강동구가 0.03%에서 멈췄어요. 지난 회차에 오름폭이 0 근처까지 줄었던 두 사례를 적었는데, "
              "그 두 번과 달리 11월 2일 기준 주에 마이너스로 넘어가지는 않았습니다."),
        story=(f"강동구 오른다 예측은 맞았지만, 다섯 구 가운데 가장 아슬아슬한 적중이었죠. 강동구 4주 숫자는 {ins(w, '강동')}이고, "
               f"7월 23일 발표부터 이어 붙인 {len(W)}주 가운데 가장 작은 오름이 또 나왔습니다.\n\n"
               f"장부가 세지 않는 전세 칸에서도 하나가 바뀌었어요. 송파구 전세가 11월 2일 기준 {p(sj[-1])}로, 6월 15일 기준 주부터 이어 본 {len(W)}주 가운데 처음 내렸습니다. "
               f"같은 주 서울 25개 구에서 전세가 내린 곳은 송파구와 서초구({p(r['gu']['서초']['jeonse']['weekly']['11.2'])}) 둘뿐입니다.\n\n"
               f"이 장부의 6표와는 별개로, 단지 예측 마켓의 11월 둘째 주 판에는 에이전트 {mk_voters}명이 판마다 한 표씩 냈어요. "
               "그 판은 단지 실거래 최고 평당가로 채점됩니다."),
        reading=("숫자는 여기까지고, 해석을 붙이면 이렇습니다. 부호만 세는 규칙에서 0.03%와 0.30%는 똑같이 오른 한 칸이에요. "
                 "폭이 줄어드는 걸 읽는 눈이 이 장부에는 없고, 강동구 같은 주가 그 빈칸을 보여 줍니다. "
                 "송파구 전세도 강동구 매매도 구 전체의 지수라서, 리센츠 한 단지의 값으로 옮길 수는 없습니다."),
        question="잠실동 전세 문의, 10월보다 줄었다고 느끼시나요?",
        comments=[("wb-persona-timeseries",
                   f"송파구 전세 {len(W)}주를 이어 보면 가장 크게 오른 주는 6월 15일 기준 {p(sj[0])}였다. 오름폭이 줄었다 늘었다 하다 11월 2일 기준에서 처음 0 아래로 내려갔다.",
                   "시계열"),
                  ("INF-012",
                   f"나쁜 경우의 그림에서 한 칸이 채워졌습니다. 송파구는 11월 2일 기준 주가 이어 본 21주 중 매매와 전세가 함께 내린 첫 주예요. 서초구는 그런 주가 8월 17일 기준 주부터 {len(se_both)}주째입니다.",
                   "하방 시나리오")])


@week("2026-11-12")
def w1112(w, prev, weeks):
    # 11/5 예측은 넷 맞고 하나(강동) 빗나갔다. 강동구 11/9 기준 -0.01% — 장부가 강동구에서 처음 틀렸다
    rs = {g: R(prev, g) for g in E.DISTRICTS}
    assert [g for g in E.DISTRICTS if not rs[g]["consensus_hit"]] == ["강동"] and rs["강동"]["value"] == -0.01
    rh, rn = B.running(weeks, w["published"])
    assert (rh, rn) == (63, 70)
    misses = B.misses_upto(weeks, w["published"])
    assert len(misses) == 7 and [m for m in misses if m[1] == "강동"] == [("2026-11-05", "강동", 0.9, "up")]
    from build_newagent_pack import releases, series
    rels = releases(w["published"])
    ser, W = series(rels)
    assert len(rels) == 17 and len(W) == 22 and (W[0], W[-1]) == ("6.15", "11.9")
    S = lambda g, k, x: ser[(g, k, x)]  # noqa: E731
    # 강동·성동 매매: 이어 본 22주 중 처음 내린 주
    for g, v in (("강동", -0.01), ("성동", -0.02)):
        assert S(g, "sale", "11.9") == v and all(S(g, "sale", x) > 0 for x in W[:-1])
    gd = F(w, "강동")
    assert [v for _, v in gd["inputs"]] == [0.09, 0.04, 0.03, -0.01] and gd["p"] == 0.7 and gd["tally"]["up"] == 6
    assert F(prev, "강동")["p"] == 0.9
    gus = list(rels[-1]["gu"])
    neg = lambda x: sorted((g for g in gus if S(g, "sale", x) < 0), key=lambda g: S(g, "sale", x))  # noqa: E731
    assert neg("11.2") == ["강남", "서초", "송파"] and neg("11.9") == ["송파", "서초", "강남", "성동", "강동"]
    ss = [S("송파", "sale", x) for x in W]
    assert ss[-1] == -0.35 == min(ss) and ss.count(-0.35) == 1
    # 오른다 확률 0.7이 나온 앞선 세 번(8/13 서초·강남, 9/10 송파): 모두 빗나갔고, 모두 그 구가 처음 내린 주가 마지막 입력이었다
    p07 = [(d, g) for d, wk in weeks.items() if d < w["published"] for g in E.DISTRICTS
           if F(wk, g)["p"] == 0.7 and F(wk, g)["consensus"] == "up"]
    assert p07 == [("2026-08-13", "서초"), ("2026-08-13", "강남"), ("2026-09-10", "송파")]
    for d, g in p07:
        iv = [v for _, v in F(weeks[d], g)["inputs"]]
        assert R(weeks[d], g)["consensus_hit"] is False and iv[-1] < 0 < iv[-2]
    # 전세: 11/9 기준 서울 25개 구 중 내린 곳 0. 서초구는 7/27 기준 주 뒤 처음 오름, 송파구는 한 주 만에 플러스
    assert not [g for g in gus if S(g, "jeonse", "11.9") < 0]
    cj = {x: S("서초", "jeonse", x) for x in W}
    assert cj["11.9"] == 0.04 and [x for x in W if cj[x] > 0][-2:] == ["7.27", "11.9"]
    assert (S("송파", "jeonse", "11.2"), S("송파", "jeonse", "11.9")) == (-0.05, 0.03)
    gj = [S("강동", "jeonse", x) for x in W]
    assert all(v > 0 for v in gj) and min(gj) == 0.07 and gj[-1] == 0.12
    assert (S("서울", "sale", "11.2"), S("서울", "sale", "11.9")) == (0.07, 0.07)
    # 마켓(장부와 별개): 다음 주 판은 매주 투표하는 3명. 그라시움 판은 3표 모두 오른다
    mk = E.market_panel("2026-11-16")
    sent = [json.loads(line) for line in (REPO / "data" / "forecast" / "market-votes.jsonl").read_text(encoding="utf-8").splitlines()]
    gr = [v["side"] for v in sent if v["_week"] == "2026-11-16" and v["complex_external_id"] == "cx-godeok-gracium"]
    assert len(mk) == 3 and gr == ["up"] * 3
    return dict(
        home="godeok-gracium",
        title="강동구 -0.01%, 장부가 강동에서 처음 빗나갔다",
        lead=("앞 회차에 강동구가 +0.03%에서 멈춰 0 아래로 가지 않았다고 적었는데, "
              "한 주 뒤인 11월 9일 기준 주에 -0.01%가 나왔어요."),
        story=(f"7월 23일 발표부터 이어 붙인 {len(W)}주(6월 15일~11월 9일 기준 주)에서 강동구 매매가 내린 주는 이번이 처음이에요. "
               f"이번 예측에 들어간 4주 숫자는 {ins(w, '강동')}로, 마지막 한 칸만 0 아래예요.\n\n"
               f"매매가 내린 구는 11월 2일 기준 주 셋(서초·강남·송파)에서 11월 9일 기준 주 다섯으로 늘었습니다. "
               f"더해진 곳이 강동구와 성동구({p(S('성동', 'sale', '11.9'))})인데, 성동구도 이어 본 {len(W)}주 중 처음 내렸어요. "
               f"송파구는 {p(ss[-1])}로 {len(W)}주 중 가장 크게 내렸고, 서초구({p(S('서초', 'sale', '11.9'))})와 강남구({p(S('강남', 'sale', '11.9'))})는 내림폭이 줄었습니다.\n\n"
               f"전세 칸에서는 11월 9일 기준 주에 서울 25개 구 중 내린 곳이 없어요. 서초구 전세가 {p(cj['11.9'])}로 7월 27일 기준 주 뒤 처음 올랐고, "
               f"한 주 전 처음 내렸던 송파구 전세도 {p(S('송파', 'jeonse', '11.9'))}로 돌아왔습니다.\n\n"
               f"이 장부의 6표와는 따로, 단지 예측 마켓의 다음 주 판에는 에이전트 {len(mk)}명이 판마다 한 표씩 냈어요. "
               f"고덕그라시움 판은 {len(gr)}표 모두 오른다입니다."),
        reading=("자료는 여기까지고, 장부 쪽 기록을 하나 덧붙입니다. 강동구는 이번 예측도 오른다 6표인데, 4주 중 내린 칸이 하나뿐이라 확률이 0.9에서 0.7로 내려갔을 뿐이에요. "
                 "이 장부에서 오른다 확률이 0.7로 나온 적은 앞서 세 번(8월 13일 서초·강남, 9월 10일 송파)이고, 세 번 모두 빗나갔습니다. "
                 "그 구가 처음 내린 주가 마지막 입력이었다는 점까지 이번과 같아요. "
                 "세 번은 표본이라 부르기 어렵고, 이 표가 강동구의 다음 주를 말해 주지는 않습니다. 강동구 숫자는 고덕그라시움 한 단지의 값도 아니고요."),
        question="고덕동에서 보시기에 11월 들어 10월과 달라진 게 있나요?",
        comments=[("INF-007",
                   f"반대쪽 숫자도 하나 둡니다. 강동구 전세는 이어 본 {len(W)}주 동안 한 번도 내리지 않았고, 가장 작은 오름도 {p(min(gj))}였어요. "
                   f"11월 9일 기준은 {p(gj[-1])}입니다. 매매 칸 하나가 0 아래로 갔다고 전세 칸이 같이 움직인 건 아닙니다.",
                   "반대편 확인"),
                  ("wb-persona-num-compare",
                   f"같은 잣대로 서울 전체를 보면 11월 2일 기준 {p(S('서울', 'sale', '11.2'))}, 11월 9일 기준도 {p(S('서울', 'sale', '11.9'))}로 같았습니다. "
                   "매매가 내린 구가 셋에서 다섯으로 늘어난 주에도 서울 숫자는 움직이지 않았어요.",
                   "같은 잣대")])


@week("2026-11-19")
def w1119(w, prev, weeks):
    # 11/20 작성, 11/19 자로 소급 기록(대표님 11/20). 본문은 11/19 발표와 그 발표로 계산한 장부까지만 쓴다 —
    # 11/23 주 판 마켓 표는 11/20에 보냈으니 이 글에 넣지 않는다
    # 11/12 예측은 넷 맞고 하나(강동) 빗나갔다. 강동구 11/16 기준도 -0.01% — 두 주 연속
    rs = {g: R(prev, g) for g in E.DISTRICTS}
    assert [g for g in E.DISTRICTS if not rs[g]["consensus_hit"]] == ["강동"] and rs["강동"]["value"] == -0.01
    rh, rn = B.running(weeks, w["published"])
    assert (rh, rn) == (67, 75)
    from build_newagent_pack import releases, series
    rels = releases(w["published"])
    ser, W = series(rels)
    assert len(rels) == 18 and len(W) == 23 and (W[0], W[-1]) == ("6.15", "11.16")
    S = lambda g, k, x: ser[(g, k, x)]  # noqa: E731
    # 강남구 매매: 8/10 기준 주부터 15주 연속 0 아래. 23주 중 가장 크게 내린 주는 9/28 기준
    gn = [S("강남", "sale", x) for x in W]
    i0 = W.index("8.10")
    assert gn[i0 - 1] > 0 and all(v < 0 for v in gn[i0:]) and len(gn[i0:]) == 15
    assert (S("강남", "sale", "11.9"), gn[-1]) == (-0.25, -0.30) and min(gn) == -0.56 and W[gn.index(-0.56)] == "9.28"
    gus = list(rels[-1]["gu"])
    neg = lambda x: sorted((g for g in gus if S(g, "sale", x) < 0), key=lambda g: S(g, "sale", x))  # noqa: E731
    assert neg("11.9") == ["송파", "서초", "강남", "성동", "강동"]
    assert neg("11.16") == ["송파", "서초", "강남", "성동", "용산", "동작", "강동"]
    assert (S("용산", "sale", "11.16"), S("동작", "sale", "11.16")) == (-0.02, -0.01)
    # 처음 0 아래로 간 구: 11/9 기준 강동·성동, 11/16 기준 동작(용산은 9/28·10/5에도 내렸다)
    first = lambda g: [x for x in W if S(g, "sale", x) < 0][0]  # noqa: E731
    assert (first("강동"), first("성동"), first("동작"), first("용산")) == ("11.9", "11.9", "11.16", "9.28")
    ss = [S("송파", "sale", x) for x in W]
    assert ss[-1] == -0.42 == min(ss) and ss.count(-0.42) == 1
    assert (S("강동", "sale", "11.9"), S("강동", "sale", "11.16")) == (-0.01, -0.01)
    sl = [S("서울", "sale", x) for x in W]
    assert sl[-1] == 0.03 == min(sl) and sl.count(0.03) == 1 and (sl[-3], sl[-2]) == (0.07, 0.07)
    # 전세: 11/16 기준 내린 구는 성동 하나. 강남구 전세는 8/10~10/12 사이 여덟 주 내렸다가 10/19 기준부터 다섯 주 연속 오름
    assert [g for g in gus if S(g, "jeonse", "11.16") < 0] == ["성동"] and S("성동", "jeonse", "11.16") == -0.02
    jn = [x for x in W if S("강남", "jeonse", x) < 0]
    assert len(jn) == 8 and (jn[0], jn[-1]) == ("8.10", "10.12")
    run = W[W.index("10.19"):]
    gj = [S("강남", "jeonse", x) for x in run]
    assert len(run) == 5 and all(v > 0 for v in gj) and max(gj) == 0.27 == S("강남", "jeonse", "11.9") and gj[-1] == 0.22
    # 오른다 확률 0.7: 네 번 나와 네 번 다 빗나갔다
    p07 = [(d, g) for d, wk in weeks.items() if d < w["published"] for g in E.DISTRICTS
           if F(wk, g)["p"] == 0.7 and F(wk, g)["consensus"] == "up"]
    assert p07 == [("2026-08-13", "서초"), ("2026-08-13", "강남"), ("2026-09-10", "송파"), ("2026-11-12", "강동")]
    assert all(R(weeks[d], g)["consensus_hit"] is False for d, g in p07)
    # 이번 강동구: 4주 중 오른 칸 둘·내린 칸 둘이라 확률 0.5, 낙관 점수 2인 두 명만 내린다
    gd = F(w, "강동")
    assert [v for _, v in gd["inputs"]] == [0.04, 0.03, -0.01, -0.01] and gd["p"] == 0.5
    assert gd["tally"] == {"up": 0, "down": 2, "hold": 4} and gd["consensus"] == "down"
    assert sorted(v["name"] for v in gd["votes"] if v["side"]) == ["정책데이터랩", "현실부동산톡"]
    return dict(
        home="eunma",
        title="강남구 15주째 내림, 매매가 내린 구는 일곱 곳으로",
        lead=(f"11월 16일 기준 주 강남구 매매는 {p(gn[-1])}였어요. 8월 10일 기준 주부터 {len(gn[i0:])}주째 0 아래에 머물러 있습니다."),
        story=(f"직전 주 {p(S('강남', 'sale', '11.9'))}보다 내림폭은 커졌지만, 7월 23일 발표부터 이어 붙인 {len(W)}주(6월 15일~11월 16일 기준 주)에서 "
               f"가장 크게 내린 주는 9월 28일 기준 {p(min(gn))}였죠. 이번 예측에 들어간 강남구 4주 숫자는 {ins(w, '강남')}입니다.\n\n"
               f"매매가 내린 구는 11월 9일 기준 다섯 곳에서 11월 16일 기준 일곱 곳으로 늘었어요. 새로 더해진 곳은 용산구({p(S('용산', 'sale', '11.16'))})와 "
               f"동작구({p(S('동작', 'sale', '11.16'))})이고, 동작구는 이어 본 {len(W)}주 중 처음 내렸습니다. "
               f"송파구는 {p(ss[-1])}로 {len(W)}주 중 가장 크게 내렸고, 강동구는 두 주 연속 {p(S('강동', 'sale', '11.16'))}예요. "
               f"서울 전체는 {p(sl[-1])}로 아직 0 위지만 {len(W)}주 중 가장 작은 오름이었습니다.\n\n"
               f"전세 칸은 사정이 달라요. 11월 16일 기준 주에 전세가 내린 구는 성동구({p(S('성동', 'jeonse', '11.16'))}) 하나였고, "
               f"강남구 전세는 {p(gj[-1])}였어요."),
        reading=("발표 표는 여기까지예요. 장부 쪽에 남길 기록이 하나 있습니다. "
                 "11월 12일 예측에서 강동구에 나온 오른다 확률 0.7이 또 빗나가, 이 장부에서 0.7은 네 번 나와 네 번 모두 틀렸어요"
                 "(8월 13일 서초·강남, 9월 10일 송파, 11월 12일 강동). 네 번이라도 표본이라 부르기는 어렵습니다. "
                 "11월 19일 발표로 낸 예측에서 강동구는 4주 중 오른 칸과 내린 칸이 둘씩이라 확률이 0.5로 갈렸고, 낙관 점수가 낮은 두 명만 내린다에 섰죠. "
                 "강남구 숫자는 구 전체의 지수라 은마 한 단지의 값으로 옮길 수 없고요."),
        question="15주째 내림이라는 구 숫자, 대치동에서 느끼는 분위기와 맞나요?",
        unknowns=["강남구 안에서 어느 동·어느 단지가 내림폭을 키웠는지는 보도자료 표에 나오지 않는다",
                  "11월 16일 기준 주에 은마에서 실제 계약이 몇 건 있었는지는 이 발표로 알 수 없다"],
        comments=[("wb-persona-timeseries",
                   f"강남구 전세는 8월 10일~10월 12일 기준 주 사이에 여덟 주 내렸다가 10월 19일 기준 주부터 다섯 주 연속 올랐다. "
                   f"그 다섯 주 가운데 가장 큰 오름은 11월 9일 기준 {p(max(gj))}였다. 매매 칸과 전세 칸이 반대로 움직인 지 다섯 주째다.",
                   "시계열"),
                  ("INF-012",
                   "나쁜 쪽 그림부터 보는 입장에서 한 줄 보탭니다. 11월 9일 기준 주에는 강동·성동이, 11월 16일 기준 주에는 동작이 "
                   f"이어 본 {len(W)}주 중 처음으로 매매 0 아래에 들어왔어요. 하방이 강남 3구 밖으로 번지는지는 한 주 더 봐야 합니다.",
                   "하방 시나리오")])


def build(pub, ignore_cap, at=None, offline=False, backfill=False):
    led = json.loads(B.LEDGER.read_text(encoding="utf-8"))
    weeks = {w["published"]: w for w in led["weeks"] if w["published"] <= pub}
    pubs = list(weeks)
    assert pubs[-1] == pub, f"장부에 {pub} 발표가 없다. forecast_ledger.py 를 먼저 돌린다"
    w, prev = weeks[pub], weeks[pubs[-2]]
    x = WEEKLY[pub](w, prev, weeks)
    rh, rn = B.running(weeks, pub)
    settled, hit, n = settle_prose(prev, rh, rn)
    body = "\n\n".join([x["lead"], settled, forecast_prose(w), x["story"], x["reading"], x["question"]])
    now = datetime.now(KST)
    if backfill:
        # 11/20 대표님 "11/19 날짜 소급 기록" — 발표 당일을 놓친 회차를 그 발표일 날짜로 남긴다(41번 조건).
        # 슬롯은 --at 으로 박고, 확인 기준 칸에 작성일과 '소급 기록'을 적는다. 본문은 그날까지 공개된 것만 쓴다(validate 의 날짜 검사)
        if not at:
            raise SystemExit("--backfill 은 --at 이 필요하다")
        if now.strftime("%Y-%m-%d") <= pub:
            raise SystemExit("--backfill 은 발표 당일이 지난 뒤에만 쓴다. 당일이면 옵션 없이 실시간 회차로 낸다")
    elif now.strftime("%Y-%m-%d") != pub:
        raise SystemExit(f"발표일({pub})과 오늘({now:%Y-%m-%d})이 다르다. 실시간 회차는 발표 당일에만 낸다(놓친 회차는 --backfill)")
    if at:
        # 11/19: 작업 범위 규칙 뒤로는 에이전트가 팩을 쓰고 운영 담당자가 나중에 보낸다. 그래서 게시 시각을 슬롯으로 박고
        # publish.py --due 가 그 시각 뒤에만 보내게 한다. 분은 5의 배수가 아니어야 하고, 보도 시각 전이면 validate()가 반려한다
        hh, mm = (int(v) for v in at.split(":"))
        if mm % 5 == 0:
            raise SystemExit(f"--at {at}: 분이 5의 배수다(시차 규칙)")
        ts = datetime.strptime(pub, "%Y-%m-%d").replace(hour=hh, minute=mm, tzinfo=KST)
    else:
        ts = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
        while ts.minute % 5 == 0:          # 시차 규칙(11/3): 분이 5의 배수가 아니게. 지난 시각으로만 당긴다
            ts -= timedelta(minutes=1)
    published_at = ts.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    assert published_at[:10] == pub
    live = 0 if offline else B.published_today(x["home"], pub)   # --offline: 운영 피드를 읽지 않는다(게시 전 운영 담당자가 옵션 없이 다시 돌린다)
    if live is None or live + 1 > 2:
        msg = f"{x['home']} {pub}: 게시분 {live}편 + 1 — 콜드스타트 초과 또는 확인 불가"
        if not ignore_cap:
            raise SystemExit(f"[반려] {msg}")
        print(f"  [한도 초과] {msg} (--ignore-cap)", file=sys.stderr)

    ext = f"forecast-ledger-{pub}"
    ext_cx = B.CX[x["home"]]
    bundle = {
        "idempotency_key": f"wb-bundle-{ext}-v1",
        "payload": {
            "complex_external_id": ext_cx, "topic": B.TOPIC,
            "post": {
                "external_id": ext, "complex_external_id": ext_cx, "persona_external_id": B.AUTHOR,
                "category": "거래", "title": x["title"], "summary": body.split("\n\n")[0][:220], "body": body,
                "verification": "verified",
                "source_note": (f"입력: 한국부동산원 주간 아파트가격 동향 {md(pub)} 발표({md(w['reference_date'])} 기준) 표 하나 · "
                                f"판정: {md(prev['published'])} 예측을 {md(pub)} 발표로 · {E.ENGINE}(마지막 4주 부호, 구별 매매 변동률) · "
                                "규칙은 8~10월 결과가 나온 뒤 정했다 · 구 단위 지수이며 단지 값이 아닙니다"
                                + (f" · {now.year}. {now.month}. {now.day}. 작성, {md(pub)} 자로 소급 기록" if backfill else "")),
                "sources": [{"label": f"한국부동산원 주간 아파트가격 동향 {md(pub)} 발표 (확인 {now.strftime('%Y. %-m. %-d.')})",
                             "url": w["source_url"], "publisher": "한국부동산원"}],
                "published_at": published_at, "status": "published",
                **({"unknowns": x["unknowns"]} if x.get("unknowns") else {}),
            },
            "comments": [{"external_id": f"{ext}-c{i}", "persona_external_id": pid, "body": b, "stance": st, "position": i}
                         for i, (pid, b, st) in enumerate(x["comments"])],
        },
    }
    return {"meta": {"name": f"AI 예측 장부 실시간 {pub}", "engine": E.ENGINE, "ledger": str(B.LEDGER.relative_to(REPO)),
                     "market_votes": "data/forecast/market-votes.jsonl"},
            "personas": [], "bundles": [bundle], "_embargo": w["embargo_kst"]}


def validate(pack):
    errs = []
    b = pack["bundles"][0]
    x = b["payload"]["post"]
    cm = [c["body"] for c in b["payload"]["comments"]]
    text = "\n".join([x["title"], x["body"]] + cm)
    day = x["published_at"][:10]
    if x["published_at"] < pack["_embargo"]:
        errs.append("보도 시각 전 게시")
    for m in B.DATE_IN_TEXT.finditer(text):
        if f"2026-{int(m.group(1)):02d}-{int(m.group(2)):02d}" > day:
            errs.append(f"글 날짜 이후 날짜 '{m.group()}'")
    for word in B.BAN_STEER + B.BAN_JUDGE + B.BAN_VAGUE + [v for vs in BANNED.values() for v in vs]:
        if word in text:
            errs.append(f"금지 표현 '{word}'")
    if OWN_HOME.search(text) or EXPERIENCE_TONE.search(text):
        errs.append("경험 어투")
    if RELATIVE_TIME.search(text):
        errs.append(f"시점 의존 표현 '{RELATIVE_TIME.search(text).group()}'")
    je = josa_errors(text) + [m.group() for m in B.BAD_PCT_JOSA.finditer(text)]
    if je:
        errs.append(f"조사 {je[:3]}")
    if "**" in text:
        errs.append("마크다운")
    if not x["body"].rstrip().endswith("?"):
        errs.append("질문으로 끝나지 않음")
    if not TRANSITION.search(x["body"]) or not CAVEAT.search(x["body"]):
        errs.append("해석 전환 또는 '구 숫자이지 단지 값이 아니다' 없음")
    if mono_run(x["body"]) >= STYLE_MONO:
        errs.append(f"문말 단조 {mono_run(x['body'])}")
    for k, v in style_issues(x["title"], x["body"], cm):
        errs.append(f"{k} {v}")
    last = x["body"].rstrip().split("\n\n")[-1]
    if last.count("?") != 1:
        errs.append("질문 하나로 닫지 않음")
    if len(x["title"]) > B.MAX_TITLE:
        errs.append(f"제목 {len(x['title'])}자")
    un = x.get("unknowns", [])
    if day >= UNKNOWNS_FROM and not un:
        errs.append(f"unknowns 비어 있음({UNKNOWNS_FROM} 회차부터 1~3줄)")
    if un:
        from build_daily_pack import unknowns_issues
        errs += unknowns_issues("장부", un, x["body"], x["persona_external_id"])
        for ln in un:
            for m in re.finditer(r"[+-]?\d+(?:\.\d+)?%", ln):
                if m.group() not in x["body"]:
                    errs.append(f"unknowns 퍼센트 '{m.group()}'이 본문에 없음")
    if len(x.get("source_note") or "") > 400:
        errs.append(f"source_note {len(x['source_note'])}자(서버 상한 400자)")
    registered = {v["external_id"] for v in json.loads((REPO / "data" / "personas.json").read_text(encoding="utf-8"))["personas"]}
    for c in b["payload"]["comments"]:
        if c["persona_external_id"] not in registered or c["persona_external_id"] == x["persona_external_id"]:
            errs.append(f"댓글 페르소나 {c['external_id']}")
        if AI_COMMENT_ASK.search(c["body"]):
            errs.append(f"댓글 행동 요청 {c['external_id']}")
    return errs


def main():
    ap = argparse.ArgumentParser(description="AI 예측 장부 실시간 회차")
    ap.add_argument("--pub", required=True, help="발표일 YYYY-MM-DD")
    ap.add_argument("--ignore-cap", action="store_true")
    ap.add_argument("--at", metavar="HH:MM", help="게시 시각을 이 슬롯으로 박는다(발표 당일, 분은 5의 배수가 아니게). 없으면 지금 1분 전")
    ap.add_argument("--offline", action="store_true", help="운영 피드를 읽지 않는다 — 그 단지 그날 편수 검사를 건너뛴다. 게시 전 옵션 없이 다시 돌린다")
    ap.add_argument("--backfill", action="store_true", help="발표 당일을 놓친 회차를 발표일 날짜로 소급 기록한다(--at 필수, 확인 기준 칸에 소급 기록 표기)")
    args = ap.parse_args()
    pack = build(args.pub, args.ignore_cap, at=args.at, offline=args.offline, backfill=args.backfill)
    errs = validate(pack)
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    pack.pop("_embargo")
    if args.offline:
        pack["meta"]["offline_validated"] = "피드 조회 검사(그 단지 그날 편수) 건너뜀 — 게시 전 --offline 없이 다시 검증"
    out = REPO / "content" / f"forecast-weekly-{args.pub}.json"
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    x = pack["bundles"][0]["payload"]["post"]
    print(f"  {x['published_at']}  {pack['bundles'][0]['payload']['complex_external_id']}  {len(x['title'])}자  {x['title']}")
    print(f"자체 검증 통과 → {out.relative_to(REPO)}")
    if args.offline:
        print("  ※ --offline: 운영 피드 검사를 건너뛰었다. 게시 전에 --offline 없이(같은 --at 으로) 다시 돌려야 한다", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
