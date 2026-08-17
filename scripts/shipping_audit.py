#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""출고 검사 — 명세 8.3.

  "이름을 가리고 읽었을 때 서로 바꿔도 어색하지 않은 글이 3개 이상이면
   해당 배치를 반려한다."

사람이 눈으로 하던 판정을 기계로 근사한다. 방법은 두 단계다.

  1. 마스킹 — 단지명·숫자·고유명사를 자리표시자로 바꾼다.
     이걸 해야 "서로 바꿔도"가 성립하는지 볼 수 있다.
     마스킹 전에는 단지명이 달라서 모든 글이 달라 보인다.
  2. 유사도 — 마스킹된 본문의 어절 집합으로 자카드 유사도를 잰다.
     임계값 이상인 쌍은 '교체 가능'으로 본다.

임계값 0.55는 절대 기준이 아니다. 상위 쌍을 눈으로 확인해 보정할 것.
이 검사는 반려 여부를 자동 결정하지 않고 후보를 뽑아 준다. 판정은 사람이 한다.

사용법:
  python3 shipping_audit.py                 # 전체 게시글
  python3 shipping_audit.py --complex eunma # 한 단지만
  python3 shipping_audit.py --threshold 0.5
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from collections import defaultdict
from itertools import combinations
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE = "https://3-36-105-64.sslip.io"
UA = "danji-content-agent/1.0"

# 마스킹 대상. 이걸 안 지우면 단지명 때문에 전부 달라 보인다.
COMPLEX_WORDS = [
    "래미안 원베일리", "원베일리", "아크로리버파크", "아리팍", "은마아파트", "은마",
    "디에이치 퍼스티어 아이파크", "디퍼아", "헬리오시티", "헬리오", "잠실엘스", "엘스",
    "리센츠", "파크리오", "올림픽파크 포레온", "올파포", "고덕그라시움", "그라시움",
    "마포래미안푸르지오", "마래푸", "트리지움", "남산타운",
]
DISTRICTS = ["서초구", "강남구", "송파구", "강동구", "마포구", "반포동", "대치동",
             "잠실동", "신천동", "상일동", "둔촌동", "아현동", "가락동", "문정동"]


def get(path, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001
            if i == retries - 1:
                raise
            time.sleep(2 ** i)


def mask(text):
    """단지·지역·숫자를 지운다. 남는 건 문장 구조와 서술 방식이다."""
    t = text
    for w in sorted(COMPLEX_WORDS + DISTRICTS, key=len, reverse=True):
        t = t.replace(w, "〈단지〉")
    t = re.sub(r"\d[\d,\.]*", "〈수〉", t)
    t = re.sub(r"[㎡㎥%원년월일층대명동호]", "", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def tokens(text):
    """어절 단위. 조사가 붙어 있어도 구조가 같으면 겹친다."""
    return {w for w in re.split(r"[\s·,\.\!\?\(\)\[\]\"'“”‘’—…]+", text) if len(w) > 1}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main():
    ap = argparse.ArgumentParser(description="출고 검사 (명세 8.3)")
    ap.add_argument("--complex", dest="only")
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()

    cxs = [c for c in get("/api/v1/complexes?limit=50")["items"]
           if c["post_count"] > 0 and "테스트" not in c["name"]]
    if args.only:
        cxs = [c for c in cxs if c["slug"] == args.only]
        if not cxs:
            print(f"[중단] 알 수 없는 슬러그: {args.only}", file=sys.stderr)
            return 2

    posts = []
    for c in cxs:
        items = get(f"/api/v1/posts?complex={c['slug']}&limit=60")["items"]
        for p in items[:args.limit]:
            try:
                d = get(f"/api/v1/posts/{p['id']}")
            except Exception as exc:  # noqa: BLE001
                print(f"  [실패] id={p['id']}: {exc}", file=sys.stderr)
                continue
            body = d.get("body") or ""
            if len(body) < 80:
                continue
            posts.append({"id": d["id"], "ext": d.get("external_id"),
                          "cx": c["name"], "title": d.get("title", ""),
                          "persona": d.get("persona_handle") or d.get("author_label") or "?",
                          "masked": mask(body)})
            time.sleep(0.12)
        print(f"  수집 {c['name']} 누적 {len(posts)}편", flush=True)

    for p in posts:
        p["tok"] = tokens(p["masked"])

    pairs = []
    for a, b in combinations(posts, 2):
        s = jaccard(a["tok"], b["tok"])
        if s >= args.threshold:
            pairs.append((s, a, b))
    pairs.sort(key=lambda x: -x[0])

    # 명세 8.3의 '배치' 단위를 단지로 본다. 단지별로 교체가능 글 수를 센다.
    involved = defaultdict(set)
    for s, a, b in pairs:
        involved[a["cx"]].add(a["id"])
        involved[b["cx"]].add(b["id"])

    print(f"\n대상 {len(posts)}편 · 임계값 {args.threshold} · 교체가능 쌍 {len(pairs)}건\n")
    if pairs:
        print("=== 유사도 상위 12쌍 ===")
        for s, a, b in pairs[:12]:
            print(f"  {s:.2f}  [{a['cx'][:8]}] {a['title'][:26]}")
            print(f"        [{b['cx'][:8]}] {b['title'][:26]}")
    print("\n=== 단지별 판정 (명세 8.3: 3편 이상이면 반려) ===")
    rejected = []
    for c in cxs:
        n = len(involved.get(c["name"], ()))
        verdict = "반려" if n >= 3 else ("주의" if n > 0 else "통과")
        if n >= 3:
            rejected.append(c["name"])
        print(f"  {c['name'][:20]:22}교체가능 {n:>2}편  {verdict}")

    print(f"\n반려 대상 단지 {len(rejected)}곳" + (f": {', '.join(rejected)}" if rejected else ""))
    out = REPO / "data" / "shipping-audit.json"
    out.write_text(json.dumps({
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "posts": len(posts), "threshold": args.threshold,
        "pairs": len(pairs), "rejected_complexes": rejected,
        "top_pairs": [{"similarity": round(s, 3),
                       "a": {"cx": a["cx"], "title": a["title"], "ext": a["ext"]},
                       "b": {"cx": b["cx"], "title": b["title"], "ext": b["ext"]}}
                      for s, a, b in pairs[:40]],
        "note": "명세 8.3 출고 검사의 기계 근사. 마스킹 후 자카드 유사도. 최종 판정은 사람이 한다",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"→ {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
