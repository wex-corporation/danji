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
