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

# 글이 붙는 단지. 같은 날 부동산원 소급 글(41번)이 있는 단지는 피했다 — 서모스탯은 피드로 다시 센다
HOME = {
    "2026-08-06": "eunma", "2026-08-13": "one-bailey", "2026-08-20": "helio-city", "2026-08-27": "ricents",
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
    return (f"이 기록은 {COMPUTED_MD}에 같은 규칙으로 계산해 {md(w['published'])} 자리에 남긴 것입니다. "
            f"입력은 한국부동산원 {md(w['published'])} 발표({md(w['reference_date'])} 기준) 표 하나입니다. "
            "규칙은 기간이 끝난 뒤에 정했으니, 아래 적중은 실력이 아니라 규칙이 이 기간에 맞았는지의 기록입니다.")


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
            parts.append(f"{md(prev['published'])} 예측 판정. {line}. 이번 판정 {hit}/{n}, 누적 {rh}/{rn}.")
        parts.append(f"{md(w['published'])} 예측(다음 주 매매 변동률). {forecast_line(w)}.")
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
                    "source_note": (f"한국부동산원 주간 아파트가격 동향 {'·'.join(md(u) for u in r['uses'])} 발표분 · "
                                    f"{E.ENGINE}(마지막 4주 부호) · {COMPUTED} 계산, 발표일 기준으로 기록 · "
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
