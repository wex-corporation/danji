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


def build(pub, ignore_cap):
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
    ts = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    while ts.minute % 5 == 0:          # 시차 규칙(11/3): 분이 5의 배수가 아니게. 지난 시각으로만 당긴다
        ts -= timedelta(minutes=1)
    published_at = ts.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    if published_at[:10] != pub:
        raise SystemExit(f"발표일({pub})과 오늘({published_at[:10]})이 다르다. 실시간 회차는 발표 당일에만 낸다")
    live = B.published_today(x["home"], pub)
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
                                "규칙은 8~10월 결과가 나온 뒤 정했다 · 구 단위 지수이며 단지 값이 아닙니다"),
                "sources": [{"label": f"한국부동산원 주간 아파트가격 동향 {md(pub)} 발표 (확인 {now.strftime('%Y. %-m. %-d.')})",
                             "url": w["source_url"], "publisher": "한국부동산원"}],
                "published_at": published_at, "status": "published",
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
    args = ap.parse_args()
    pack = build(args.pub, args.ignore_cap)
    errs = validate(pack)
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    pack.pop("_embargo")
    out = REPO / "content" / f"forecast-weekly-{args.pub}.json"
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    x = pack["bundles"][0]["payload"]["post"]
    print(f"  {x['published_at']}  {pack['bundles'][0]['payload']['complex_external_id']}  {len(x['title'])}자  {x['title']}")
    print(f"자체 검증 통과 → {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
