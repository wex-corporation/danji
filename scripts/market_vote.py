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
  python3 scripts/market_vote.py --backfill   # 지난 주차 소급 표를 만든다(파일만, 전송하지 않는다)

소급 표 (2026-10-31 운영자 결정 "단지 서비스를 처음 연 주부터, 에이전트들이 소급해서")
  첫 글이 8/1(토)이라 첫 주는 7/27 주다. 주 W의 표는 W 직전 목요일 발표 하나만 입력으로 쓴다(발표 → +4일 = 그 주 월요일).
  소급 표는 이미 지난 주에 대해 지금 계산한 것이다. 명세 5.4(예측은 실제 로그, 조작 금지) 때문에
  `backfill: true`와 근거 문장의 "소급 계산"으로 드러내고, 서버는 실시간 성적과 따로 집계해야 한다.
  서버가 10/31(PR #4)부터 `week_start`·`backfill: true`를 받는다. 닫힌 주에 backfill 없이 보내면 409 week_closed,
  같은 판에 같은 페르소나의 실시간 표가 있으면 action "skipped". 한 요청 100표까지, 하나라도 걸리면 요청 통째로 거절.
  소급 성적은 서버가 실시간 성적과 따로 센다. 소급 판 정산은 서버 실거래 동기화가 따라잡은 뒤 차례로 난다

  python3 scripts/market_vote.py --send-backfill --weeks 2026-07-27   # 한 주만 먼저 보내 본다
  python3 scripts/market_vote.py --send-backfill                      # 파일의 전부(100표씩 나눠서)

  **사고(2026-11-01 08:11 KST).** 서버가 "준비됨"이라고 답한 뒤 7/27 주 36표를 보냈더니 `week_start`를 무시하고
  이번 주(11/2) 판의 같은 페르소나 표를 덮었다(응답 action "updated", 서버 표 id가 실시간 표와 같다). 실시간 36표를 새 멱등키로
  다시 보내 몇 분 안에 되돌렸다. 그래서 보낼 때마다 이번 주 판에 '소급' 근거가 섞였는지 확인하고, 섞였으면 실시간 표를 되돌린 뒤 멈춘다.
  `BACKFILL_SERVER_OK`는 서버가 고쳤다는 확인을 받고 나서만 True 로 바꾼다
"""

import argparse
from collections import Counter
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
# 마켓 패널 v2(11/9 주 판부터, forecast_engine.MARKET_VOTERS). 함수는 그 표의 값(c)을 받아 문장을 고른다.
# 수요밀도체크는 낙관 3 → 4로 바뀌어 옛 문장("기준 확률 그대로")이 틀리므로 v2 문장을 따로 둔다. 소급 표(옛 패널)는 VOICE 그대로
VOICE_V2 = {
    "wb-persona-demand-check": lambda c: (
        f"{c['gu']}구 4주 중 상승 {c['u']}주·하락 {c['d']}주(부동산원 {c['pub']}). 기준 확률 {c['p']:.2f}에 상방 쪽으로 조금 얹어 {c['q']:.2f}, {c['side']}고 봅니다."),
    "INF-012": lambda c: (
        f"하방 위험부터 보는 쪽인데도 {c['gu']}구 4주가 오른 주 {c['u']}·내린 주 {c['d']}입니다({c['pub']} 발표). 하방 편향을 빼고도 {c['q']:.2f}, 이번 판은 오른다 쪽에 섭니다."
        if c["side_en"] == "up" else
        f"{c['gu']}구 4주 오른 주 {c['u']}·내린 주 {c['d']}(부동산원 {c['pub']}). 하방 편향까지 더해 {c['q']:.2f}, 내린다 쪽입니다."),
    "INF-007": lambda c: (
        f"쏠림 {c['diff']:+d}({c['gu']}구 4주, {c['pub']} 발표). 반대편이 서려면 다른 입력이 있어야 하는데 이번 판 입력은 구 지수 하나라 {c['q']:.2f}, {c['side']}에 둡니다."
        if abs(c["diff"]) >= 2 else
        f"{c['gu']}구 4주가 오른 주 {c['u']}·내린 주 {c['d']}로 갈렸습니다({c['pub']} 발표). 갈린 판에선 아래를 조금 더 봐서 {c['q']:.2f}, {c['side']}."),
    "INF-003": lambda c: (
        f"기준: 부동산원 {c['pub']} 발표 {c['gu']}구 마지막 4주 부호. 판정: 오른 주 {c['u']}·내린 주 {c['d']}, 확률 {c['q']:.2f} → {c['side']}."),
    "INF-001": lambda c: (
        f"한 달에 한 번 내는 표입니다. {c['gu']}구 4주(부동산원 {c['pub']})는 오른 주 {c['u']}·내린 주 {c['d']}, 확률 {c['q']:.2f}이라 {c['side']} 쪽에 둡니다."),
    "INF-005": lambda c: (
        f"{c['gu']}구 4주 중 오른 주 {c['u']}, 내린 주 {c['d']}({c['pub']} 발표). 조금 밝게 봐서 {c['q']:.2f}, {c['side']}에 한 표."),
    "INF-020": lambda c: (
        f"숫자를 읽는 법부터: {c['gu']}구 4주는 오른 주 {c['u']}·내린 주 {c['d']}(부동산원 {c['pub']}). 확률 {c['q']:.2f}, {c['side']}로 읽습니다."),
}
SIDE_KO = {"up": "오른다", "down": "내린다"}


def rationale(pid, week, c):
    if week >= E.MARKET_V2_FROM and pid in VOICE_V2:
        return VOICE_V2[pid](c)
    return VOICE[pid].format(**c)


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
        f = E.forecast(rel, gu, voters=E.market_panel(rd["week_start"]))
        for v in f["votes"]:
            if v["side"] is None:
                continue
            c = dict(gu=gu, u=f["u"], d=f["d"], p=f["p"], q=v["q"], diff=f["u"] - f["d"],
                     pub=md(rel["published"]), side=SIDE_KO[v["side"]], side_en=v["side"])
            text = rationale(v["persona"], rd["week_start"], c)
            assert not AI_COMMENT_ASK.search(text), text
            votes.append({"external_id": f"vote-{rd['week_start']}-{rd['complex_slug']}-{v['persona']}",
                          "complex_external_id": rd["complex_external_id"],
                          "persona_external_id": v["persona"], "side": v["side"], "rationale": text,
                          "_round": rd["id"], "_week": rd["week_start"]})
    return votes


def _voice_check():
    pids = {v[0] for v in E.MARKET_VOTERS}
    assert pids <= set(VOICE) | set(VOICE_V2), pids - set(VOICE) - set(VOICE_V2)
    for f in ({"u": 4, "d": 0, "p": 0.9}, {"u": 0, "d": 4, "p": 0.1}, {"u": 2, "d": 2, "p": 0.5}, {"u": 1, "d": 1, "p": 0.5}):
        texts = []
        for pid, _, opt, _ in E.market_panel("2026-12-07"):
            side, q = E.vote(f["p"], opt)
            if side is None:
                continue
            c = dict(gu="송파", pub="12/3", q=q, diff=f["u"] - f["d"], side=SIDE_KO[side], side_en=side, **f)
            t = rationale(pid, "2026-12-07", c)
            assert "{" not in t and not AI_COMMENT_ASK.search(t), t
            texts.append(t)
        assert len(set(texts)) == len(texts)


_voice_check()

BACKFILL_FIRST_WEEK = "2026-07-27"   # 첫 글 8/1(토)이 속한 주
BACKFILL_LIVE_WEEK = "2026-11-02"    # 실시간 표가 시작된 주. 서버의 이번 주가 넘어가도 소급 범위는 여기서 끝난다
BACKFILL_SERVER_OK = False           # 11/1 사고 뒤 잠갔다. 서버가 week_start 를 실제로 받는다는 확인 후에만 True
BACKFILL_OUT = REPO / "data" / "forecast" / "market-votes-backfill.json"
SLUGS = [("godeok-gracium", "cx-godeok-gracium"), ("one-bailey", "cx-one-bailey"), ("ricents", "cx-ricents"),
         ("mapo-raemian-prugio", "cx-mapo-raemian-prugio"), ("eunma", "cx-eunma"), ("helio-city", "cx-helio-city")]


def live_round_polluted():
    """이번 주 open 판 근거에 '소급'이 보이면 서버가 week_start 를 무시하고 덮은 것이다"""
    st, mk = call("GET", "/api/v1/markets?complex_id=1")
    for rd in mk.get("rounds", []) if st == 200 else []:
        st2, d = call("GET", f"/api/v1/markets/{rd['id']}")
        if st2 == 200 and any("소급" in x.get("rationale", "") for x in d.get("rationales", [])):
            return True
    return st != 200


def restore_live(week):
    """market-votes.jsonl 에 남은 그 주 실시간 표를 새 멱등키로 다시 보낸다(같은 키는 캐시된 응답만 돌려준다)"""
    live = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    live = [v for v in live if v["external_id"].startswith(f"vote-{week}-")]
    keep = ("external_id", "complex_external_id", "persona_external_id", "side", "rationale")
    body = {"votes": [{k: v[k] for k in keep} for v in live]}
    digest = hashlib.sha1(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8]
    st, res = call("POST", "/api/v1/ingest/market-votes", body, idem=f"wb-market-votes-{week}-restore-{digest}")
    print(f"  실시간 표 {len(live)}개 되돌림: {st}", file=sys.stderr)


def backfill(live_week):
    """지난 주차 소급 표. 주 W = 발표일 + 4일(월). 이번 주(live_week)부터는 실시간 표가 맡는다."""
    from datetime import date, timedelta
    votes, weeks = [], []
    for f in sorted(REL_DIR.glob("*.json")):
        rel = json.loads(f.read_text(encoding="utf-8"))
        week = (date.fromisoformat(rel["published"]) + timedelta(days=4)).isoformat()
        if not (BACKFILL_FIRST_WEEK <= week < live_week):
            continue
        assert rel["embargo_kst"][:10] < week, (rel["published"], week)   # 입력 발표는 그 주가 시작되기 전에 나왔다
        weeks.append((week, rel["published"]))
        rounds = [{"status": "open", "complex_slug": s, "complex_external_id": cx, "week_start": week, "id": None}
                  for s, cx in SLUGS]
        for v in build_votes(rel, rounds):
            v["rationale"] += " (10/31 소급 계산)"
            v["week_start"], v["backfill"], v["input_release"] = week, True, rel["published"]
            votes.append(v)
    assert weeks and weeks[0][0] == BACKFILL_FIRST_WEEK, weeks[:1]
    return weeks, votes


def main():
    ap = argparse.ArgumentParser(description="서버 예측 마켓 AI 투표")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--backfill", action="store_true", help="지난 주차 소급 표를 파일로만 만든다")
    ap.add_argument("--send-backfill", action="store_true", help="만들어 둔 소급 표 파일을 보낸다(100표씩)")
    ap.add_argument("--weeks", nargs="*", help="--send-backfill 때 이 주차만")
    args = ap.parse_args()

    if args.send_backfill:
        if not BACKFILL_SERVER_OK:
            raise SystemExit("소급 전송은 잠겨 있다(11/1 사고, CLAUDE.md 48번). 서버가 week_start 를 받는다는 확인 뒤 BACKFILL_SERVER_OK 를 연다")
        data = json.loads(BACKFILL_OUT.read_text(encoding="utf-8"))
        votes = [v for v in data["votes"] if not args.weeks or v["week_start"] in args.weeks]
        keep = ("external_id", "complex_external_id", "persona_external_id", "side", "rationale", "week_start", "backfill")
        for v in votes:
            assert v["backfill"] is True and v["week_start"] < data["meta"]["live_week"] and not AI_COMMENT_ASK.search(v["rationale"])
        actions, failed = Counter(), 0
        sent_log = REPO / "data" / "forecast" / "market-votes-backfill-sent.jsonl"
        for i in range(0, len(votes), 100):
            chunk = [{k: v[k] for k in keep} for v in votes[i:i + 100]]
            digest = hashlib.sha1(json.dumps(chunk, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8]
            st, res = call("POST", "/api/v1/ingest/market-votes", {"votes": chunk}, idem=f"wb-market-backfill-{digest}")
            if st != 200:
                failed += 1
                print(f"  [실패] {i}~{i + len(chunk) - 1}: {st} {str(res)[:300]}")
                continue
            got = {r.get("external_id"): r for r in res.get("result", [])}
            with sent_log.open("a", encoding="utf-8") as fh:
                for v in chunk:
                    r = got.get(v["external_id"], {})
                    actions[r.get("action", "?")] += 1
                    fh.write(json.dumps(dict(v, action=r.get("action"), server_id=r.get("id"),
                                             sent_at=time.strftime("%Y-%m-%dT%H:%M:%S%z")), ensure_ascii=False) + "\n")
            print(f"  {i}~{i + len(chunk) - 1}: {st} {dict(Counter(r.get('action') for r in res.get('result', [])))}")
            if live_round_polluted():
                print("  [중단] 이번 주 판에 소급 근거가 섞였다 — 실시간 표를 되돌린다", file=sys.stderr)
                restore_live(data["meta"]["live_week"])
                return 1
            time.sleep(0.5)
        print(f"\n소급 표 {len(votes)}개 · 결과 {dict(actions)} · 실패 요청 {failed}")
        return 0 if not failed else 1

    if args.backfill:
        st, mk = call("GET", "/api/v1/markets?complex_id=1")
        if st != 200:
            raise SystemExit(f"마켓 조회 실패: {st} {mk}")
        weeks, votes = backfill(min(mk["week_start"], BACKFILL_LIVE_WEEK))
        for w, pub in weeks:
            vs = [v for v in votes if v["week_start"] == w]
            sides = {s: sum(1 for v in vs if v["side"] == s) for s in ("up", "down")}
            print(f"  주 {w} ← 발표 {pub}  표 {len(vs)} (오른다 {sides['up']} · 내린다 {sides['down']})")
        body = {"meta": {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "engine": E.ENGINE, "first_week": BACKFILL_FIRST_WEEK,
                         "live_week": min(mk["week_start"], BACKFILL_LIVE_WEEK), "note": "소급 표. 서버가 week_start·backfill 을 받기 전에는 보내지 않는다"},
                "votes": [{k: v for k, v in x.items() if not k.startswith("_")} for x in votes]}
        BACKFILL_OUT.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n소급 {len(weeks)}주 · 표 {len(votes)}개 → {BACKFILL_OUT.relative_to(REPO)} (보내지 않았다)")
        return 0

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
