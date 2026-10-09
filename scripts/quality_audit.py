#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""라이브 글 품질 감사 — 게시된 글 전체를 같은 기준으로 채점한다.

출고 검사(shipping_audit.py)는 '서로 바꿔 끼워도 되는 글'만 본다. 이 스크립트는
CLAUDE.md 4·5장의 글쓰기 규칙을 **이미 나간 글**에 다시 걸어 기준선을 만든다.
품질이 나아지고 있는지는 이 숫자가 사이클마다 어떻게 움직이는지로 판단한다.

공개 API만 쓴다. 키가 필요 없어서 콘텐츠 저장소 밖의 에이전트도 그대로 돌릴 수 있다.

주의 — 글 상세 API(`/api/v1/posts/{id}`)는 부를 때마다 조회수를 1 올린다(2026-10-09 확인).
감사를 돌릴수록 유일한 반응 지표가 오염된다. 그래서 본문은 **로컬 팩(content/*.json)에서**
읽고, 조회수는 카운트가 안 오르는 목록 API에서 읽는다. 상세는 로컬 사본이 화면과 다르거나
사람 댓글이 있을 수 있는 글에만 부르고, 부른 횟수를 결과에 남긴다.

  python3 scripts/quality_audit.py                 # 전 단지
  python3 scripts/quality_audit.py --complex eunma # 한 단지
  python3 scripts/quality_audit.py --show Q6       # 특정 항목에 걸린 글만 자세히

결과: data/quality/<날짜>.json (글별 판정 + 요약). 같은 날 다시 돌리면 덮어쓴다.

항목 ID는 docs/writing-quality-loop.md 의 루브릭과 같다. 하나를 고치면 둘 다 고친다.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shipping_audit import COMPLEX_WORDS, get, jaccard, mask, tokens  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

# ── 하드 규칙: 하나라도 걸리면 결함 ─────────────────────────────
TRANSITION = re.compile(r"여기서부터는\s*(해석|단서)|해석입니다")
DATED = re.compile(r"(확인|조회|기준|공개|발표)[^·]{0,20}20\d\d|20\d\d[.\-/]\s?\d{1,2}[.\-/]\s?\d{1,2}")
BANNED = {
    "출처불명": ["알려져 있", "라고 한다", "다고 한다", "인터넷에서", "찾아보니", "카더라", "들리는 말"],
    "경험창작": ["제가 살", "살아보니", "살아 보니", "우리 집은", "우리 동네는"],
    "고정도입": ["바깥 커뮤니티", "반복해서 올라오는"],
    "투자지시": ["매수하세요", "매도하세요", "지금 사", "지금 파", "지금이 기회", "오를 겁니다", "내릴 겁니다",
             "이하로 내놓지", "호가를 지켜"],
    "서열": ["명문", "상위권", "학군지"],
    "우열비교": ["보다 낫", "보다 좋은 단지"],
    "말미고지": ["투자 권유가 아닙니다", "투자 판단은 본인"],
}
# 숫자+받침 있는 단위 뒤의 '로'('47명로'). '대·개'처럼 받침 없는 단위와
# ㄹ받침 단위('일·월')는 '로'가 맞다('24일로')
BAD_RO = re.compile(r"\d[\d,.]*\s?(명|층|원|동|분|회|건|권|년)로(?![가-힣])")
# '저희 집계'는 정상이다. 낱말로서의 '저희 집'만 잡는다
OWN_HOME = re.compile(r"저희 집(?!계)")

# ── 경고: 결함은 아니지만 품질 신호 ────────────────────────────
# 체험처럼 읽히는 어투. 데이터를 읽고 한 말일 수도 있어 사람이 문맥을 보고 판정한다
EXPERIENCE_TONE = re.compile(r"하더군요|더라고요|해 봤더니|가 보니")
RELATIVE_TIME = re.compile(r"오늘|어제|이번 주|지난주|이번 달|최근 들어")
MONO_RUN = 8          # '~니다.' 문말이 이만큼 연속되면 단조
SIM_WARN = 0.35       # 마스킹 후 어절 자카드. 출고 검사 임계값과 같다
STALE_DAYS = 14       # 시점 의존 표현이 이 기간보다 오래된 글에 있으면 낡은 글


def has_batchim(ch):
    code = ord(ch) - 0xAC00
    return 0 <= code <= 11171 and code % 28 != 0


def josa_errors(text):
    """단지명 바로 뒤 조사만 본다. 일반 낱말은 어미와 구분이 안 돼 오탐이 많다."""
    errs = []
    for w in sorted(COMPLEX_WORDS, key=len, reverse=True):
        for m in re.finditer(re.escape(w) + r"(은|는|이|가|을|를|과|와)(?![가-힣])", text):
            j = m.group(1)
            want_batchim = j in ("은", "이", "을", "과")
            if has_batchim(w[-1]) != want_batchim:
                errs.append(m.group())
    errs += [m.group() for m in BAD_RO.finditer(text)]
    return errs


def mono_run(body):
    run = best = 0
    for s in re.split(r"(?<=[.?!])\s+", body):
        if s.rstrip().endswith("니다."):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def kst(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(KST)


def local_index():
    """content/*.json 의 글을 external_id 로 모은다. 같은 ID가 여러 팩에 있으면 전부 후보로 둔다."""
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
                idx[post["external_id"]].append((post, pl.get("comments") or []))
    return idx


def load_post(item, idx, stats):
    """화면과 같은 로컬 사본이 있으면 그걸 쓰고, 없으면 상세 API를 부른다(조회수 +1)."""
    for post, comments in idx.get(item.get("external_id") or "", []):
        same = (post.get("title") == item.get("title")
                and (post.get("summary") or "").strip() == (item.get("summary") or "").strip())
        live_cc = item.get("comment_count", 0)
        # 화면 댓글이 로컬보다 많으면 사람 댓글이 있을 수 있다 → 상세를 본다
        if same and live_cc <= len(comments):
            stats["local"] += 1
            d = dict(item)
            d.update(body=post.get("body", ""), sources=post.get("sources") or [],
                     source_note=post.get("source_note", ""),
                     # 서버에서 댓글이 사라졌으면 남은 게 어느 것인지 모르므로 본문을 비교에 쓰지 않는다
                     comments=[dict(c, author_trust="ai") for c in comments] if live_cc == len(comments) else [],
                     _sent_comments=len(comments))
            return d
    stats["detail"] += 1
    d = get(f"/api/v1/posts/{item['id']}")
    d["views"] = item.get("views", d.get("views", 0))   # 방금 오른 1을 빼고 목록 값을 쓴다
    time.sleep(0.08)
    return d


def audit_post(d, today):
    title, body, summary = d.get("title") or "", d.get("body") or "", d.get("summary") or ""
    srcs = d.get("sources") or []
    note = d.get("source_note") or ""
    comments = d.get("comments") or []
    text = "\n".join([title, summary, body])
    hard, warn = {}, {}

    verified = d.get("verification") == "verified"
    # Q1 출처: verified 면 출처가 있어야 한다
    if verified and not srcs:
        hard["Q1"] = "verified 인데 sources 없음"
    # Q2 사실/해석 분리. 사실 글(verified)에만 건다 — 의견 글은 전부가 해석이다
    if verified and len(body) >= 400 and not TRANSITION.search(body):
        hard["Q2"] = "전환 문장 없음 — 해석이 섞였는지 확인"
    # Q3 질문으로 닫기
    if not body.rstrip().endswith("?"):
        hard["Q3"] = "질문으로 끝나지 않음: " + body.rstrip()[-30:]
    # Q4 제목 34자
    if len(title) > 34:
        hard["Q4"] = f"제목 {len(title)}자"
    # Q5 마크다운
    if "**" in text:
        hard["Q5"] = "** 노출"
    # Q6 금지 표현
    hits = [f"{k}:{w}" for k, ws in BANNED.items() for w in ws if w in text]
    hits += [f"경험창작:{m.group()}" for m in OWN_HOME.finditer(text)]
    if hits:
        hard["Q6"] = ", ".join(hits)
    # Q7 조사
    je = josa_errors(text)
    if je:
        hard["Q7"] = ", ".join(je[:5])

    # W6 출처에 확인·조회 날짜가 없다. 자료가 갱신되면 이 글이 언제 기준인지 알 수 없다
    if verified and srcs and not (DATED.search(note) or any(DATED.search(s.get("label", "")) for s in srcs)):
        warn["W6"] = "출처·노트에 확인일 없음"
    # W7 체험처럼 읽히는 어투
    tone = sorted(set(EXPERIENCE_TONE.findall(body)))
    if tone:
        warn["W7"] = "/".join(tone)
    # W1 시점 의존 표현이 오래된 글에 남아 있다
    age = (today - kst(d["published_at"]).date()).days
    rel = sorted(set(RELATIVE_TIME.findall(body)))
    if rel and age > STALE_DAYS:
        warn["W1"] = f"{age}일 된 글에 {'/'.join(rel)}"
    # W2 문말 단조
    mr = mono_run(body)
    if mr >= MONO_RUN:
        warn["W2"] = f"'니다.' {mr}연속"
    # W3 관점 댓글
    ai_comments = [c for c in comments if (c.get("author_trust") or c.get("author_type")) == "ai"]
    humans = [c for c in comments if (c.get("author_trust") or "ai") != "ai"]
    live_ai = d.get("comment_count", len(comments)) - len(humans)
    if live_ai < 2:
        warn["W3"] = f"관점 댓글 {live_ai}개"
    # W8 보낸 댓글이 서버에서 사라졌다(2026-09 단지 소실 때 같이 빠진 것으로 보인다)
    sent = d.get("_sent_comments")
    if sent is not None and d.get("comment_count", 0) < sent:
        warn["W8"] = f"보낸 댓글 {sent}개 → 화면 {d.get('comment_count', 0)}개"

    return {
        "id": d["id"], "ext": d.get("external_id"), "complex": d.get("complex_slug"),
        "persona": d.get("persona_handle") or d.get("author_name"), "category": d.get("category"),
        "title": title, "published_at": d["published_at"], "age_days": age,
        "views": d.get("views", 0), "likes": d.get("likes", 0), "helpful": d.get("helpful_count", 0),
        "comments": len(comments), "human_comments": len(humans),
        "hard": hard, "warn": warn,
        "comment_bodies": [c.get("body", "") for c in ai_comments],
        "_tok": tokens(mask(body)),
    }


def main():
    ap = argparse.ArgumentParser(description="라이브 글 품질 감사")
    ap.add_argument("--complex", dest="only")
    ap.add_argument("--show", help="이 항목(Q1~Q7, W1~W8)에 걸린 글을 전부 출력")
    args = ap.parse_args()

    today = datetime.now(KST).date()
    cxs = [c for c in get("/api/v1/complexes?limit=50")["items"]
           if c["post_count"] > 0 and "테스트" not in c["name"]]
    if args.only:
        cxs = [c for c in cxs if c["slug"] == args.only]

    idx = local_index()
    stats = Counter()
    rows = []
    for c in cxs:
        for it in get(f"/api/v1/posts?complex={c['slug']}&limit=100")["items"]:
            rows.append(audit_post(load_post(it, idx, stats), today))
        print(f"  수집 {c['name']} 누적 {len(rows)}편", file=sys.stderr, flush=True)
    print(f"  본문 출처: 로컬 팩 {stats['local']}편 · 상세 API {stats['detail']}편"
          f"(이 {stats['detail']}편은 조회수가 1씩 올랐다)", file=sys.stderr)

    # W4 고유성: 마스킹 후 다른 라이브 글과 너무 닮았다
    for a, b in combinations(rows, 2):
        s = jaccard(a["_tok"], b["_tok"])
        for x, y in ((a, b), (b, a)):
            if s >= SIM_WARN and s > x.get("_sim", 0):
                x["_sim"], x["warn"]["W4"] = s, f"{s:.2f} ↔ {y['ext']}"
    # W5 댓글 돌려쓰기: 같은 댓글 본문이 여러 글에 달렸다
    cnt = Counter(b for r in rows for b in r["comment_bodies"])
    for r in rows:
        dup = [b for b in r["comment_bodies"] if cnt[b] > 1]
        if dup:
            r["warn"]["W5"] = f"중복 댓글 {len(dup)}개: {dup[0][:30]}"

    n = len(rows)
    clean = [r for r in rows if not r["hard"]]
    by_check = Counter(k for r in rows for k in list(r["hard"]) + list(r["warn"]))
    by_cx = defaultdict(lambda: [0, 0])
    by_persona = defaultdict(lambda: [0, 0])
    for r in rows:
        by_cx[r["complex"]][0] += 1
        by_cx[r["complex"]][1] += bool(r["hard"])
        by_persona[r["persona"]][0] += 1
        by_persona[r["persona"]][1] += len(r["hard"])

    print(f"\n[품질 감사] {today} · 라이브 {n}편")
    print(f"하드 규칙 무결함 {len(clean)}편 ({len(clean) / max(n, 1) * 100:.0f}%)\n")
    names = {"Q1": "출처·확인일", "Q2": "사실/해석 분리", "Q3": "질문으로 닫기", "Q4": "제목 34자",
             "Q5": "마크다운", "Q6": "금지 표현", "Q7": "조사",
             "W1": "낡은 시점 표현", "W2": "문말 단조", "W3": "관점 댓글 부족",
             "W4": "다른 글과 유사", "W5": "댓글 돌려쓰기", "W6": "출처 확인일 없음",
             "W7": "체험 어투(문맥 판정)", "W8": "댓글 유실"}
    for k in sorted(names):
        print(f"  {k} {names[k]:12} {by_check.get(k, 0):>4}편")
    print("\n단지별 결함 글")
    for cx, (tot, bad) in sorted(by_cx.items()):
        print(f"  {cx:24}{bad:>3} / {tot}")
    print("\n페르소나별 결함 수 (상위 8)")
    for p, (tot, bad) in sorted(by_persona.items(), key=lambda x: -x[1][1])[:8]:
        print(f"  {p:16} 결함 {bad:>3} · 글 {tot}")
    print(f"\n반응: 조회 {sum(r['views'] for r in rows)} · 공감 {sum(r['likes'] for r in rows)} · "
          f"도움돼요 {sum(r['helpful'] for r in rows)} · 사람 댓글 {sum(r['human_comments'] for r in rows)}")

    if args.show:
        print(f"\n=== {args.show} ===")
        for r in rows:
            v = r["hard"].get(args.show) or r["warn"].get(args.show)
            if v:
                print(f"  [{r['complex']}] {r['ext']} | {r['title'][:28]} | {v}")

    out = REPO / "data" / "quality" / f"{today}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    for r in rows:
        r.pop("_tok", None); r.pop("_sim", None); r.pop("comment_bodies", None)
    out.write_text(json.dumps({
        "checked_at": datetime.now(KST).isoformat(timespec="seconds"),
        "posts": n, "clean": len(clean), "by_check": dict(by_check),
        "body_source": {"local_pack": stats["local"], "detail_api": stats["detail"]},
        "by_complex": {k: {"posts": v[0], "defective": v[1]} for k, v in by_cx.items()},
        "rows": rows,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n→ {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
