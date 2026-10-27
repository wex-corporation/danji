#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""서버에서 사라진 관점 댓글을 되돌린다 (CLAUDE.md 35번).

2026-09 단지 소실(29번) 때 댓글이 1,057 → 553으로 줄었고, 남은 6곳에서도 일부 글의
댓글이 0이 됐다. 우리가 보낸 원본은 content/*.json 에 그대로 있다.

글이 아니라 댓글만 보낸다
  번들을 통째로 재전송하면 글·주제까지 다시 업서트된다. 그 사이 다른 팩에서 고친 글이
  옛 판본으로 돌아갈 수 있다. 그래서 `/ingest/comments` 에 `post_external_id` 로 글을 지목해
  댓글만 보낸다. 댓글은 external_id 업서트라 남아 있는 댓글과 겹쳐도 중복이 생기지 않는다.

어느 로컬 사본이 화면의 글인가
  같은 external_id 가 여러 팩에 있을 수 있다. 화면 목록의 제목·요약과 똑같은 사본만 쓴다
  (quality_audit.py 의 load_post 와 같은 기준). 맞는 사본이 없거나 둘 이상이 댓글 구성이
  다르면 건너뛰고 사유를 남긴다.

글 상세 API는 부르지 않는다. 호출마다 조회수가 오른다(34번). 목록 API의 comment_count 만 본다.

실행:
  python3 scripts/restore_comments.py            # 대상만 출력 (기본)
  python3 scripts/restore_comments.py --send     # 전송. CIVIC_PULSE_API_KEY 필요
"""

import argparse
import hashlib
import json
import re
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_audit import AI_COMMENT_ASK  # noqa: E402
BASE = os.environ.get("BASE_URL", "https://danji.life")
UA = "danji-content-agent/1.0"
KST = timezone(timedelta(hours=9))
STAMP = datetime.now(KST).strftime("%Y%m%d")


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


def live_posts():
    st, cx = call("GET", "/api/v1/complexes?limit=50")
    assert st == 200, cx
    out = []
    for c in cx["items"]:
        if c["post_count"] == 0 or "테스트" in c["name"]:
            continue
        st, d = call("GET", f"/api/v1/posts?complex={urllib.parse.quote(c['slug'])}&limit=100")
        assert st == 200, d
        out += [i for i in d["items"] if i.get("external_id")]
    return out


def local_copies():
    idx = defaultdict(list)
    for f in sorted((REPO / "content").glob("*.json")):
        try:
            pack = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for b in pack.get("bundles") or []:
            pl = b.get("payload") or {}
            post = pl.get("post")
            if post and post.get("external_id"):
                idx[post["external_id"]].append((f.name, post, pl.get("comments") or []))
    return idx


def server_would_reject(body):
    """문장이 전부 독자 행동 요청·다음 글 약속이면 서버가 422 empty_after_cleanup 으로 거절한다."""
    sents = [x for x in re.split(r"(?<=[.?!])\s+", body.strip()) if x]
    return bool(sents) and all(AI_COMMENT_ASK.search(x) for x in sents)


def plan():
    idx = local_copies()
    targets, skipped = [], []
    for item in live_posts():
        same = [(fn, p, cm) for fn, p, cm in idx.get(item["external_id"], [])
                if p.get("title") == item.get("title")
                and (p.get("summary") or "").strip() == (item.get("summary") or "").strip()]
        if not same:
            continue
        variants = {json.dumps(cm, ensure_ascii=False, sort_keys=True) for _, _, cm in same}
        fn, post, comments = same[-1]
        sent, live = len(comments), item.get("comment_count", 0)
        if live >= sent:
            continue
        if len(variants) > 1:
            skipped.append((item["external_id"], "같은 글의 로컬 사본끼리 댓글 구성이 다르다"))
            continue
        keep = [c for c in comments if not server_would_reject(c["body"])]
        for c in comments:
            if c not in keep:
                skipped.append((c["external_id"], "독자 행동 요청·다음 글 약속뿐인 댓글이라 서버 규칙상 복구 불가"))
        targets.append({"post_external_id": item["external_id"], "complex": item.get("complex_slug"),
                        "title": item.get("title"), "pack": fn, "sent": sent, "live": live,
                        "comments": keep})
    return targets, skipped


def main():
    ap = argparse.ArgumentParser(description="사라진 관점 댓글 복구")
    ap.add_argument("--send", action="store_true", help="실제로 보낸다")
    args = ap.parse_args()

    targets, skipped = plan()
    total = sum(t["sent"] for t in targets)
    print(f"복구 대상 글 {len(targets)}편 · 다시 보낼 댓글 {total}개 (화면에 남은 댓글 {sum(t['live'] for t in targets)}개)")
    for t in targets:
        print(f"  {t['complex'] or '?':22}{t['post_external_id']:34}{t['live']}/{t['sent']}  {t['pack']}")
    for eid, why in skipped:
        print(f"  [건너뜀] {eid}: {why}", file=sys.stderr)
    if not args.send:
        print("\n(--send 없이 실행했다. 보내지 않았다)")
        return 0

    ok = fail = 0
    for t in targets:
        if not t["comments"]:
            continue
        body = {"comments": [dict(c, post_external_id=t["post_external_id"]) for c in t["comments"]]}
        # 같은 키 + 다른 본문은 409다. 본문이 바뀌면 키도 바뀌게 해시를 붙인다
        digest = hashlib.sha1(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8]
        st, res = call("POST", "/api/v1/ingest/comments", body,
                       idem=f"wb-restore-comments-{t['post_external_id']}-{STAMP}-{digest}")
        if st == 200:
            ok += 1
        else:
            fail += 1
            print(f"  [실패] {t['post_external_id']} → {st} {str(res)[:160]}", file=sys.stderr)
        time.sleep(0.4)
    print(f"\n전송: 성공 {ok} / 실패 {fail}")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
