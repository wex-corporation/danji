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
  이 생성기는 **단지당 1일 1편**만 만든다.

라운드
  같은 프레임을 두 번 쓰면 라운드 사이에서 글이 겹친다. 그래서 라운드마다
  지표 풀과 프레임을 통째로 바꾼다. 한 단지가 같은 지표를 다시 받지 않도록
  이전 라운드 배정도 검증에서 확인한다.

  1라운드 — 파일럿 5곳, 규모·설비·인력·비용·시대 (게시 완료)
  2라운드 — 파일럿 6곳(원베일리 추가), 배치·이동·안전·주차·주차방식·청소

실행:
  python3 build_outlier_pack.py            # 2라운드
  python3 build_outlier_pack.py --round 1  # 1라운드 재생성(게시분과 동일해야 한다)
"""

import argparse
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FEE_PERIOD = "202605"
NOW = "2026-08-17T15:20:00+09:00"   # 생성 시점(KST). 미래 게시를 막는 기준

# 명세 10.1 Phase 0 — 파일럿 3~5곳. 거래량 상위 + 화제성으로 골랐고,
# 2라운드에서 원베일리를 더해 6곳이 됐다(운영자 결정).
PILOT_R1 = ["olympic-park-foreon", "helio-city", "ricents", "parkrio", "eunma"]
PILOT_R2 = PILOT_R1 + ["one-bailey"]

# 단지 external_id 는 slug 와 다를 수 있다. `cx-{slug}` 로 지어내면 안 된다 —
# 디에이치 퍼스티어(slug dh-firstier-ipark / id cx-dh-firstier)에서 실제로
# 422 unknown_complex 가 났다. 명시적으로 적는다.
CX = {
    "olympic-park-foreon": "cx-olympic-park-foreon",
    "helio-city": "cx-helio-city",
    "ricents": "cx-ricents",
    "parkrio": "cx-parkrio",
    "eunma": "cx-eunma",
    "one-bailey": "cx-one-bailey",
}

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


def JR(word):
    """로/으로. J()와 규칙이 달라 따로 둔다 — ㄹ 받침은 '로'다.
    '청소 47명로' 가 실제로 나왔던 자리다."""
    for ch in reversed(word.rstrip(")]}」』\"' ")):
        if "가" <= ch <= "힣":
            j = (ord(ch) - 0xAC00) % 28
            return word + ("로" if j in (0, 8) else "으로")
        if ch.isdigit():
            return word + ("로" if ch in "013678" else "으로")
    return word + "로"


BAN_PRICE = ["억", "호가", "시세", "매수", "매도", "저점", "고점", "전망", "집값"]
BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "뒤처", "부럽"]
BAD_RO = ["명로", "층로", "원로", "동로", "분로"]

# 지표별 단위. 본문·제목에서 숫자 뒤에 붙인다.
UNIT = {"세대수": "세대", "동수": "개동", "최고층": "층", "준공연도": "년",
        "승강기당 세대": "세대", "세대당 CCTV": "대", "EV 충전기 비율": "%",
        "경비1인당 세대": "세대", "청소1인당 세대": "세대", "㎡당 공용관리비": "원",
        "동당 세대": "세대", "세대당 주차": "대", "지상주차 비율": "%"}

# 지표 계열. 프레임이 여기서 갈린다.
# 라운드마다 다르다. 1라운드는 설비·인력을 한 계열로 묶었는데, 2라운드에서는
# 프레임을 재사용할 수 없어(재사용하면 라운드 사이에서 글이 겹친다) 더 잘게 쪼갰다.
# 1라운드 지도를 그대로 남겨 두는 이유는 게시분을 재현할 수 있어야 하기 때문이다.
FAMILY_R1 = {
    "세대수": "규모", "동수": "규모",
    "승강기당 세대": "설비", "세대당 CCTV": "설비", "EV 충전기 비율": "설비",
    "경비1인당 세대": "인력", "청소1인당 세대": "인력",
    "㎡당 공용관리비": "비용",
    "준공연도": "시대", "최고층": "시대",
}
FAMILY_R2 = {
    "동당 세대": "배치",
    "승강기당 세대": "이동",
    "세대당 CCTV": "안전",
    "세대당 주차": "주차",
    "지상주차 비율": "주차방식",
    "청소1인당 세대": "청소",
}

# 라운드별 지표 풀. 1라운드 배정을 그대로 재현하려면 풀도 그때 그대로여야 한다.
POOL_R1 = ["세대수", "동수", "최고층", "준공연도", "승강기당 세대", "경비1인당 세대",
           "청소1인당 세대", "세대당 CCTV", "EV 충전기 비율", "㎡당 공용관리비"]
POOL_R2 = ["동당 세대", "승강기당 세대", "세대당 CCTV", "세대당 주차",
           "지상주차 비율", "청소1인당 세대"]

# 85㎡ 초과 세대 비율은 쓰지 않는다.
#   K-apt 면적 구간이 단지마다 기준이 어긋난다. 리센츠는 전용면적 기준으로
#   들어가 있는데(84.99㎡가 60~85 구간) 은마는 4,424세대 중 4,400세대가
#   85~135 구간이다. 은마 주력은 전용 76.79·84.43㎡라 전용 기준이면 그 구간에
#   들어갈 수 없다. 원자료가 공급면적으로 채워졌거나 오류다.
#   어느 쪽인지 확인하지 못했으므로 인용하지 않는다(CLAUDE.md 4장).


def load(pilot):
    rows = {}
    for slug in pilot:
        i = json.loads((REPO / "data" / "complex-info" / f"{slug}.json").read_text(encoding="utf-8"))
        fee = json.loads((REPO / "data" / "mgmt-fees" / f"{slug}.json").read_text(encoding="utf-8"))
        rows[slug] = {"info": i, "fee": fee["periods"].get(FEE_PERIOD)}
    return rows


def metrics(rows, pool):
    """비교 가능한 지표만 뽑는다. 분모가 없으면 그 지표는 건너뛴다."""
    out = {}
    for slug, r in rows.items():
        i, fee = r["info"], r["fee"]
        hh = i["household_count"]
        m = {"세대수": hh, "동수": i.get("dong_count"), "최고층": i.get("top_floor"),
             "준공연도": int(i["use_approval_date"][:4])}
        if i.get("dong_count"):
            m["동당 세대"] = round(hh / i["dong_count"], 1)
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
        if i.get("parking_per_household"):
            m["세대당 주차"] = i["parking_per_household"]
        if i.get("parking_total") and i.get("parking_ground") is not None:
            m["지상주차 비율"] = round(i["parking_ground"] / i["parking_total"] * 100, 1)
        if fee and fee.get("complete") and fee.get("per_m2_won"):
            m["㎡당 공용관리비"] = round(fee["per_m2_won"])
        out[slug] = {k: v for k, v in m.items() if v is not None and k in pool}
    return out


def assign(mets, family):
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
        fam = family.get(k, "기타")
        if slug in used_slug or k in used_key or fam in used_fam:
            continue
        picked[slug] = {"key": k, "value": v, "z": round(z, 2),
                        "mean": round(mu, 2), "family": family.get(k, "기타"),
                        "high": z > 0}
        used_slug.add(slug)
        used_key.add(k)
        used_fam.add(fam)
    missing = [s for s in mets if s not in picked]
    if missing:
        sys.exit(f"[중단] 겹치지 않는 지표·프레임 조합을 못 찾은 단지: {missing}. "
                 f"파일럿 수가 이 라운드의 계열 수({len(set(family.values()))})를 넘으면 생긴다")
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


# ── 2라운드 프레임 6종 ────────────────────────────────────────────
# 1라운드 프레임을 다시 쓰면 라운드 사이에서 마스킹 후 유사도가 튄다.
# 그래서 계열을 쪼개고 문단 구성·도입·질문을 전부 새로 쓴다.

def frame_layout(name, info, p, peers):
    """배치 — 동당 세대수. 규모가 아니라 '어떻게 나눠 담았나'를 본다."""
    v, mu = p["value"], p["mean"]
    hi = "많이" if p["high"] else "적게"
    return (
        f"""세대수와 동수를 따로 보면 놓치는 게 있습니다. 나눠 보면 한 동에 몇 세대를 담았는지가 나옵니다.

{J(name, "은는")} {info['dong_count']}개동에 {info['household_count']:,}세대이니 한 동당 {v:,}세대입니다. 파일럿 단지 평균은 한 동당 {mu:,.1f}세대이고, 이 단지는 {hi} 담은 쪽입니다.

여기서부터는 해석입니다. 한 동에 몇 세대를 담느냐는 복도·계단·엘리베이터를 몇 세대가 같이 쓰느냐와 같은 말입니다. 적게 담으면 마주치는 사람이 줄고, 많이 담으면 같은 층에서 처리되는 일이 늘어납니다. 다만 이건 동별로 다르고, 저는 단지 평균까지만 볼 수 있습니다.

사시는 동은 이 평균보다 빽빽한 편인가요, 아니면 헐거운 편인가요?""")


def frame_elevator(name, info, p, peers):
    """이동 — 승강기당 세대. 아침 7~9시 이야기로 연다."""
    v, mu = p["value"], p["mean"]
    tight = "몰리는" if p["high"] else "여유 있는"
    return (
        f"""아침 출근 시간의 체감은 대개 엘리베이터에서 갈립니다. 그래서 대수부터 세어 봤습니다.

K-apt 공개정보 기준 승강기가 {info['elevator_count']}대, 세대수가 {info['household_count']:,}세대이니 1대당 {v:,}세대를 맡습니다. 파일럿 단지 평균은 1대당 {mu:,.1f}세대라서, 숫자만 보면 {tight} 쪽입니다.

여기서부터는 해석입니다. 이 값은 평균일 뿐이라 실제 대기 시간과는 다릅니다. 층수, 저층·고층 분리 운행, 정지 층 수가 대기를 만드는데 어느 것도 공개 자료에 없습니다. 같은 단지 안에서도 동마다 다를 겁니다.

평일 아침에 엘리베이터를 얼마나 기다리시나요? 몇 분쯤부터 '오래 기다렸다'고 느끼시나요?""")


def frame_cctv(name, info, p, peers):
    """안전 — 세대당 CCTV. 대수 자체보다 '무엇을 비추나'를 묻는다."""
    v, mu = p["value"], p["mean"]
    hi = "촘촘한" if p["high"] else "성긴"
    return (
        f"""CCTV 대수는 단지 소개에 잘 안 나오는데, K-apt에는 등록 대수가 그대로 공개돼 있습니다.

{J(name, '이가')} {info['cctv_count']:,}대이고 {info['household_count']:,}세대로 나누면 세대당 {v}대입니다. 파일럿 단지 평균은 세대당 {mu:,.2f}대이니, 밀도로는 {hi} 편에 들어갑니다.

여기서부터는 해석입니다. 대수는 설치량이지 감시 범위가 아닙니다. 지하주차장·출입구·놀이터 중 어디에 몇 대가 걸려 있는지, 화질이 번호판을 읽을 수준인지, 녹화가 며칠 보관되는지가 실제로 쓸모를 정하는데 그건 어디에도 공개되지 않습니다. 저는 대수까지만 말할 수 있습니다.

필요할 때 영상이 남아 있었는지가 대수보다 중요한 정보일 겁니다. 관리사무소에 영상을 요청해 보신 적이 있으신가요? 그때 찾던 장면이 남아 있던가요?""")


def frame_parking(name, info, p, peers):
    """주차 — 세대당 주차대수. |z|가 작으면 '평균에 가깝다'를 소재로 쓴다."""
    v, mu = p["value"], p["mean"]
    lo, hi = min(x for _, x in peers), max(x for _, x in peers)
    near = abs(p["z"]) < 0.6
    read = (f"""파일럿 단지는 세대당 {lo}대에서 {hi}대 사이에 흩어져 있고, 평균은 {mu:.2f}대입니다. {J(name, "은는")} 그 한가운데입니다. 튀는 값이 없다는 것도 하나의 정보라서 적어 둡니다."""
            if near else
            f"""파일럿 단지 평균은 세대당 {mu:.2f}대이고 범위는 {lo}대에서 {hi}대입니다. {J(name, "은는")} {'위' if p['high'] else '아래'}쪽 끝에 가깝습니다.""")
    return (
        f"""주차는 숫자와 체감이 가장 크게 어긋나는 항목입니다. 먼저 숫자만 적습니다.

총 {info['parking_total']:,}대를 {info['household_count']:,}세대가 나누어 세대당 {v}대입니다. {read}

여기서부터는 해석입니다. 세대당 대수는 평일 낮 기준으로도 금요일 밤 기준으로도 같은 값이지만, 자리를 찾는 시간은 완전히 다릅니다. 방문 차량, 이중주차 허용 여부, 동별 지하 연결 구조가 그 차이를 만드는데 셋 다 공개 자료에 없습니다.

밤 열 시에 들어와 자리를 찾기까지 걸리는 시간이 이 숫자보다 정확한 지표일 겁니다. 보통 얼마나 도시나요?""")


def frame_ground(name, info, p, peers):
    """주차방식 — 지상주차 비율. 분포가 사실상 0 아니면 100이라 평균을 쓰지 않는다."""
    zeros = sum(1 for _, x in peers if x == 0)
    v = p["value"]
    rest = (f"나머지 {len(peers)}곳은 모두" if zeros == len(peers)
            else f"나머지 {len(peers)}곳 중 {zeros}곳은")
    return (
        f"""주차 대수 말고 주차 '위치'를 보면 파일럿 단지가 두 무리로 딱 갈립니다.

{J(name, "은는")} 총 {info['parking_total']:,}대 중 지상이 {info['parking_ground']:,}대, 지하가 {info['parking_underground']:,}대입니다. 지상 비율 {v:.0f}%입니다. 같이 보는 {rest} 지상 비율이 0%, 그러니까 지상에 주차면이 아예 없습니다.

여기서부터는 해석입니다. 이 차이는 관리의 결과가 아니라 지어진 시점의 기준 차이입니다. 지상 주차는 단지 안 도로와 보행로를 차와 나눠 쓴다는 뜻이고, 지하 주차는 그 면적을 조경과 보행로에 돌린다는 뜻입니다. 대신 지하는 건설비와 이후 유지·환기 비용이 붙습니다. 어느 쪽이 낫다기보다 무엇을 내주고 무엇을 얻었는지가 다릅니다.

지상에 차가 서 있는 구조가 생활에서 불편하신가요, 아니면 오히려 편한 점도 있으신가요?""")


def frame_clean(name, info, p, peers):
    """청소 — 청소1인당 세대. 인력 프레임과 겹치지 않게 '보이지 않는 노동'으로 연다."""
    v, mu = p["value"], p["mean"]
    dense = "촘촘한" if not p["high"] else "성긴"
    return (
        f"""단지에서 가장 자주 마주치지만 숫자로는 거의 이야기되지 않는 항목이 청소입니다.

K-apt 공개정보 기준 청소 인원 {info['staff_clean']}명이고, {info['household_count']:,}세대를 {JR(str(info['staff_clean']) + '명')} 나누면 1인당 {v:,}세대입니다. 파일럿 단지 평균은 1인당 {mu:,.1f}세대여서, 배치는 {dense} 편입니다.

여기서부터는 해석입니다. 청소 인원은 관리비에서 비중이 작지 않은데도 고지서에서는 한 줄로만 보입니다. 그리고 이 숫자는 인원일 뿐 담당 범위가 아닙니다. 지하주차장까지 맡는지, 분리수거장 정리가 포함되는지, {info['hall_type']} 구조에서 층을 어떻게 도는지에 따라 같은 인원도 전혀 다른 일이 됩니다.

그래서 여쭙니다. 이 단지에서 가장 손이 많이 갈 자리는 어디이고, 그 자리는 지금 잘 관리되고 있나요?""")


FRAMES = {"규모": frame_scale, "설비": frame_facility, "인력": frame_staff,
          "비용": frame_cost, "시대": frame_era,
          "배치": frame_layout, "이동": frame_elevator, "안전": frame_cctv,
          "주차": frame_parking, "주차방식": frame_ground, "청소": frame_clean}

TITLES = {
    "규모": lambda n, p: f"{p['key']} {p['value']:,}{UNIT.get(p['key'],'')}. 규모는 무엇을 나누고 무엇을 몰리게 하나요?",
    "설비": lambda n, p: f"{p['key']} {p['value']:,}{UNIT.get(p['key'],'')} — 설치된 양과 체감되는 양은 같은가요?",
    "인력": lambda n, p: f"{'경비' if '경비' in p['key'] else '청소'} 한 명이 {p['value']:,}세대를 맡습니다. 충분한가요?",
    "비용": lambda n, p: f"㎡당 {p['value']:,}원, 이 단가는 값을 하고 있나요?",
    "시대": lambda n, p: f"{p['key']} {p['value']}{UNIT.get(p['key'],'')}, 이건 관리가 아니라 시대가 만든 숫자입니다",
    "배치": lambda n, p: f"한 동에 {p['value']:,}세대. 같은 층을 몇 집이 나눠 쓰나요?",
    "이동": lambda n, p: f"승강기 1대가 {p['value']:,}세대를 맡습니다. 아침에 얼마나 기다리시나요?",
    "안전": lambda n, p: f"세대당 CCTV {p['value']}대 — 대수는 압니다, 어디를 비추는지는 모릅니다",
    "주차": lambda n, p: f"세대당 주차 {p['value']}대, 밤 열 시에는 이 숫자가 맞나요?",
    "주차방식": lambda n, p: f"지상 주차 비율 {p['value']:.0f}% — 대수가 아니라 위치가 갈리는 지점",
    "청소": lambda n, p: f"청소 한 명이 {p['value']:,}세대를 맡습니다. 어디가 제일 손이 갈까요?",
}

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
    "배치": [("wb-persona-field-scout", "동당 세대는 단지 평균이라 동별 편차를 다 지웁니다. 타워형 한 동이 평균을 통째로 끌어올리는 경우도 있어요.", "평균의 한계"),
             ("wb-persona-psy-thermo", "빽빽함의 체감은 세대수보다 마주치는 빈도에서 옵니다. 같은 숫자라도 복도형과 계단식이 다르게 느껴지죠.", "해석 주의")],
    "이동": [("wb-persona-real-talk", "1대당 세대수는 아침 8시에는 의미가 없습니다. 저층·고층 분리 운행 여부가 실제 대기를 정합니다.", "생활 현실"),
             ("wb-persona-cashflow", "승강기는 대수만큼 유지비도 늘어납니다. 관리비 항목에서 승강기유지비를 같이 보셔야 그림이 맞습니다.", "비용 구조")],
    "안전": [("wb-persona-appraisal-check", "대수는 등록값이라 검증이 되는데 화질·보관기간은 검증할 자료가 없습니다. 이 둘을 섞어 말하면 안 됩니다.", "기준 명시"),
             ("wb-persona-real-talk", "필요할 때 영상이 남아 있느냐가 전부입니다. 대수가 많아도 보관 기간이 짧으면 소용이 없어요.", "생활 현실")],
    "주차": [("wb-persona-real-talk", "세대당 대수가 같아도 방문 차량 정책이 다르면 체감은 완전히 갈립니다. 이게 자료에 안 나오는 변수예요.", "생활 현실"),
             ("wb-persona-field-scout", "시간대별 점유율은 사시는 분만 압니다. 평일 낮과 금요일 밤을 같이 알려 주셔야 판단이 됩니다.", "현장 검증 요청")],
    "주차방식": [("wb-persona-trade-brief", "지상 대 지하는 단지 비교가 아니라 준공 시점 비교에 가깝습니다. 같은 축에 놓으면 오독이 생깁니다.", "중립 정리"),
                 ("wb-persona-cashflow", "지하 주차는 환기·조명·배수 유지비가 계속 붙습니다. 관리비 단가 차이의 한 축이 여기입니다.", "비용 구조")],
    "청소": [("wb-persona-cashflow", "청소비는 공용관리비에서 인건비 다음으로 큰 항목인 경우가 많습니다. 인원 수는 곧 고지서 금액입니다.", "비용 구조"),
             ("wb-persona-psy-thermo", "1인당 세대수가 적다고 만족도가 높아지지는 않습니다. 담당 범위와 순번이 더 크게 작용합니다.", "해석 주의")],
}

# 라운드 정의. 지표 풀·파일럿·날짜·출력 파일이 라운드마다 다르다.
ROUNDS = {
    1: {"pilot": PILOT_R1, "pool": POOL_R1, "family": FAMILY_R1, "out": "outlier-w1.json",
        "prefix": "outlier-2026-08", "idem": "v1",
        "days": ["2026-08-12T19:20:00+09:00", "2026-08-13T18:40:00+09:00",
                 "2026-08-14T12:30:00+09:00", "2026-08-15T19:10:00+09:00",
                 "2026-08-16T11:20:00+09:00"],
        "topic": {"external_id": "wb-topic-2026-08-outlier", "title": "이 단지만 다른 숫자",
                  "summary": "같은 잣대로 쟀을 때 그 단지에서만 튀는 값을 하나씩 본다",
                  "category": "생활", "heat": 4}},
    # 2라운드는 하루에 다 올린다. 서모스탯 한도는 단지당 기준이라
    # 6개 단지에 1편씩이면 단지당 1편으로 콜드스타트(2편) 안이다.
    2: {"pilot": PILOT_R2, "pool": POOL_R2, "family": FAMILY_R2, "out": "outlier-w2.json",
        "prefix": "outlier2-2026-08", "idem": "v1",
        "days": ["2026-08-17T08:10:00+09:00", "2026-08-17T09:35:00+09:00",
                 "2026-08-17T10:50:00+09:00", "2026-08-17T12:20:00+09:00",
                 "2026-08-17T13:40:00+09:00", "2026-08-17T14:50:00+09:00"],
        "topic": {"external_id": "wb-topic-2026-08-outlier2", "title": "숫자는 아는데 체감은 모릅니다",
                  "summary": "공개 자료로 셀 수 있는 데까지 세고, 나머지는 사는 사람에게 묻는다",
                  "category": "생활", "heat": 4}},
}

def build(rnd):
    cfg = ROUNDS[rnd]
    pilot, pool = cfg["pilot"], cfg["pool"]
    rows = load(pilot)
    mets = metrics(rows, pool)
    picked = assign(mets, cfg["family"])

    bundles = []
    for idx, slug in enumerate(pilot):
        info = rows[slug]["info"]
        p = picked[slug]
        name = info["complex_name"]
        peers = sorted(((rows[s]["info"]["complex_name"], mets[s][p["key"]])
                        for s in pilot if s != slug and p["key"] in mets[s]),
                       key=lambda t: -t[1])
        body = FRAMES[p["family"]](name, info, p, peers)
        title = TITLES[p["family"]](name, p)
        srcs = [SRC_FEE, SRC_BASIS] if p["family"] == "비용" else [SRC_BASIS]
        ext = f"{cfg['prefix']}-{slug}"
        # 관리비를 인용하지 않는 글에 관리비 기준월을 적으면 안 쓴 자료를
        # 쓴 것처럼 보인다. 계열에 따라 문구를 나눈다.
        note = ("2026. 8. 16. 조회 · K-apt 공개정보 기준 · "
                f"파일럿 {len(pilot)}개 단지 분포와 비교한 값")
        if p["family"] == "비용":
            note = ("2026. 8. 16. 조회 · K-apt 공개정보 및 2026년 5월분 공용관리비 기준 · "
                    f"파일럿 {len(pilot)}개 단지 분포와 비교한 값")
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-{cfg['idem']}",
            "payload": {
                "complex_external_id": CX[slug],
                "topic": cfg["topic"],
                "post": {
                    "external_id": ext, "complex_external_id": CX[slug],
                    "persona_external_id": PERSONA["external_id"], "category": "생활",
                    "title": title, "summary": body.split("\n\n")[1][:220],
                    "body": body, "verification": "verified",
                    "source_note": note,
                    "sources": srcs,
                    "published_at": cfg["days"][idx], "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{i}", "persona_external_id": pid,
                     "body": b, "stance": s, "position": i}
                    for i, (pid, b, s) in enumerate(COMMENTS[p["family"]])
                ],
            },
        })

    return {
        "meta": {"name": f"특이값 팩 (w{rnd})", "round": rnd, "posts": len(bundles),
                 "persona": PERSONA["external_id"], "pilot": pilot, "pool": pool,
                 "fee_period": FEE_PERIOD, "built_at": "2026-08-17",
                 "assigned": {s: picked[s] for s in pilot},
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
        if p["published_at"] > NOW:
            errs.append(f"미래 시각: {p['published_at']}")
        if int(p["published_at"][11:13]) < 7:
            errs.append(f"야간 게시: {p['published_at']}")
    if len({p["published_at"] for p in posts}) != len(posts):
        errs.append("published_at 중복")
    for c in comments:
        if c["persona_external_id"] not in reg:
            errs.append(f"미등록 페르소나: {c['persona_external_id']}")

    # 서모스탯은 **단지당** 한도다. 전체 편수로 세면 6개 단지에 1편씩 올려도
    # 초과로 잡힌다. 명세 6.3의 단위는 단지다.
    per = Counter((p["complex_external_id"], p["published_at"][:10]) for p in posts)
    over = {f"{cx} {d}": n for (cx, d), n in per.items() if n > 2}
    if over:
        errs.append(f"서모스탯 콜드스타트(단지당 일 2편) 초과: {over}")

    # 조사 정합성은 정규식으로 훑지 않는다. 동사 어미(없는·받는)에 오탐이 난다.
    # 헬퍼 자체를 단위 검증한다.
    for w, pair, want in [("올림픽파크 포레온", "은는", "올림픽파크 포레온은"),
                          ("리센츠", "은는", "리센츠는"), ("파크리오", "이가", "파크리오가"),
                          ("헬리오시티", "을를", "헬리오시티를")]:
        if J(w, pair) != want:
            errs.append(f"조사 헬퍼 오류: J({w}) → {J(w, pair)}")
    for w, want in [("47명", "47명으로"), ("8명", "8명으로"), ("2대", "2대로")]:
        if JR(w) != want:
            errs.append(f"조사 헬퍼 오류: JR({w}) → {JR(w)}")

    # 라운드 간 중복 — 같은 단지가 같은 지표를 다시 받으면 글이 겹친다.
    prev = defaultdict(set)
    for r, cfg in ROUNDS.items():
        if r >= pack["meta"]["round"]:
            continue
        fp = REPO / "content" / cfg["out"]
        if not fp.exists():
            continue
        old = json.loads(fp.read_text(encoding="utf-8"))
        for s, a in old["meta"].get("assigned", {}).items():
            prev[s].add(a["key"])
            prev["__fam__"].add(a["family"])
    for s, a in pack["meta"]["assigned"].items():
        if a["key"] in prev.get(s, ()):
            errs.append(f"이전 라운드와 같은 지표: {s} / {a['key']}")
        if a["family"] in prev.get("__fam__", ()):
            errs.append(f"이전 라운드와 같은 프레임 계열: {s} / {a['family']}")
    return errs


def main():
    ap = argparse.ArgumentParser(description="특이값 기반 콘텐츠 생성기")
    ap.add_argument("--round", type=int, default=2, choices=sorted(ROUNDS))
    args = ap.parse_args()

    pack = build(args.round)
    errs = validate(pack)
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    out = REPO / "content" / ROUNDS[args.round]["out"]
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{'단지':22}{'배정 지표':16}{'값':>10}{'z':>7}  프레임")
    for s in pack["meta"]["pilot"]:
        a = pack["meta"]["assigned"][s]
        nm = json.loads((REPO / "data" / "complex-info" / f"{s}.json").read_text(encoding="utf-8"))["complex_name"]
        print(f"  {nm[:18]:20}{a['key']:16}{a['value']:>10,}{a['z']:>+7.2f}  {a['family']}")
    print(f"\n글 {len(pack['bundles'])}편 · 댓글 {sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
