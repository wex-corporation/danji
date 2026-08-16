#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TOP10 대단지 콘텐츠 팩(100편) 게시 스크립트."""
import json, os, sys, time, urllib.request, urllib.error

BASE_URL = os.environ.get("BASE_URL", "https://3-36-105-64.sslip.io")
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

pack = json.load(open(sys.argv[1], encoding="utf-8"))
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

print(f"\n완료: 성공 {ok} / 실패 {fail}")
if failed:
    print("실패 목록:")
    for f in failed:
        print("  ", f)
st, stats = call("GET", "/api/v1/stats")
print("stats:", json.dumps(stats, ensure_ascii=False) if st == 200 else st)
