#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""서버 예측 마켓에 AI 페르소나 표를 넣는다 (CLAUDE.md 43·44번).

  입력   data/reb-weekly/releases/ 의 가장 최근 발표 하나 (as-of)
  엔진   scripts/forecast_engine.py — 소급 기록과 같은 규칙이다
  대상   GET /api/v1/markets?complex_id=1 이 돌려주는 open 판(단지 6곳 × 주)
  전송   POST /api/v1/ingest/market-votes  {votes: [{external_id, complex_external_id,
         persona_external_id, side: up|down, rationale}]}  — 근거 없는 표는 서버가 거부한다

서버 마켓의 정산 기준은 단지 실거래 평단가로 보인다(`baseline_unit_price`). 우리 엔진은 구 단위
부동산원 지수를 읽는다. 근거 문장에 무엇을 보고 낸 표인지 그대로 적어 기준이 다르다는 걸 숨기지 않는다.

보류(q = 0.5)인 페르소나는 표를 내지 않는다. 서버가 up|down 만 받는다.
근거 문장에는 독자 행동 요청·다음 글 약속을 넣지 않는다(42번 서버 규칙).

실행:
  python3 scripts/market_vote.py          # 낼 표만 출력
  python3 scripts/market_vote.py --send   # 전송. CIVIC_PULSE_API_KEY 필요
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forecast_engine as E  # noqa: E402
from quality_audit import AI_COMMENT_ASK  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
REL_DIR = REPO / "data" / "reb-weekly" / "releases"
LOG = REPO / "data" / "forecast" / "market-votes.jsonl"
BASE = os.environ.get("BASE_URL", "https://danji.life")
UA = "danji-content-agent/1.0"

# 페르소나마다 근거를 다르게 말한다. 숫자는 전부 엔진 값에서 온다
VOICE = {
    "wb-persona-policy-lab": "{gu}구 최근 4주 오른 주 {u}·내린 주 {d}(부동산원 {pub} 발표). 기준 확률 {p:.2f}에 하방 편향을 얹어 {q:.2f}, {side}에 겁니다.",
    "wb-persona-real-talk": "{pub} 발표 {gu}구 4주 흐름이 오른 주 {u}, 내린 주 {d}입니다. 체감보다 표를 따르면 {side} 쪽({q:.2f})입니다.",
    "wb-persona-demand-check": "{gu}구 4주 중 상승 {u}주·하락 {d}주. 기준 확률 {p:.2f} 그대로, {side}고 봅니다.",
    "wb-persona-num-compare": "같은 잣대: {gu}구 4주 부호 합 {diff:+d}(부동산원 {pub}). 확률 {q:.2f}, {side}.",
    "wb-persona-cashflow": "{gu}구 매매지수 4주 중 {u}주 상승, {d}주 하락({pub} 발표). 확률 {q:.2f}. {side}에 둡니다.",
    "wb-persona-field-scout": "현장 정보 없이 표만 봤습니다. {gu}구 4주 오른 주 {u}·내린 주 {d}, 확률 {q:.2f}. {side}.",
}
SIDE_KO = {"up": "오른다", "down": "내린다"}


def call(method, path, body=None, idem=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Content-Type", "application/json")
    if method != "GET":
        req.add_header("X-API-Key", os.environ["CIVIC_PULSE_API_KEY"])
    if idem:
        req.add_header("Idempotency-Key", idem)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            payload = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            return e.code, payload
        except (urllib.error.URLError, OSError) as e:
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            return -1, str(e)
    return -1, "재시도 소진"


def latest_release():
    files = sorted(REL_DIR.glob("*.json"))
    if not files:
        raise SystemExit("data/reb-weekly/releases/ 가 비었다. scripts/reb_weekly.py 를 먼저 돌린다")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def md(iso):
    _, m, d = iso.split("-")
    return f"{int(m)}/{int(d)}"


def build_votes(rel, rounds):
    votes = []
    for rd in rounds:
        if rd["status"] != "open":
            continue
        gu = E.COMPLEX_GU.get(rd["complex_slug"])
        if not gu:
            continue
        f = E.forecast(rel, gu)
        for v in f["votes"]:
            if v["side"] is None:
                continue
            text = VOICE[v["persona"]].format(gu=gu, u=f["u"], d=f["d"], p=f["p"], q=v["q"], diff=f["u"] - f["d"],
                                              pub=md(rel["published"]), side=SIDE_KO[v["side"]])
            assert not AI_COMMENT_ASK.search(text), text
            votes.append({"external_id": f"vote-{rd['week_start']}-{rd['complex_slug']}-{v['persona']}",
                          "complex_external_id": rd["complex_external_id"],
                          "persona_external_id": v["persona"], "side": v["side"], "rationale": text,
                          "_round": rd["id"], "_week": rd["week_start"]})
    return votes


def main():
    ap = argparse.ArgumentParser(description="서버 예측 마켓 AI 투표")
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()

    rel = latest_release()
    st, mk = call("GET", "/api/v1/markets?complex_id=1")
    if st != 200:
        raise SystemExit(f"마켓 조회 실패: {st} {mk}")
    votes = build_votes(rel, mk["rounds"])
    print(f"입력: 부동산원 {rel['published']} 발표({rel['reference_date']} 기준) · 판 주차 {mk['week_start']} · 표 {len(votes)}개")
    for v in votes:
        print(f"  {v['_week']} {v['complex_external_id']:24}{v['persona_external_id']:26}{v['side']:5} {v['rationale']}")
    if not args.send or not votes:
        print("\n(--send 없이 실행했다. 보내지 않았다)" if not args.send else "\n낼 표가 없다")
        return 0

    body = {"votes": [{k: v for k, v in x.items() if not k.startswith("_")} for x in votes]}
    digest = hashlib.sha1(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8]
    st, res = call("POST", "/api/v1/ingest/market-votes", body, idem=f"wb-market-votes-{mk['week_start']}-{digest}")
    print(f"\n전송: {st} {json.dumps(res, ensure_ascii=False)[:400]}")
    if st == 200:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            for v in votes:
                fh.write(json.dumps(dict(v, input_release=rel["published"], engine=E.ENGINE), ensure_ascii=False) + "\n")
    st, after = call("GET", "/api/v1/markets?complex_id=1")
    if st == 200:
        print("판별 AI 표:", {r["complex_slug"]: r["ai_votes"] for r in after["rounds"]})
    return 0 if st == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
