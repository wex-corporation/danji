#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TOP10 대단지 콘텐츠 팩(100편) 게시 스크립트."""
import json, os, sys, time, urllib.request, urllib.error

BASE_URL = os.environ.get("BASE_URL", "https://danji.life")
API_KEY = os.environ["CIVIC_PULSE_API_KEY"]

def call(method, path, body=None, idem=None, timeout=40):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE_URL + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-API-Key", API_KEY)
    if idem:
        req.add_header("Idempotency-Key", idem)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            payload = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 ** attempt); continue
            return e.code, payload
        except Exception as e:
            if attempt < 4:
                time.sleep(2 ** attempt); continue
            return -1, str(e)
    return -1, "retries exhausted"

# --due: 게시 시각(published_at)이 지난 글만 보낸다. 하루치 팩(build_daily_pack.py)을 슬롯마다 나눠 낼 때 쓴다.
# 미래 시각 글은 보내지 않는다(CLAUDE.md 5장). 이미 보낸 글을 다시 보내도 업서트라 안전하다
from datetime import datetime, timezone
pack = json.load(open(sys.argv[1], encoding="utf-8"))
# --only id1,id2: 이 글만 보낸다. 승인된 글과 승인 전 초안이 한 팩(하루치)에 같이 있을 때 쓴다
if "--only" in sys.argv[2:]:
    only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    pack["bundles"] = [b for b in pack["bundles"] if b["payload"]["post"]["external_id"] in only]
    pack["comments"] = [c for c in pack.get("comments", []) if c["external_id"] in only]
    print(f"--only: {len(pack['bundles'])}편만 보낸다", flush=True)
if "--due" in sys.argv[2:]:
    now = datetime.now(timezone.utc)
    later = [b for b in pack["bundles"] if datetime.fromisoformat(b["payload"]["post"]["published_at"]) > now]
    pack["bundles"] = [b for b in pack["bundles"] if b not in later]
    for b in later:
        print(f"  대기 {b['payload']['post']['published_at']}  {b['payload']['post']['external_id']}")
    print(f"게시 시각이 지난 글 {len(pack['bundles'])}편 · 대기 {len(later)}편", flush=True)
    # 보내는 순간에 서모스탯을 다시 센다. 서버도 글을 세운다(마켓 근거 스레드·최고가 토론 스레드, CLAUDE.md 48번)
    # 그래서 팩을 만들 때 통과했어도 보낼 때는 넘을 수 있다. 이미 올라간 글의 재전송은 세지 않는다
    from datetime import timedelta
    KST = timezone(timedelta(hours=9))
    feed = {}
    def _today(slug, day):
        if slug not in feed:
            req = urllib.request.Request(f"{BASE_URL}/api/v1/posts?complex={slug}&limit=100",
                                         headers={"User-Agent": "danji-content-agent/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                feed[slug] = json.loads(r.read().decode("utf-8"))["items"]
        return [i for i in feed[slug]
                if datetime.fromisoformat(i["published_at"].replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d") == day]
    held = []
    for b in list(pack["bundles"]):
        po = b["payload"]["post"]
        slug, day = po["complex_external_id"].removeprefix("cx-"), po["published_at"][:10]
        items = _today(slug, day)
        if any(i.get("external_id") == po["external_id"] for i in items):
            continue
        if len(items) >= 2:
            held.append(b)
            pack["bundles"].remove(b)
            print(f"  [보류] {po['external_id']}: {slug} {day} 이미 {len(items)}편(콜드스타트 2) — 보내지 않았다", flush=True)
st, h = call("GET", "/api/health")
print("health:", st, h.get("status") if isinstance(h, dict) else h, flush=True)
if st != 200:
    sys.exit("서버 도달 실패")

ok = fail = 0
failed = []
for i, b in enumerate(pack["bundles"], 1):
    pid = b["payload"]["post"]["external_id"]
    st, res = call("POST", "/api/v1/ingest/bundle", b["payload"], idem=b["idempotency_key"])
    if st == 200:
        ok += 1
    else:
        fail += 1
        failed.append((pid, st, str(res)[:200]))
        print(f"  FAIL {pid} → {st} {str(res)[:160]}", flush=True)
    if i % 10 == 0:
        print(f"  진행 {i}/{len(pack['bundles'])} (성공 {ok} / 실패 {fail})", flush=True)
    time.sleep(0.4)

# 보낸 글의 '데이터로는 모르는 것'(unknowns)이 서버 글 상세에 그대로 들어갔는지 본다(11/12~). 우리 UA 의 상세 조회는 조회수에 안 센다(CLAUDE.md 48번)
for b in pack["bundles"]:
    po = b["payload"]["post"]
    if po["external_id"] in [f[0] for f in failed] or not po.get("unknowns"):
        continue
    try:
        slug = po["complex_external_id"].removeprefix("cx-")
        req = urllib.request.Request(f"{BASE_URL}/api/v1/posts?complex={slug}&limit=100&sort=latest", headers={"User-Agent": "danji-content-agent/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            hit = [i for i in json.loads(r.read().decode("utf-8"))["items"] if i.get("external_id") == po["external_id"]]
        req = urllib.request.Request(f"{BASE_URL}/api/v1/posts/{hit[0]['id']}", headers={"User-Agent": "danji-content-agent/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            det = json.loads(r.read().decode("utf-8"))
        got = det.get("post", det).get("unknowns")
        print(f"  unknowns {po['external_id']}: {'일치' if got == po['unknowns'] else f'불일치 서버={got}'}", flush=True)
    except Exception as e:   # 대조 실패는 게시 실패가 아니다. 이유만 남긴다
        print(f"  unknowns {po['external_id']}: 대조 못 함 {e}", flush=True)

# 따로 다는 댓글(사람 댓글에 답하기 등). post_external_id 로 우리 글을 지목한다
if pack.get("comments"):
    import hashlib
    digest = hashlib.sha1(json.dumps(pack["comments"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8]
    st, res = call("POST", "/api/v1/ingest/comments", {"comments": pack["comments"]},
                   idem=f"wb-comments-{digest}")
    print(f"  댓글 {len(pack['comments'])}개 → {st} {str(res)[:160]}", flush=True)
    if st != 200:
        fail += 1
        failed.append(("comments", st, str(res)[:200]))

print(f"\n완료: 성공 {ok} / 실패 {fail}")
if failed:
    print("실패 목록:")
    for f in failed:
        print("  ", f)
st, stats = call("GET", "/api/v1/stats")
print("stats:", json.dumps(stats, ensure_ascii=False) if st == 200 else st)
