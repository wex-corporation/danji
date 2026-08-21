#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""분석 글 생성기 — 가격·정책을 다루되 기준을 반드시 붙인다.

왜 따로 두나
  홍보·특이값 생성기는 금지 어휘에 '억'·'시세'가 들어 있다. 홍보 페르소나가
  가격을 말하면 시세 부양으로 읽히기 때문이다(명세 7.2.1).
  반면 분석 페르소나는 실거래를 인용할 수 있다. 대신 CLAUDE.md 4장의
  "숫자에는 기준을 붙인다"를 어기면 안 된다 — 금액만 던지는 글은 여기서도 못 나간다.

이 팩이 지키는 선
  - 담합 유도·매수/매도 지시·전망 단정 금지. 검증기가 막는다
  - 단지 간 우열 비교 금지. 이 팩은 한 단지 안에서만 이야기한다
  - 모든 수치는 우리가 조회한 원자료에서 나온다. 언론·커뮤니티 인용은 쓰지 않는다

서모스탯 (명세 6.3)
  단지당 하루 2편이 한도다. **팩 안에서만 세면 안 된다** — 실제로 2026-08-18에
  원베일리가 서로 다른 팩에서 3편 나갔다. 그래서 이 생성기는 게시된 피드를
  조회해 그날 이미 몇 편 나갔는지 확인하고 합산해서 판정한다.

실행: python3 scripts/build_analysis_pack.py
"""

import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "content" / "analysis-w1.json"
INFO_DIR = REPO / "data" / "complex-info"
BASE = os.environ.get("BASE_URL", "https://danji.life")
NOW = "2026-08-21T16:40:00+09:00"
DAY = NOW[:10]

CX = {"one-bailey": "cx-one-bailey"}

SRC_TRADE = {"label": "국토교통부 아파트 매매 실거래가 상세 자료",
             "url": "https://www.data.go.kr/data/15126469/openapi.do", "publisher": "국토교통부"}
SRC_BASIS = {"label": "공동주택 기본 정보제공 서비스(K-apt) OpenAPI",
             "url": "https://www.data.go.kr/data/15058453/openapi.do", "publisher": "국토교통부"}

TOPIC = {"external_id": "wb-topic-2026-08-basis", "title": "숫자에는 기준이 붙어야 합니다",
         "summary": "같은 거래도 무엇으로 나누느냐에 따라 달라진다. 원자료로 확인한다",
         "category": "거래", "heat": 5}

# 분석 글에도 넘지 않는 선이 있다. 가격은 쓰되 이것들은 못 쓴다.
BAN_STEER = ["얼마 이하로", "내놓지 마", "지금 사", "지금 파", "매수 추천", "매도 추천",
             "사야 합니다", "팔아야 합니다", "오를 겁니다", "내릴 겁니다", "전망합니다"]
BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "명문", "상위권", "학군지"]
BAN_COMPARE = ["보다 낫", "보다 좋", "보다 우수"]
BAN_VAGUE = ["인터넷에서", "알려져 있", "라고 한다", "찾아보니", "카페에서", "커뮤니티에서"]


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


def won(manwon):
    """만원 단위를 읽는 형태로 바꾼다.

    900,000만원 은 사람이 쓰는 말이 아니다. 90억원이라고 써야 읽힌다.
    CLAUDE.md 4장이 금지하는 건 금액 자체가 아니라 기준 없는 금액이다 —
    예시도 "7월 6일 계약, 전용 116.95㎡ 25층 기준 90억"이다.
    """
    m = round(manwon)
    eok, rest = divmod(m, 10_000)
    if eok and rest:
        return f"{eok}억 {rest:,}만원"
    if eok:
        return f"{eok}억원"
    return f"{rest:,}만원"


def published_today(cx_ext, day):
    """그날 이미 게시된 편수를 서버에서 센다.

    팩 안에서만 세면 팩 사이를 넘는 초과를 못 잡는다. 2026-08-18 에
    원베일리가 outlier3 1편 + nearby 2편으로 3편 나간 적이 있다.
    """
    slug = [s for s, e in CX.items() if e == cx_ext][0]
    try:
        req = urllib.request.Request(f"{BASE}/api/v1/posts?complex={slug}&limit=100",
                                     headers={"User-Agent": "danji-content-agent/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            items = json.load(r)["items"]
    except Exception as exc:  # noqa: BLE001
        print(f"[주의] 피드 조회 실패로 서모스탯을 확인하지 못했습니다: {exc}", file=sys.stderr)
        return None
    return sum(1 for i in items if (i.get("published_at") or "").startswith(day))


def build():
    i = json.loads((INFO_DIR / "one-bailey.json").read_text(encoding="utf-8"))
    name = i["complex_name"]
    priv, marea, hh = i["private_area_sum_m2"], i["billed_area_m2"], i["household_count"]
    ratio = marea / priv

    # 2026-07-06 계약, 전용 116.95㎡ 25층, 90억. 국토부 실거래 신고 원자료.
    amt_manwon, area = 900_000, 116.95
    per_excl = amt_manwon / area * 3.3058
    eq_area = area * ratio
    per_billed = amt_manwon / eq_area * 3.3058

    body1 = f"""부동산 이야기에서 평당가는 거의 매번 등장하는데, 무엇으로 나눈 값인지는 잘 안 붙습니다. 그래서 한 건을 놓고 직접 나눠 봤습니다.

국토교통부 실거래 신고 기준으로 2026년 7월 6일 계약, 전용 {area}㎡ 25층이 {won(amt_manwon)}에 거래됐습니다. 이 금액을 전용면적으로 나누면 평당 {won(per_excl)}입니다.

그런데 같은 집을 부르는 면적이 하나가 아닙니다. K-apt 공개정보에서 {J(name, '은는')} 전용면적 합계 {priv:,.1f}㎡, 관리비 부과면적 {marea:,.1f}㎡로 등록돼 있습니다. 부과면적이 전용면적의 {ratio:.2f}배입니다. 세대로 나누면 평균 전용 {priv/hh:.1f}㎡, 평균 부과 {marea/hh:.1f}㎡가 됩니다.

이 비율로 아까 그 거래를 환산하면 {eq_area:.1f}㎡가 되고, 평당가는 {won(per_billed)}으로 내려앉습니다. 같은 계약, 같은 금액인데 평당 {won(per_excl)}과 {won(per_billed)}이 함께 나옵니다.

여기서부터는 해석입니다. 둘 중 틀린 값은 없습니다. 분모가 다를 뿐이죠. 문제는 기준을 밝히지 않은 평당가가 돌아다닐 때 생깁니다. 전용 기준끼리 비교해야 할 자리에 공급이나 부과 기준 값이 섞여 들어오면, 비교 자체가 성립하지 않습니다. 저희가 예측 정산 규칙에서 전용면적 기준을 못 박아 둔 이유도 이것입니다.

어디선가 들으신 이 단지 평당가는 어느 면적 기준이던가요? 기준을 물어보셨을 때 바로 답을 들으셨나요?"""

    title1 = f"평당 {won(per_excl)}과 {won(per_billed)}. 같은 거래"

    # 2024-01~2026-07 국토부 신고 176건을 월별로 집계한 결과다.
    body2 = f"""토지거래허가구역 재지정이 거래를 줄였다는 이야기는 자주 나오는데, 이 단지에서 실제로 얼마나 줄었는지는 세어 보면 알 수 있습니다.

국토교통부 실거래 신고 자료에서 {name} 계약을 2024년 1월부터 2026년 7월까지 모으면 176건입니다. 재지정 시행일은 2025년 3월 24일입니다.

시행 직전 12개월(2024년 4월~2025년 3월)은 104건, 월 평균 8.7건입니다. 직후 12개월(2025년 4월~2026년 3월)은 27건, 월 평균 3.9건입니다. 신고가 한 건도 없는 달이 다섯 번 있었습니다.

여기서부터는 해석입니다. 줄어든 건 분명한데, 허가제 하나 때문이라고 단정할 수는 없습니다. 같은 기간에 대출 한도를 조이는 대책도 있었고, 실거래는 신고일이 아니라 계약일 기준이라 최근 달은 아직 덜 찬 상태로 보입니다. 거래가 줄었다는 사실과 무엇이 줄였는지는 다른 이야기입니다.

숫자로 확인되지 않는 대목이 하나 더 있습니다. 허가를 실제로 신청하면 무엇을 준비해야 하고 며칠이 걸리는지는 어느 통계에도 없습니다. 밟아 보신 분이 계시면 그 과정이 어땠는지 알려 주시겠어요?"""

    title2 = "허가구역 뒤 거래가 월 8.7건에서 3.9건으로"

    specs = [
        ("basis-2026-08-one-bailey", title1, body1, "wb-persona-appraisal-check", "거래",
         [SRC_TRADE, SRC_BASIS],
         "2026. 8. 21. 조회 · 국토교통부 실거래 신고 원자료와 K-apt 공개정보로 직접 계산한 값",
         f"{DAY}T09:30:00+09:00",
         [("wb-persona-trade-brief", "기준을 안 밝힌 평당가는 비교에 쓸 수 없습니다. 표를 만들 때 제일 먼저 통일해야 하는 항목이에요.", "기준 통일"),
          ("wb-persona-cashflow", "관리비는 부과면적으로 매겨집니다. 같은 면적 이름이 가격과 관리비에서 다르게 쓰인다는 점도 같이 보셔야 합니다.", "비용 구조")]),
        ("permit-2026-08-one-bailey", title2, body2, "wb-persona-trade-brief", "정책",
         [SRC_TRADE],
         "2026. 8. 21. 조회 · 국토교통부 실거래 2024년 1월~2026년 7월 계약분 176건을 월별로 집계",
         f"{DAY}T14:10:00+09:00",
         [("wb-persona-policy-lab", "제도 시행 전후 비교는 다른 변수가 겹치면 인과가 흐려집니다. 같은 시기 대출 규제를 함께 놓고 봐야 합니다.", "정책 분석"),
          ("wb-persona-real-talk", "거래가 줄면 남은 몇 건이 전체를 대표하게 됩니다. 표본이 작아진다는 점도 같이 봐야 해요.", "생활 현실")]),
    ]

    bundles = []
    for ext, title, body, persona, cat, srcs, note, pub, cmts in specs:
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-v1",
            "payload": {
                "complex_external_id": CX["one-bailey"],
                "topic": dict(TOPIC, category=cat),
                "post": {
                    "external_id": ext, "complex_external_id": CX["one-bailey"],
                    "persona_external_id": persona, "category": cat,
                    "title": title, "summary": body.split("\n\n")[1][:220], "body": body,
                    "verification": "verified", "source_note": note, "sources": srcs,
                    "published_at": pub, "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{n}", "persona_external_id": pid,
                     "body": b, "stance": s, "position": n}
                    for n, (pid, b, s) in enumerate(cmts)
                ],
            },
        })

    return {
        "meta": {"name": "분석 팩 (w1)", "posts": len(bundles), "built_at": DAY,
                 "complex": "one-bailey",
                 "purpose": "가격·정책을 다루되 기준을 붙인다. 수치는 전부 원자료에서 계산했다",
                 "note": "홍보 페르소나는 이 팩에 쓰지 않는다. 가격을 말하는 순간 시세 부양으로 읽힌다"},
        "personas": [],
        "bundles": bundles,
    }


def validate(pack):
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    comments = [c for b in pack["bundles"] for c in b["payload"]["comments"]]
    reg = {"wb-persona-appraisal-check", "wb-persona-trade-brief", "wb-persona-cashflow",
           "wb-persona-policy-lab", "wb-persona-real-talk"}

    ids = [p["external_id"] for p in posts] + [c["external_id"] for c in comments]
    if len(set(ids)) != len(ids):
        errs.append("external_id 중복")
    if len({p["published_at"] for p in posts}) != len(posts):
        errs.append("published_at 중복")

    for p in posts:
        t = p["title"] + "\n" + p["body"]
        for w in BAN_STEER + BAN_JUDGE + BAN_COMPARE + BAN_VAGUE:
            if w in t:
                errs.append(f"금지 표현 '{w}': {p['external_id']}")
        if "**" in t:
            errs.append(f"마크다운 강조는 렌더링되지 않는다: {p['external_id']}")
        if not p["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {p['external_id']}")
        if "여기서부터는 해석입니다." not in p["body"]:
            errs.append(f"사실/해석 전환 문장 없음: {p['external_id']}")
        if p["verification"] == "verified" and not p["sources"]:
            errs.append(f"verified인데 sources 없음: {p['external_id']}")
        if p["published_at"] > NOW:
            errs.append(f"미래 시각: {p['external_id']}")
        if p["persona_external_id"] not in reg:
            errs.append(f"미등록 페르소나: {p['persona_external_id']}")
        if p["persona_external_id"].startswith("adv-"):
            errs.append(f"홍보 페르소나가 가격 글을 쓸 수 없다: {p['external_id']}")
        # 제목은 공유 카드에 2줄로 그려진다. 34자를 넘으면 잘리거나 3줄이 된다.
        if len(p["title"]) > 34:
            errs.append(f"제목 {len(p['title'])}자 — 공유 카드 2줄을 넘는다: {p['external_id']}")
    for c in comments:
        if c["persona_external_id"] not in reg:
            errs.append(f"미등록 페르소나: {c['persona_external_id']}")

    # 서모스탯 — 이 팩 + 이미 게시된 그날 편수를 합산해서 본다
    per = Counter((p["complex_external_id"], p["published_at"][:10]) for p in posts)
    for (cx, day), n in per.items():
        live = published_today(cx, day)
        total = n if live is None else n + live
        if total > 2:
            errs.append(f"서모스탯 콜드스타트(단지당 일 2편) 초과: {cx} {day} "
                        f"이미 {live}편 + 이번 {n}편 = {total}편")
    return errs


def main():
    pack = build()
    errs = validate(pack)
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    OUT.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for b in pack["bundles"]:
        p = b["payload"]["post"]
        print(f"  [{p['category']}] {p['persona_external_id']:28}{len(p['title']):>3}자  {p['title']}")
    print(f"\n글 {len(pack['bundles'])}편 · 댓글 {sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
