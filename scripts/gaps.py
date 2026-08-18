#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사이클 시작 리포트 — `GET /api/v1/insights/gaps`.

CLAUDE.md 7장이 정한 콘텐츠 사이클의 1번 단계다. 무엇을 쓸지 정하기 전에
서버에 **무엇이 비었는지 먼저 묻는다.** 이 스크립트는 읽기만 한다.

주의 — 서버 안내를 그대로 따르면 안 된다
  응답의 `guidance` 는 "quiet_complexes 부터 채워라"인데, 지금 그 목록은
  **우리가 파일럿에서 일부러 뺀 단지들**로 채워져 있다. 글을 내렸으니 조용한 게
  당연하다. 그대로 따르면 어제 내린 단지를 오늘 다시 채우게 된다.
  그래서 기본 출력은 파일럿 교집합만 보여주고, 나머지는 --all 에서 따로 묶는다.

우선순위는 이 순서다.
  1. unanswered_questions — 사람이 물었는데 답이 없는 것. 무조건 최우선
  2. 파일럿 중 조용한 단지
  3. category_performance — 참여도가 높은데 편수가 적은 분야

사용법:
  set -a && . ./.env && set +a
  python3 scripts/gaps.py          # 파일럿만
  python3 scripts/gaps.py --all    # 파일럿 밖까지 참고용으로 함께
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "gaps"
BASE = os.environ.get("BASE_URL", "https://danji.life")
UA = "danji-content-agent/1.0"

# build_outlier_pack.py 의 PILOT_R2 와 같아야 한다. 한쪽만 바꾸면 어긋난다.
PILOT = ["one-bailey", "eunma", "olympic-park-foreon", "helio-city", "parkrio", "ricents"]


def get(path, key):
    req = urllib.request.Request(f"{BASE}{path}",
                                 headers={"User-Agent": UA, "X-API-Key": key})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"HTTP {exc.code}: {body[:200]}") from exc
        except (urllib.error.URLError, OSError) as exc:
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"네트워크 실패: {exc}") from exc


def main():
    ap = argparse.ArgumentParser(description="사이클 시작 리포트 (insights/gaps)")
    ap.add_argument("--all", action="store_true", help="파일럿 밖 단지도 참고용으로 표시")
    args = ap.parse_args()

    key = os.environ.get("CIVIC_PULSE_API_KEY")
    if not key:
        print("[중단] CIVIC_PULSE_API_KEY 가 없습니다. `set -a && . ./.env && set +a`", file=sys.stderr)
        return 2
    try:
        d = get("/api/v1/insights/gaps", key)
    except RuntimeError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    (OUT_DIR / f"{stamp}.json").write_text(
        json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    quiet = d.get("quiet_complexes") or []
    mine = [c for c in quiet if c.get("slug") in PILOT]
    theirs = [c for c in quiet if c.get("slug") not in PILOT]
    unanswered = d.get("unanswered_questions") or []

    print(f"\n생성 시각 {d.get('generated_at')}\n")

    print("① 미답변 주민 질문 — 무조건 최우선")
    if not unanswered:
        print("   없음. 아직 사람 질문이 0건이다. 답이 있는 척하지 않는다\n")
    else:
        for q in unanswered:
            print(f"   [id={q.get('id')}] {str(q.get('title'))[:60]}")
        print()

    print(f"② 조용한 파일럿 단지 ({len(mine)}/{len(PILOT)}곳)")
    if not mine:
        print("   없음. 파일럿 6곳 모두 최근 글이 있다\n")
    else:
        for c in mine:
            print(f"   {c['name'][:18]:20}{c.get('days_quiet','?'):>3}일 조용  "
                  f"최근 {str(c.get('last_post_at'))[:16]}")
        print()

    if theirs:
        if args.all:
            print(f"③ 파일럿 밖 ({len(theirs)}곳) — 참고용. 지금은 채우지 않는다")
            for c in theirs:
                print(f"   {c['name'][:18]:20}{c.get('household_count',0):>7,}세대  "
                      f"{c.get('days_quiet','?'):>3}일 조용")
            print()
        else:
            print(f"③ 파일럿 밖 {len(theirs)}곳이 조용하지만 **의도한 상태다.**")
            print("   글을 내려서 조용한 것이므로 채우지 않는다. 보려면 --all\n")

    perf = d.get("category_performance") or []
    if perf:
        print("④ 분야별 참여도 — 반응 좋은데 편수 적은 쪽이 다음 소재다")
        for c in sorted(perf, key=lambda x: -float(x.get("avg_engagement") or 0)):
            print(f"   {c['category']:6}{c['posts']:>4}편  평균 참여 {c['avg_engagement']}")
        print()

    tags = d.get("trending_tags") or []
    if tags:
        print("⑤ 뜨는 태그: " + ", ".join(f"{t['name']}({t['count']})" for t in tags) + "\n")

    stale = [t for t in (d.get("stale_topics") or []) if "테스트" not in (t.get("title") or "")]
    if stale:
        print("⑥ 오래 방치된 주제")
        for t in stale:
            print(f"   {t['title'][:26]:28}{t['category']:6}최근 {str(t.get('last_post_at'))[:10]}")
        print()

    print(f"서버 안내(guidance): {d.get('guidance')}")
    print("→ 단, quiet_complexes 는 파일럿과 교집합해서 읽어야 한다. 위 ③ 참조")
    print(f"→ 원본 저장 {(OUT_DIR / f'{stamp}.json').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
