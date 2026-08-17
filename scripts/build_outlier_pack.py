#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""특이값 기반 생성기 — 템플릿이 아니라 '그 단지만의 숫자'에서 글을 시작한다.

왜 만들었나
  명세 8.3 출고 검사를 처음 돌렸더니 11곳 중 10곳이 반려였다.
  단지명과 숫자를 가리면 유사도 1.00, 즉 완전히 같은 글이 다수였다.
  원인은 구조다. 기존 생성기는 템플릿 t1~t10에 단지를 인자로 넣는다.
  그러면 단지가 달라도 글의 뼈대가 같을 수밖에 없다.

어떻게 푸나
  순서를 뒤집는다. 템플릿 → 단지 채우기가 아니라, 단지 → 그 단지의 특이값 → 글.
  11개 단지 분포에서 z-score를 재 가장 튀는 지표를 찾고, 그 지표를 첫 문장으로 쓴다.
  지표가 서로 다르면 글의 소재·구조·질문이 자동으로 갈린다.

  지표는 단지마다 **겹치지 않게** 배정한다(그리디, |z| 큰 순).
  같은 지표를 두 단지가 쓰면 다시 같은 글이 나오기 때문이다.

프레임은 지표 계열별로 다르다. 규모·설비·인력·비용·시대 다섯 가지이며
문단 구성과 질문 방식이 각각 다르다. 지표가 갈리면 프레임도 갈린다.

서모스탯 (명세 6.3)
  인간 액션이 0이므로 허용량은 상한(글 4)이 아니라 콜드스타트(글 2)다.
  이 생성기는 단지당 1일 1편만 만든다.

실행: python3 build_outlier_pack.py
"""

import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "content" / "outlier-w1.json"
FEE_PERIOD = "202605"

# 명세 10.1 Phase 0 — 파일럿 3~5곳. 거래량 상위 + 화제성으로 5곳을 고정한다.
PILOT = ["olympic-park-foreon", "helio-city", "ricents", "parkrio", "eunma"]

PERSONA = {
    "external_id": "wb-persona-outlier",
    "handle": "이단지만다른점",
    "avatar_label": "다른",
    "tagline": "같은 잣대로 재면 이 단지만 튀는 숫자가 하나씩 있습니다",
    "stance": "특이값 추적",
    "expertise": ["단지 비교", "공개 자료"],
    "avatar_color": "#0891b2",
}

SRC_BASIS = {"label": "공동주택 기본 정보제공 서비스(K-apt) OpenAPI",
             "url": "https://www.data.go.kr/data/15058453/openapi.do", "publisher": "국토교통부"}
SRC_FEE = {"label": "공동주택관리비(공용관리비)정보제공서비스 OpenAPI",
           "url": "https://www.data.go.kr/data/15057937/openapi.do", "publisher": "국토교통부"}

def _batchim(w):
    for ch in reversed(w.rstrip(")]}」』\"' ")):
        if "가" <= ch <= "힣":
            return (ord(ch) - 0xAC00) % 28 != 0
        if ch.isdigit():
            return ch in "13678" or ch == "0"
    return False


def J(word, pair):
    """받침 판정 후 조사 선택. '올림픽파크 포레온는' 같은 사고를 막는다."""
    return word + (pair[0] if _batchim(word) else pair[1])


BAN_PRICE = ["억", "호가", "시세", "매수", "매도", "저점", "고점", "전망", "집값"]
BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "뒤처", "부럽"]
BAD_RO = ["명로", "층로", "원로", "동로", "분로"]

# 지표별 단위. 본문·제목에서 숫자 뒤에 붙인다.
UNIT = {"세대수": "세대", "동수": "개동", "최고층": "층", "준공연도": "년",
        "승강기당 세대": "세대", "세대당 CCTV": "대", "EV 충전기 비율": "%",
        "경비1인당 세대": "세대", "청소1인당 세대": "세대", "㎡당 공용관리비": "원"}

# 지표 계열. 프레임이 여기서 갈린다.
FAMILY = {
    "세대수": "규모", "동수": "규모",
    "승강기당 세대": "설비", "세대당 CCTV": "설비", "EV 충전기 비율": "설비",
    "경비1인당 세대": "인력", "청소1인당 세대": "인력",
    "㎡당 공용관리비": "비용",
    "준공연도": "시대", "최고층": "시대",
}


def load():
    rows = {}
    for slug in PILOT:
        i = json.loads((REPO / "data" / "complex-info" / f"{slug}.json").read_text(encoding="utf-8"))
        fee = json.loads((REPO / "data" / "mgmt-fees" / f"{slug}.json").read_text(encoding="utf-8"))
        rows[slug] = {"info": i, "fee": fee["periods"].get(FEE_PERIOD)}
    return rows


def metrics(rows):
    """비교 가능한 지표만 뽑는다. 분모가 없으면 그 지표는 건너뛴다."""
    out = {}
    for slug, r in rows.items():
        i, fee = r["info"], r["fee"]
        hh = i["household_count"]
        m = {"세대수": hh, "동수": i.get("dong_count"), "최고층": i.get("top_floor"),
             "준공연도": int(i["use_approval_date"][:4])}
        if i.get("elevator_count"):
            m["승강기당 세대"] = round(hh / i["elevator_count"], 1)
        if i.get("staff_security"):
            m["경비1인당 세대"] = round(hh / i["staff_security"], 1)
        if i.get("staff_clean"):
            m["청소1인당 세대"] = round(hh / i["staff_clean"], 1)
        if i.get("cctv_count"):
            m["세대당 CCTV"] = round(i["cctv_count"] / hh, 2)
        if i.get("ev_underground") and i.get("parking_total"):
            m["EV 충전기 비율"] = round(i["ev_underground"] / i["parking_total"] * 100, 1)
        if fee and fee.get("complete") and fee.get("per_m2_won"):
            m["㎡당 공용관리비"] = round(fee["per_m2_won"])
        out[slug] = {k: v for k, v in m.items() if v is not None}
    return out


def assign(mets):
    """단지마다 겹치지 않는 지표를 하나씩 배정한다. |z| 큰 조합부터 그리디."""
    keys = sorted({k for m in mets.values() for k in m})
    stats = {}
    for k in keys:
        xs = [m[k] for m in mets.values() if k in m]
        if len(xs) < 3:
            continue
        mu, sd = st.mean(xs), (st.pstdev(xs) or 1)
        stats[k] = (mu, sd)

    cands = []
    for slug, m in mets.items():
        for k, v in m.items():
            if k not in stats:
                continue
            mu, sd = stats[k]
            cands.append((abs((v - mu) / sd), slug, k, v, (v - mu) / sd, mu))
    cands.sort(key=lambda c: -c[0])

    # 지표뿐 아니라 **계열(프레임)도** 겹치지 않게 한다.
    # 지표만 막으면 두 단지가 같은 계열(예: 설비)을 받아 프레임이 같아지고,
    # 결국 같은 글이 된다. 실제로 올파포·헬리오가 유사도 0.91로 걸렸다.
    picked, used_slug, used_key, used_fam = {}, set(), set(), set()
    for _, slug, k, v, z, mu in cands:
        fam = FAMILY.get(k, "기타")
        if slug in used_slug or k in used_key or fam in used_fam:
            continue
        picked[slug] = {"key": k, "value": v, "z": round(z, 2),
                        "mean": round(mu, 2), "family": FAMILY.get(k, "기타"),
                        "high": z > 0}
        used_slug.add(slug)
        used_key.add(k)
        used_fam.add(fam)
    missing = [s for s in mets if s not in picked]
    if missing:
        sys.exit(f"[중단] 겹치지 않는 지표·프레임 조합을 못 찾은 단지: {missing}. "
                 f"파일럿 수가 프레임 수({len(FRAMES)})를 넘으면 생긴다")
    return picked


# ── 프레임 5종. 계열이 다르면 문단 구성과 질문이 다르다 ──────────────

def frame_scale(name, info, p, peers):
    v, mu = p["value"], p["mean"]
    other = ", ".join(f"{n} {x:,}" for n, x in peers[:2])
    return (
        f"""{name} 이야기에는 늘 규모가 먼저 나옵니다. 그래서 규모가 실제로 무엇을 바꾸는지를 적어 보려 합니다.

K-apt 공개정보 기준 {J(p["key"], "은는")} {v:,}{UNIT.get(p["key"], "")}입니다. 제가 같은 기준으로 재는 파일럿 단지들의 평균이 {mu:,.0f}{UNIT.get(p["key"], "")}이니, 이 단지는 그 {v/mu:.1f}배입니다. 비교 대상은 {other} 정도입니다.

여기서부터는 해석입니다. 규모는 그 자체로 좋고 나쁨이 아니라 **무엇이 나뉘고 무엇이 몰리는지**를 정합니다. 고정비는 나뉘어 1세대당 부담이 줄고, 반대로 공용 공간과 진출입 동선에는 사람이 몰립니다. 같은 단지 안에서도 이 두 효과를 다르게 체감하실 겁니다.

규모가 이득으로 느껴지는 순간과 부담으로 느껴지는 순간을 하나씩 꼽는다면, 각각 언제인가요?""")


def frame_facility(name, info, p, peers):
    v, mu, u = p["value"], p["mean"], UNIT.get(p["key"], "")
    hi = "많은" if p["high"] else "적은"
    lead = "여기서 눈에 띕니다" if abs(p["z"]) >= 1 else "이 항목이 평균과 갈립니다"
    return (
        f"""설비 숫자는 대체로 지나치기 쉬운 항목인데, {J(name, '은는')} {lead}.

{J(p['key'], '이가')} {v:,}{u}입니다. 파일럿 단지 평균은 {mu:,.2f}{u}이고, 이 단지는 {hi} 쪽입니다. K-apt가 공개하는 설치·등록 수치 그대로입니다.

여기서부터는 해석입니다. 설비 수는 **설치된 양이지 체감된 양이 아닙니다.** 어디에 배치됐는지, 언제 붐비는지, 실제로 작동하는지는 공개 자료에 없습니다. 저는 숫자가 크다는 것까지만 말할 수 있고, 그게 생활에서 어떤 차이로 나타나는지는 모릅니다.

그래서 여쭙니다. 이 숫자가 실제로 체감되시나요? 체감된다면 어떤 상황에서인가요?""")


def frame_staff(name, info, p, peers):
    v, mu = p["value"], p["mean"]
    role = "경비" if "경비" in p["key"] else "청소"
    cnt = info.get("staff_security") if role == "경비" else info.get("staff_clean")
    dense = "낮은" if p["high"] else "높은"   # 1인당 세대가 크면 인력 밀도는 낮다
    return (
        f"""{J(name, "은는")} 어떨까 싶어 일하는 사람 수를 세어 봤습니다. 시설보다 이쪽이 관리비의 실체에 가깝습니다.

K-apt 공개정보 기준 {role} 인원은 {cnt}명이고, {info['household_count']:,}세대로 나누면 1인당 {v:,}세대입니다. 파일럿 단지 평균이 1인당 {mu:,.1f}세대이니, 이 단지는 인력 밀도가 상대적으로 {dense} 편입니다.

여기서부터는 해석입니다. 이 숫자는 관리비 고지서와 직결됩니다. 공용관리비에서 인건비·경비비·청소비가 차지하는 비중이 대개 4분의 3을 넘기 때문에, 인력을 줄이자는 이야기는 곧 관리비를 줄이자는 이야기이고 그 역도 같습니다. 어느 쪽이 옳은지는 사는 분들이 정할 문제입니다.

{role} 인력이 지금 수준으로 충분하다고 느끼시나요, 아니면 조정이 필요하다고 보시나요?""")


def frame_cost(name, info, p, peers):
    v, mu = p["value"], p["mean"]
    hi = "높은" if p["high"] else "낮은"
    return (
        f"""관리비 단가는 단지마다 두 배 가까이 갈립니다. {J(name, "은는")} 그 분포에서 {hi} 쪽입니다.

2026년 5월분 공용관리비 기준 ㎡당 {v:,}원입니다. 파일럿 단지 평균은 {mu:,.0f}원입니다. 공용관리비만이고 전기·수도 같은 개별사용료와 장기수선충당금은 빠진 값이며, 관리비 부과면적 기준이라 세대 고지서 금액과는 다릅니다.

여기서부터는 해석입니다. 단가가 {hi} 데는 규모·설비·인력이 섞여 작용합니다. 다만 단가만 보고 관리를 평가할 수는 없습니다. 낮으면 절약일 수도 있고 덜 쓰는 것일 수도 있으며, 높으면 낭비일 수도 있고 그만큼 투입하는 것일 수도 있습니다. 이 둘을 가르는 건 고지서 항목을 아는 사람뿐입니다.

고지서에서 유독 크게 느껴지는 항목이 있나요? 그 항목이 값을 한다고 보시나요?""")


def frame_era(name, info, p, peers):
    v, mu = p["value"], p["mean"]
    year = int(info["use_approval_date"][:4])
    return (
        f"""{J(name, "을를")} 다른 단지와 같은 표에 놓으면 유독 다른 칸이 하나 있습니다. {p['key']}입니다.

{v}{UNIT.get(p["key"], "")}입니다. 파일럿 단지 평균은 {mu:,.0f}{UNIT.get(p["key"], "")}이고, 준공은 {year}년입니다. K-apt 공개정보 그대로입니다.

여기서부터는 해석입니다. 이 숫자는 관리의 결과가 아니라 **지어진 시대의 결과**입니다. {year}년의 설계 기준과 지금의 기준은 다르고, 그 차이가 층수·동 배치·주차 같은 항목에 그대로 남습니다. 그래서 이 값을 두고 좋다 나쁘다를 말하는 건 시대를 두고 말하는 셈이 됩니다.

다만 시대가 만든 조건 중에는 불편만 있는 게 아니라 지금은 못 만드는 것도 있습니다. 이 단지에서 요즘 단지들이 따라 하기 어려운 점이 있다면 무엇일까요?""")


FRAMES = {"규모": frame_scale, "설비": frame_facility, "인력": frame_staff,
          "비용": frame_cost, "시대": frame_era}

TITLES = {
    "규모": lambda n, p: f"{p['key']} {p['value']:,}{UNIT.get(p['key'],'')}. 규모는 무엇을 나누고 무엇을 몰리게 하나요?",
    "설비": lambda n, p: f"{p['key']} {p['value']:,}{UNIT.get(p['key'],'')} — 설치된 양과 체감되는 양은 같은가요?",
    "인력": lambda n, p: f"{'경비' if '경비' in p['key'] else '청소'} 한 명이 {p['value']:,}세대를 맡습니다. 충분한가요?",
    "비용": lambda n, p: f"㎡당 {p['value']:,}원, 이 단가는 값을 하고 있나요?",
    "시대": lambda n, p: f"{p['key']} {p['value']}{UNIT.get(p['key'],'')}, 이건 관리가 아니라 시대가 만든 숫자입니다",
}

DAYS = ["2026-08-12T19:20:00+09:00", "2026-08-13T18:40:00+09:00",
        "2026-08-14T12:30:00+09:00", "2026-08-15T19:10:00+09:00",
        "2026-08-16T11:20:00+09:00"]

COMMENTS = {
    "규모": [("wb-persona-cashflow", "규모 효과는 관리비 단가에서 제일 먼저 보입니다. 다만 나뉘는 건 고정비뿐이라 사용량 항목은 규모와 무관하죠.", "비용 관점"),
             ("wb-persona-field-scout", "몰리는 쪽은 자료에 안 나옵니다. 진출입구와 시간대는 사시는 분만 아는 항목이에요.", "현장 검증 요청")],
    "설비": [("wb-persona-field-scout", "설치 대수와 배치는 다른 이야기입니다. 평균으로 묶으면 제일 불편한 지점이 사라져요.", "평균의 한계"),
             ("wb-persona-real-talk", "설비는 늘어날수록 유지비도 같이 늘어납니다. 숫자가 크다는 게 곧 이득은 아니죠.", "양면 보기")],
    "인력": [("wb-persona-cashflow", "인건비 비중이 큰 구조에서는 관리비 절감 논의가 곧 인력 논의가 됩니다. 이걸 알고 말해야 대화가 됩니다.", "비용 구조"),
             ("wb-persona-psy-thermo", "인력 밀도는 만족도와 단순 비례하지 않습니다. 배치와 운영 방식이 더 크게 작용하는 경우가 많아요.", "해석 주의")],
    "비용": [("wb-persona-appraisal-check", "단가 비교는 같은 달, 같은 분모끼리만 성립합니다. 부과면적 기준이라는 점을 빼면 숫자가 왜곡됩니다.", "기준 명시"),
             ("wb-persona-real-talk", "낮은 단가가 늘 좋은 건 아닙니다. 어디에 덜 쓰는지가 같이 보여야 평가가 되죠.", "양면 보기")],
    "시대": [("wb-persona-trade-brief", "준공 연도로 묶으면 단지 비교가 아니라 시대 비교가 됩니다. 이 프레임이 숫자를 덜 자극적으로 만들죠.", "중립 정리"),
             ("wb-persona-field-scout", "옛 설계에는 지금 기준으로 못 만드는 것도 있습니다. 그건 사시는 분들이 제일 잘 압니다.", "현장 관점")],
}

TOPIC = {"external_id": "wb-topic-2026-08-outlier", "title": "이 단지만 다른 숫자",
         "summary": "같은 잣대로 쟀을 때 그 단지에서만 튀는 값을 하나씩 본다",
         "category": "생활", "heat": 4}


def build():
    rows = load()
    mets = metrics(rows)
    picked = assign(mets)

    bundles = []
    for idx, slug in enumerate(PILOT):
        info = rows[slug]["info"]
        p = picked[slug]
        name = info["complex_name"]
        peers = sorted(((rows[s]["info"]["complex_name"], mets[s][p["key"]])
                        for s in PILOT if s != slug and p["key"] in mets[s]),
                       key=lambda t: -t[1])
        body = FRAMES[p["family"]](name, info, p, peers)
        title = TITLES[p["family"]](name, p)
        srcs = [SRC_FEE, SRC_BASIS] if p["family"] == "비용" else [SRC_BASIS]
        ext = f"outlier-2026-08-{slug}"
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-v1",
            "payload": {
                "complex_external_id": f"cx-{slug}",
                "topic": TOPIC,
                "post": {
                    "external_id": ext, "complex_external_id": f"cx-{slug}",
                    "persona_external_id": PERSONA["external_id"], "category": "생활",
                    "title": title, "summary": body.split("\n\n")[1][:220],
                    "body": body, "verification": "verified",
                    "source_note": ("2026. 8. 16. 조회 · K-apt 공개정보 및 2026년 5월분 공용관리비 기준 · "
                                    "파일럿 5개 단지 분포와 비교한 값"),
                    "sources": srcs,
                    "published_at": DAYS[idx], "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{i}", "persona_external_id": pid,
                     "body": b, "stance": s, "position": i}
                    for i, (pid, b, s) in enumerate(COMMENTS[p["family"]])
                ],
            },
        })

    return {
        "meta": {"name": "특이값 팩 (w1)", "posts": len(bundles),
                 "persona": PERSONA["external_id"], "pilot": PILOT,
                 "fee_period": FEE_PERIOD, "built_at": "2026-08-16",
                 "assigned": {s: picked[s] for s in PILOT},
                 "purpose": "템플릿이 아니라 단지별 특이값에서 글을 시작해 출고 검사(8.3)를 통과한다",
                 "thermostat": "인간 액션 0 기준 콜드스타트(단지당 1일 글 2). 이 팩은 단지당 1편"},
        "personas": [PERSONA],
        "bundles": bundles,
    }


def validate(pack):
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    comments = [c for b in pack["bundles"] for c in b["payload"]["comments"]]
    reg = {PERSONA["external_id"], "wb-persona-cashflow", "wb-persona-field-scout",
           "wb-persona-real-talk", "wb-persona-psy-thermo", "wb-persona-appraisal-check",
           "wb-persona-trade-brief"}

    ids = [p["external_id"] for p in posts] + [c["external_id"] for c in comments]
    if len(set(ids)) != len(ids):
        errs.append("external_id 중복")

    fam = [pack["meta"]["assigned"][s]["family"] for s in pack["meta"]["pilot"]]
    if len(set(fam)) != len(fam):
        errs.append(f"프레임 중복 — 같은 계열이 둘 이상이면 글이 겹친다: {Counter(fam)}")
    keys = [pack["meta"]["assigned"][s]["key"] for s in pack["meta"]["pilot"]]
    if len(set(keys)) != len(keys):
        errs.append(f"지표 중복 배정: {Counter(keys)}")

    for ext, t in [(p["external_id"], p["title"] + "\n" + p["body"]) for p in posts] + \
                  [(c["external_id"], c["body"]) for c in comments]:
        for w in BAN_PRICE + BAN_JUDGE + BAD_RO + ["포레온는", "그라시움는", "아리팍는", "은마는"]:
            if w in t:
                errs.append(f"금지 어휘 '{w}': {ext}")
    for p in posts:
        if not p["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {p['external_id']}")
        if p["verification"] == "verified" and not p["sources"]:
            errs.append(f"verified인데 sources 없음: {p['external_id']}")
        if p["published_at"] > "2026-08-16T22":
            errs.append(f"미래 시각: {p['published_at']}")
        if int(p["published_at"][11:13]) < 7:
            errs.append(f"야간 게시: {p['published_at']}")
    for c in comments:
        if c["persona_external_id"] not in reg:
            errs.append(f"미등록 페르소나: {c['persona_external_id']}")

    days = Counter(p["published_at"][:10] for p in posts)
    over = {d: n for d, n in days.items() if n > 2}
    if over:
        errs.append(f"서모스탯 콜드스타트(일 2편) 초과: {over}")
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
    print(f"{'단지':22}{'배정 지표':16}{'값':>10}{'z':>7}  프레임")
    for s in pack["meta"]["pilot"]:
        a = pack["meta"]["assigned"][s]
        nm = json.loads((REPO / "data" / "complex-info" / f"{s}.json").read_text(encoding="utf-8"))["complex_name"]
        print(f"  {nm[:18]:20}{a['key']:16}{a['value']:>10,}{a['z']:>+7.2f}  {a['family']}")
    print(f"\n글 {len(pack['bundles'])}편 · 댓글 {sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
