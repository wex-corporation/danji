#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""짧은 카드 생성기 — 공유 카드에 캡처되는 형태를 노린다.

왜 만들었나
  공유 카드(1200×630)에 들어가는 건 제목 하나다. 본문은 한 글자도 안 들어간다.
  그런데 기존 생성기는 전부 800자짜리 긴 글을 만든다. 캡처될 자리에 비해 글이 길다.
  긴 글은 검색 유입과 신뢰를 맡고, 짧은 카드는 캡처와 공유를 맡는다.

짧은 글의 함정
  뼈대가 같으면 마스킹 후 유사도가 긴 글보다 훨씬 빨리 오른다. 3문장짜리를
  같은 틀로 6장 찍으면 명세 8.3에서 그대로 반려된다.
  그래서 카드도 **단지마다 다른 지표 + 다른 뼈대**를 쓴다. 짧게 쓰되 틀은 6종이다.

지표 고르는 법
  특이값 생성기는 |z| 가 가장 큰 값을 고른다. 카드는 그럴 필요가 없다 —
  튀지 않는 값도 "우리 단지는 얼마인가"라는 질문에는 답이 된다.
  대신 그 단지가 이전 라운드에서 이미 쓴 지표는 피한다.

서모스탯 (명세 6.3)
  단지당 하루 2편. 게시된 피드를 조회해 그날 편수를 합산하고,
  여유가 없는 단지는 이번 배치에서 **빼고 그 사실을 보고한다.**

실행: python3 scripts/build_card_pack.py
"""

import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "content" / "card-w1.json"
INFO_DIR = REPO / "data" / "complex-info"
BASE = os.environ.get("BASE_URL", "https://danji.life")
NOW = "2026-08-21T17:20:00+09:00"
DAY = NOW[:10]

CX = {"olympic-park-foreon": "cx-olympic-park-foreon", "eunma": "cx-eunma",
      "helio-city": "cx-helio-city", "parkrio": "cx-parkrio",
      "ricents": "cx-ricents", "one-bailey": "cx-one-bailey"}

PERSONA = {
    "external_id": "wb-persona-num-compare",
    "handle": "숫자비교표",
    "avatar_label": "표",
    "tagline": "같은 잣대로 재지 않으면 비교가 아닙니다",
    "stance": "기준 통일",
    "expertise": ["공개 자료", "단지 비교"],
    "avatar_color": "#7c3aed",
}

SRC = {"label": "공동주택 기본 정보제공 서비스(K-apt) OpenAPI",
       "url": "https://www.data.go.kr/data/15058453/openapi.do", "publisher": "국토교통부"}
TOPIC = {"external_id": "wb-topic-2026-08-card", "title": "우리 단지는 얼마인가",
         "summary": "같은 잣대로 잰 값 하나를 짧게 놓는다. 판단은 사는 사람이 한다",
         "category": "생활", "heat": 3}

BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "뒤처", "부럽", "명문", "상위권",
             "가장 좋", "가장 나쁜", "최고의", "최하"]
BAN_COMPARE = ["보다 낫", "보다 좋", "보다 우수", "보다 편리"]
BAN_PRICE = ["억", "호가", "시세", "매수", "매도", "전망", "집값"]
BAN_VAGUE = ["인터넷에서", "알려져 있", "라고 한다", "찾아보니"]
BAD_RO = ["명로", "층로", "원로", "동로", "분로"]

MAX_BODY = 400   # 카드다. 길어지면 카드가 아니다
MAX_TITLE = 34   # 공유 카드가 2줄까지만 담는다


def _batchim(w):
    for ch in reversed(w.rstrip(")]}」』\"' ")):
        if "가" <= ch <= "힣":
            return (ord(ch) - 0xAC00) % 28 != 0
        if ch.isdigit():
            return ch in "13678" or ch == "0"
    return False


JOSA_PAIRS = {"은는", "이가", "을를", "과와", "아야"}


def J(word, pair):
    if pair not in JOSA_PAIRS:
        raise ValueError(f"J()는 조사쌍만 받는다. '{pair}'는 쌍이 아니다")
    return word + (pair[0] if _batchim(word) else pair[1])


def info(slug):
    return json.loads((INFO_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def published_today(slug, day):
    """그날 이미 게시된 편수를 서버에서 센다. 팩 안에서만 세면 팩 사이 초과를 못 잡는다."""
    try:
        req = urllib.request.Request(f"{BASE}/api/v1/posts?complex={slug}&limit=100",
                                     headers={"User-Agent": "danji-content-agent/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            items = json.load(r)["items"]
    except Exception as exc:  # noqa: BLE001
        print(f"[중단] 피드 조회 실패로 서모스탯을 확인할 수 없습니다: {exc}", file=sys.stderr)
        raise SystemExit(1)
    return sum(1 for i in items if (i.get("published_at") or "").startswith(day))


# ── 카드 뼈대 6종 ──────────────────────────────────────────────
# 짧게 쓰되 구조는 서로 다르게 한다. 문장 수, 어순, 질문 방식이 각각 다르다.

def c_dong(name, i, peers):
    v = i["dong_count"]
    lo, hi = min(peers.values()), max(peers.values())
    return (f"""{J(name, '은는')} {v}개동입니다. {i['household_count']:,}세대가 여기에 나뉘어 있습니다.

같은 잣대로 잰 파일럿 6곳은 {lo}개동에서 {hi}개동 사이입니다. K-apt 공개정보 기준입니다.

동이 많으면 단지 안에서 걷는 거리가 길어집니다. 사시는 동에서 정문까지 몇 분 걸리시나요?""")


def c_year(name, i, peers):
    y = int(i["use_approval_date"][:4])
    others = sorted(v for k, v in peers.items() if v != y)
    return (f"""사용승인 {y}년. K-apt에 그렇게 등록돼 있습니다.

파일럿 6곳 중 나머지 다섯은 {min(others)}년에서 {max(others)}년 사이입니다. {y - min(others) if y > min(others) else min(others) - y}년 차이가 나는 셈입니다.

준공 연도는 설계 기준이 언제 것이냐를 정합니다. 그 시대가 남긴 것 중에 지금도 괜찮다 싶은 게 있나요?""")


def c_cctv(name, i, peers):
    v = round(i["cctv_count"] / i["household_count"], 2)
    lo, hi = min(peers.values()), max(peers.values())
    return (f"""CCTV {i['cctv_count']:,}대, {i['household_count']:,}세대. 세대당 {v}대입니다.

파일럿 6곳은 세대당 {lo}대에서 {hi}대 사이에 있습니다.

다만 이건 등록 대수일 뿐입니다. 어디를 비추는지, 녹화가 며칠 남는지는 공개돼 있지 않습니다. 필요할 때 영상을 받아 보신 적 있으신가요?""")


def c_floor(name, i, peers):
    v = i["top_floor"]
    lo, hi = min(peers.values()), max(peers.values())
    return (f"""최고 {v}층. 파일럿 6곳은 {lo}층에서 {hi}층 사이입니다.

K-apt 공개정보에 있는 값이고, 단지 전체에서 가장 높은 층을 말합니다. 모든 동이 그 높이라는 뜻은 아닙니다.

층이 높아지면 엘리베이터 대기와 조망이 같이 달라집니다. 어느 쪽이 더 크게 느껴지시나요?""")


def c_area(name, i, peers):
    ratio = i["billed_area_m2"] / i["private_area_sum_m2"]
    lo, hi = min(peers.values()), max(peers.values())
    return (f"""같은 집을 두 면적으로 부릅니다. {J(name, '은는')} 전용면적 합 {i['private_area_sum_m2']:,.0f}㎡, 관리비 부과면적 {i['billed_area_m2']:,.0f}㎡입니다. 부과면적이 전용의 {ratio:.2f}배입니다.

파일럿 6곳은 {lo:.2f}배에서 {hi:.2f}배 사이입니다.

평당가든 관리비든 어느 면적으로 나눴는지에 따라 값이 달라집니다. 고지서에 적힌 면적이 몇 ㎡인지 보신 적 있으신가요?""")


def c_staff(name, i, peers):
    v = round(i["household_count"] / i["staff_total"], 1)
    lo, hi = min(peers.values()), max(peers.values())
    return (f"""관리 인력 {i['staff_total']}명. 일반관리 {i['staff_manage']}명, 경비 {i['staff_security']}명, 청소 {i['staff_clean']}명입니다.

{i['household_count']:,}세대로 나누면 1명이 {v}세대를 맡습니다. 파일럿 6곳은 {lo}세대에서 {hi}세대 사이입니다.

인력 수는 관리비 고지서와 바로 이어집니다. 지금 인원이 적당하다고 보시나요?""")


# (지표 키, 값 함수, 뼈대, 제목)
METRICS = {
    "동수": (lambda i: i["dong_count"], c_dong,
             lambda i, v: f"{v}개동에 {i['household_count']:,}세대. 정문까지 몇 분 걸리시나요?"),
    "준공연도": (lambda i: int(i["use_approval_date"][:4]), c_year,
                 lambda i, v: f"사용승인 {v}년. 6곳 중 이 단지만 {v // 10 % 10}0년대"),
    "세대당 CCTV": (lambda i: round(i["cctv_count"] / i["household_count"], 2), c_cctv,
                    lambda i, v: f"세대당 CCTV {v}대. 필요할 때 영상 받아 보셨나요?"),
    "최고층": (lambda i: i["top_floor"], c_floor,
               lambda i, v: f"최고 {v}층. 대기와 조망 중 어느 쪽이 더 크게 느껴지나요?"),
    "부과면적 비율": (lambda i: round(i["billed_area_m2"] / i["private_area_sum_m2"], 3), c_area,
                      lambda i, v: f"같은 집을 부르는 면적이 {v:.2f}배 차이 납니다"),
    "관리인력1인당 세대": (lambda i: round(i["household_count"] / i["staff_total"], 1), c_staff,
                          lambda i, v: f"관리 인력 1명이 {v}세대. 지금 인원이 적당한가요?"),
}

# 이 배치의 배정. 단지마다 지표가 달라야 마스킹 후에도 서로 다른 글이 된다.
# 그리고 그 단지가 이전 라운드에서 이미 쓴 지표는 피한다.
ASSIGN = [
    ("olympic-park-foreon", "동수"),
    ("eunma", "준공연도"),
    ("helio-city", "세대당 CCTV"),
    ("parkrio", "최고층"),
    ("ricents", "부과면적 비율"),
    ("one-bailey", "관리인력1인당 세대"),
]

TIMES = ["T08:40:00+09:00", "T10:10:00+09:00", "T11:40:00+09:00",
         "T13:20:00+09:00", "T15:00:00+09:00", "T16:30:00+09:00"]

COMMENTS = [
    ("wb-persona-appraisal-check", "같은 항목을 같은 기준으로 재야 비교가 됩니다. 이 표는 그것만 맞춰 둔 값이에요.", "기준 통일"),
    ("wb-persona-field-scout", "숫자가 생활에서 어떻게 나타나는지는 사시는 분만 압니다. 그 대목이 비어 있어요.", "현장 검증 요청"),
]


def build():
    rows = {s: info(s) for s in CX}
    bundles, skipped = [], []
    idx = 0
    for slug, key in ASSIGN:
        live = published_today(slug, DAY)
        if live >= 2:
            skipped.append((slug, live))
            continue
        getter, frame, title_fn = METRICS[key]
        peers = {}
        for s, i in rows.items():
            try:
                peers[s] = getter(i)
            except (KeyError, TypeError, ZeroDivisionError):
                continue          # 값이 없는 단지는 범위에서 뺀다. 지어내지 않는다
        i = rows[slug]
        v = getter(i)
        body = frame(i["complex_name"], i, peers)
        ext = f"card-2026-08-{slug}"
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-v1",
            "payload": {
                "complex_external_id": CX[slug], "topic": TOPIC,
                "post": {
                    "external_id": ext, "complex_external_id": CX[slug],
                    "persona_external_id": PERSONA["external_id"], "category": "생활",
                    "title": title_fn(i, v), "summary": body.split("\n\n")[0][:220],
                    "body": body, "verification": "verified",
                    "source_note": f"2026. 8. 16. 조회 · K-apt 공개정보 기준 · 파일럿 {len(peers)}개 단지와 같은 항목을 비교",
                    "sources": [SRC],
                    "published_at": DAY + TIMES[idx], "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{n}", "persona_external_id": pid,
                     "body": b, "stance": s2, "position": n}
                    for n, (pid, b, s2) in enumerate(COMMENTS)
                ],
            },
        })
        idx += 1

    for slug, live in skipped:
        print(f"[건너뜀] {slug}: 오늘 이미 {live}편 — 서모스탯 한도(2편)에 여유가 없습니다",
              file=sys.stderr)

    return {
        "meta": {"name": "짧은 카드 팩 (w1)", "posts": len(bundles), "built_at": DAY,
                 "assigned": {s: k for s, k in ASSIGN},
                 "skipped": [{"slug": s, "already": n} for s, n in skipped],
                 "purpose": "공유 카드에 캡처되는 짧은 형식. 제목이 곧 캡처물이다",
                 "note": "짧은 글은 뼈대가 같으면 유사도가 빨리 오른다. 단지마다 지표와 뼈대를 다르게 준다"},
        "personas": [PERSONA],
        "bundles": bundles,
    }


def validate(pack):
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    comments = [c for b in pack["bundles"] for c in b["payload"]["comments"]]
    reg = {PERSONA["external_id"], "wb-persona-appraisal-check", "wb-persona-field-scout"}

    ids = [p["external_id"] for p in posts] + [c["external_id"] for c in comments]
    if len(set(ids)) != len(ids):
        errs.append("external_id 중복")
    if len({p["published_at"] for p in posts}) != len(posts):
        errs.append("published_at 중복")

    keys = [pack["meta"]["assigned"][p["external_id"].rsplit("card-2026-08-", 1)[-1]] for p in posts]
    if len(set(keys)) != len(keys):
        errs.append(f"배치 안에서 지표가 겹친다 — 마스킹하면 같은 글이 된다: {Counter(keys)}")

    for p in posts:
        t = p["title"] + "\n" + p["body"]
        for w in BAN_JUDGE + BAN_COMPARE + BAN_PRICE + BAN_VAGUE + BAD_RO:
            if w in t:
                errs.append(f"금지 표현 '{w}': {p['external_id']}")
        if "**" in t:
            errs.append(f"마크다운 강조는 렌더링되지 않는다: {p['external_id']}")
        if not p["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {p['external_id']}")
        if len(p["title"]) > MAX_TITLE:
            errs.append(f"제목 {len(p['title'])}자 — 공유 카드 2줄을 넘는다: {p['external_id']}")
        if len(p["body"]) > MAX_BODY:
            errs.append(f"본문 {len(p['body'])}자 — 카드는 {MAX_BODY}자 이내: {p['external_id']}")
        if p["verification"] == "verified" and not p["sources"]:
            errs.append(f"verified인데 sources 없음: {p['external_id']}")
        if p["published_at"] > NOW:
            errs.append(f"미래 시각: {p['external_id']}")
        if p["persona_external_id"] not in reg:
            errs.append(f"미등록 페르소나: {p['persona_external_id']}")
    for c in comments:
        if c["persona_external_id"] not in reg:
            errs.append(f"미등록 페르소나: {c['persona_external_id']}")

    per = Counter((p["complex_external_id"], p["published_at"][:10]) for p in posts)
    over = {f"{cx} {d}": n for (cx, d), n in per.items() if n > 1}
    if over:
        errs.append(f"한 단지에 카드가 둘 이상: {over}")
    return errs


def main():
    pack = build()
    if not pack["bundles"]:
        print("만들 카드가 없습니다. 서모스탯 여유가 있는 단지가 없습니다.", file=sys.stderr)
        return 1
    errs = validate(pack)
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    OUT.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{'단지':22}{'지표':16}{'제목자수':>6}{'본문자수':>7}  제목")
    for b in pack["bundles"]:
        p = b["payload"]["post"]
        slug = p["external_id"].rsplit("card-2026-08-", 1)[-1]
        print(f"  {slug:20}{pack['meta']['assigned'][slug]:16}{len(p['title']):>6}{len(p['body']):>7}  {p['title']}")
    print(f"\n카드 {len(pack['bundles'])}장 · 댓글 {sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
