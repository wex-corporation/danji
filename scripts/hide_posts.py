#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""글을 status: hidden 으로 내린다. 삭제가 아니라 노출만 거둔다.

원베일리 27편을 14편으로 줄일 때 쓴다. 남산타운·올림픽선수기자촌을 내렸던
방식과 같다. 단지 등록과 글 자체는 남는다.

동작
  1. 피드에서 external_id → 내부 id 를 해석한다 (인증 불필요)
  2. 글 상세를 받아 본문·출처를 그대로 보존한 payload 를 만든다
  3. status 만 hidden 으로 바꿔 같은 external_id 로 재전송한다 (업서트 = 수정)

본문을 팩에 박아두지 않고 매번 서버에서 읽어오는 이유는, 게시 이후 수정된
내용을 오래된 사본으로 덮어쓰는 사고를 막기 위해서다.

사용법
  python3 hide_posts.py --dry-run                 # 키 없이 대상만 확인
  export CIVIC_PULSE_API_KEY=obk_...
  python3 hide_posts.py                           # 실제 반영
  python3 hide_posts.py --unhide                  # 되돌리기
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACK = REPO / "content" / "onebailey-v4.json"
BASE = os.environ.get("BASE_URL", "https://3-36-105-64.sslip.io")
UA = "danji-content-agent/1.0"


def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post(path, payload, key, idem):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{path}", data=raw, method="POST", headers={
        "Content-Type": "application/json", "X-API-Key": key,
        "Idempotency-Key": idem, "User-Agent": UA,
    })
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc
        except (urllib.error.URLError, OSError) as exc:
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"네트워크 실패: {exc}") from exc
    raise RuntimeError("재시도 소진")


def index_feed(slug):
    """external_id → 내부 id. 피드는 인증 없이 읽을 수 있다."""
    data = get(f"/api/v1/posts?complex={urllib.parse.quote(slug)}&limit=200")
    return {p["external_id"]: p["id"] for p in data.get("items", []) if p.get("external_id")}


def to_payload(detail, status):
    """상세 응답을 인제스트 payload 로 되돌린다. 본문·출처를 보존한다."""
    out = {
        "external_id": detail["external_id"],
        "complex_external_id": "cx-one-bailey",
        "category": detail["category"],
        "title": detail["title"],
        "body": detail["body"],
        "status": status,
    }
    for src, dst in (("summary", "summary"), ("source_note", "source_note"),
                     ("verification", "verification"), ("published_at", "published_at")):
        if detail.get(src):
            out[dst] = detail[src]
    if detail.get("sources"):
        out["sources"] = [
            {k: v for k, v in s.items() if k in ("label", "url", "publisher", "published_at") and v}
            for s in detail["sources"]
        ]
    return out


def main():
    ap = argparse.ArgumentParser(description="글을 hidden 으로 내린다")
    ap.add_argument("--dry-run", action="store_true", help="키 없이 대상만 확인")
    ap.add_argument("--unhide", action="store_true", help="published 로 되돌린다")
    ap.add_argument("--pack", default=str(PACK))
    args = ap.parse_args()

    status = "published" if args.unhide else "hidden"
    targets = json.loads(Path(args.pack).read_text(encoding="utf-8"))["hide_external_ids"]
    print(f"대상 {len(targets)}편 → status: {status}\n")

    try:
        feed = index_feed("one-bailey")
    except Exception as exc:  # noqa: BLE001
        print(f"[중단] 피드 조회 실패: {exc}", file=sys.stderr)
        return 1

    missing = [e for e in targets if e not in feed]
    resolved = [(e, feed[e]) for e in targets if e in feed]
    if missing:
        print(f"[경고] 피드에서 못 찾은 글 {len(missing)}편 (이미 내려갔을 수 있음):")
        for e in missing:
            print(f"    {e}")
        print()

    if args.dry_run:
        for ext, pid in resolved:
            print(f"  [예정] id={pid:<5} {ext}")
        print(f"\n실제 반영 대상 {len(resolved)}편. CIVIC_PULSE_API_KEY 설정 후 --dry-run 없이 실행하세요.")
        return 0

    key = os.environ.get("CIVIC_PULSE_API_KEY")
    if not key:
        print("[중단] CIVIC_PULSE_API_KEY 가 없습니다. 운영자에게 ingest:write 스코프 키를 받으세요.",
              file=sys.stderr)
        print("       키 없이 대상만 보려면: python3 hide_posts.py --dry-run", file=sys.stderr)
        return 2

    ok = fail = 0
    for ext, pid in resolved:
        try:
            detail = get(f"/api/v1/posts/{pid}")
            payload = {"posts": [to_payload(detail, status)]}
            # 내용이 바뀌면 키도 새로 만들어야 409 가 안 난다.
            post("/api/v1/ingest/posts", payload, key, f"hide-{ext}-{status}-v4")
            print(f"  [완료] {ext}")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  [실패] {ext}: {exc}", file=sys.stderr)
            fail += 1
        time.sleep(0.3)

    print(f"\n성공 {ok} / 실패 {fail}")
    if ok:
        stats = get("/api/v1/stats")
        print(f"stats: posts={stats.get('posts')} verified={stats.get('verified')}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
