#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사람 반응 찾기 — 사람이 쓴 글·댓글·한 줄 답변과, 우리가 아직 답하지 않은 것.

대표님 11/8 "답글 달아줘. 혹시 휴먼의 질문이 있으면 그것에 대한 답변을 달아주고,
의견/질문이 있으면 거기에 대해서 에이전트가 의견도 줘". 매일 루틴 2단계가 이 스크립트를 돌린다.

찾는 법(글 상세 호출을 줄인다)
  · 사람 글: 목록 API의 `author_type == "human"`
  · 사람 댓글: 목록의 `comment_count`가 우리가 보낸 댓글 수보다 많은 글과, 서버 스레드(external_id 없음)만
    글 상세를 열어 `author_type == "human"` 댓글을 고른다. 상세 조회는 우리 UA면 조회수에 안 센다(CLAUDE.md 48번 2)
  · 답했는지: `data/human-replies.json` 장부. 답글을 보낸 뒤 그 댓글 id 를 적는다

저장하는 것: 글·댓글 id, 시각, 표시 이름, 한 줄 답변 여부, 본문. IP 앞자리는 저장하지 않는다.

실행:
  python3 scripts/human_activity.py            # 표로 출력. 답 안 한 것이 있으면 종료 코드 2
  python3 scripts/human_activity.py --json     # data/human-activity/<오늘>.json 에도 남긴다
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE = "https://danji.life"
UA = "danji-content-agent/1.0"
KST = timezone(timedelta(hours=9))
LEDGER = REPO / "data" / "human-replies.json"


def get(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def kst(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d %H:%M")


def sent_counts():
    """우리 팩이 글마다 보낸 댓글 수(번들 안 댓글 + 따로 보낸 댓글)."""
    n = defaultdict(set)
    for f in sorted((REPO / "content").glob("*.json")):
        try:
            pk = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for b in pk.get("bundles") or []:
            pl = b.get("payload") or {}
            ext = (pl.get("post") or {}).get("external_id")
            for c in pl.get("comments") or []:
                n[ext].add(c["external_id"])
        for c in pk.get("comments") or []:
            n[c.get("post_external_id")].add(c["external_id"])
    return {k: len(v) for k, v in n.items()}


def scan():
    sent = sent_counts()
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {"replied": {}}
    found = []
    for cx in get("/api/v1/complexes?limit=50")["items"]:
        if cx["post_count"] == 0 or "테스트" in cx["name"]:
            continue
        items = get(f"/api/v1/posts?complex={urllib.parse.quote(cx['slug'])}&limit=100")["items"]
        for p in items:
            ext = p.get("external_id")
            if p.get("author_type") == "human":
                found.append({"kind": "post", "id": f"post-{p['id']}", "post_id": p["id"], "post_external_id": ext,
                              "complex": cx["slug"], "title": p["title"], "at": kst(p["published_at"]),
                              "author": p.get("author_label") or p.get("author_name"), "body": p.get("summary"),
                              "comment_count": p.get("comment_count")})
            # '많을 때'만 보면 아직 안 보낸 답글이 팩에 있는 글을 놓친다(11/8 은마). 다르기만 하면 연다
            need = (not ext) or p.get("comment_count", 0) != sent.get(ext, 0)
            if not need:
                continue
            det = get(f"/api/v1/posts/{p['id']}")
            for c in det.get("comments") or []:
                if c.get("author_type") != "human":
                    continue
                found.append({"kind": "comment", "id": f"comment-{c['id']}", "post_id": p["id"], "post_external_id": ext,
                              "complex": cx["slug"], "title": p["title"], "at": kst(c["created_at"]),
                              "author": c.get("author_label") or c.get("author_name"), "quick": bool(c.get("quick")),
                              "body": c.get("body"), "parent_id": c.get("parent_id")})
    for f in found:
        f["replied"] = ledger["replied"].get(f["id"])
    return sorted(found, key=lambda f: f["at"])


def main():
    ap = argparse.ArgumentParser(description="사람 반응 찾기")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    found = scan()
    todo = [f for f in found if not f["replied"]]
    print(f"사람 반응 {len(found)}건 · 아직 답 안 함 {len(todo)}건")
    for f in found:
        mark = "답함 " + ",".join(f["replied"]["reply_external_ids"]) if f["replied"] else "★ 답 필요"
        kind = "한 줄 답변" if f.get("quick") else ("글" if f["kind"] == "post" else "댓글")
        print(f"  {f['at']}  {f['complex']:20} {kind:6} {f['author']}: {str(f['body'])[:40]!r}  ← {f['title'][:28]}  [{mark}]")
    if a.json:
        out = REPO / "data" / "human-activity" / f"{datetime.now(KST):%Y-%m-%d}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"checked_at": datetime.now(KST).isoformat(), "items": found}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(out.relative_to(REPO))
    return 2 if todo else 0


if __name__ == "__main__":
    sys.exit(main())
