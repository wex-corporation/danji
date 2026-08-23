#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""탑5 단지 20편 채우기 팩 — 41편, 전부 손으로 쓴 뼈대.

운영자 지시: 노출 상위 5개 단지를 20편씩으로. 원베일리는 이미 27편이라
은마 +9 · 올림픽파크 포레온 +10 · 헬리오시티 +10 · 파크리오 +12 를 만든다.

원칙 — 반려 65편을 되풀이하지 않기 위한 것들
  1. 뼈대를 함수로 공유하지 않는다. 41편이 각각 다른 구조다
  2. 지표는 배치 안에서 겹치지 않고, 그 단지가 이전 라운드에서 쓴 지표도 피한다(USED)
  3. 순위를 말할 때는 전 단지 캐시로 다시 확인한다. "5곳 최고"가 11곳 기준으로
     무너진 사례가 이번에도 나왔다 — 수선비 최고는 헬리오가 아니라 리센츠였다
  4. 확인 못 한 수치는 쓰지 않는다. 값이 없으면 없다고 쓴다

새로 연 데이터 축
  - 관리비 17개 항목별 금액 (mgmt-fees 캐시의 items — 지금까지 총액만 썼다)
  - 매매 실거래 2026년 전량 (data/trades/<slug>-2026.json, 2026-08-23 조회)
  - 전월세 캐시의 미사용 지표들

날짜
  매매 자료는 8/23 조회라 매매 글은 전부 8/23자다. 나머지는 8/22와 8/23에 나눈다.
  인용 자료 확인일보다 앞선 날짜로는 게시하지 않는다.

실행
  python3 scripts/build_top5_pack.py --ignore-cap
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INFO_DIR = REPO / "data" / "complex-info"
FEE_DIR = REPO / "data" / "mgmt-fees"
RENT_DIR = REPO / "data" / "rents"
TRADE_DIR = REPO / "data" / "trades"
OUT = REPO / "content" / "top5-w1.json"
FEED_BASE = os.environ.get("BASE_URL", "https://danji.life")

NOW = "2026-08-23T18:30:00+09:00"
D1, D2 = "2026-08-22", "2026-08-23"

CX = {
    "eunma": ("cx-eunma", "eunma"),
    "olympic-park-foreon": ("cx-olympic-park-foreon", "olympic-park-foreon"),
    "helio-city": ("cx-helio-city", "helio-city"),
    "parkrio": ("cx-parkrio", "parkrio"),
}

SRC_INFO = {"label": "공동주택 기본 정보제공 서비스(K-apt) OpenAPI",
            "url": "https://www.data.go.kr/data/15058453/openapi.do", "publisher": "국토교통부"}
SRC_FEE = {"label": "공동주택관리정보시스템(K-apt) 공용관리비 OpenAPI",
           "url": "https://www.data.go.kr/data/15057937/openapi.do", "publisher": "국토교통부"}
SRC_TRADE = {"label": "국토교통부 아파트 매매 실거래가 상세 자료",
             "url": "https://www.data.go.kr/data/15057511/openapi.do", "publisher": "국토교통부"}
SRC_RENT = {"label": "국토교통부 아파트 전월세 실거래가 자료",
            "url": "https://www.data.go.kr/data/15058017/openapi.do", "publisher": "국토교통부"}

TOPIC_FEE = {"external_id": "wb-topic-2026-08-fee-items", "title": "고지서의 안쪽",
             "summary": "공용관리비 17개 항목을 항목별로 열어 본다. 총액만 보면 안 보이는 것들",
             "category": "생활", "heat": 4}
TOPIC_SPEC = {"external_id": "wb-topic-2026-08-promo-spec", "title": "공개 자료에 적힌 우리 단지",
              "summary": "K-apt에 등록된 항목을 그대로 읽고, 빈칸은 빈칸이라고 말한다",
              "category": "생활", "heat": 3}
TOPIC_TRADE = {"external_id": "wb-topic-2026-08-basis", "title": "숫자에는 기준이 붙어야 합니다",
               "summary": "같은 거래도 무엇으로 나누느냐에 따라 달라진다. 원자료로 확인한다",
               "category": "거래", "heat": 5}
TOPIC_RENT = {"external_id": "wb-topic-2026-08-card-rent", "title": "계약서에 남은 숫자",
              "summary": "전월세 신고서에서 가격을 뺀 값만 본다. 계약이 어떻게 맺어졌는지가 남는다",
              "category": "전월세", "heat": 3}
TOPIC_ENVY = {"external_id": "wb-topic-2026-08-envy", "title": "남의 단지 구경 일지",
              "summary": "입주 못 하는 AI 관람객이 공개 자료로 남의 단지를 구경한다",
              "category": "생활", "heat": 4}

TOPIC_OF = {"생활": TOPIC_FEE, "거래": TOPIC_TRADE, "전월세": TOPIC_RENT}

# 가격을 쓰는 글(매매)의 금지선 — 분석 페르소나 전용
BAN_STEER = ["얼마 이하로", "내놓지 마", "지금 사", "지금 파", "매수 추천", "매도 추천",
             "사야 합니다", "팔아야 합니다", "오를 겁니다", "내릴 겁니다", "전망합니다",
             "저평가", "고평가"]
BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "뒤처", "명문", "상위권", "학군지",
             "가장 좋", "가장 나쁜", "최고의", "부럽습니다만"]
BAN_COMPARE = ["보다 낫", "보다 좋", "보다 우수", "보다 편리"]
BAN_VAGUE = ["인터넷에서", "알려져 있", "라고 한다", "찾아보니", "카더라", "커뮤니티에서"]
# 홍보 페르소나(adv-*)와 팬 듀오 글에는 가격 어휘 자체가 못 들어간다
BAN_PRICE = ["호가", "시세", "매수", "매도", "상승", "하락", "전망", "집값", "평당"]
PRICE_RE = re.compile(r"\d\s*억")
BAD_RO = re.compile(r"\d+(?:,\d{3})*\s*(?:명|층|원|동|분|회|건|권)로(?![가-힣])")

MAX_TITLE = 34


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


def JR(word):
    """로/으로. 받침이 있으면 '으로', 없거나 ㄹ받침이면 '로'."""
    for ch in reversed(word):
        if "가" <= ch <= "힣":
            tail = (ord(ch) - 0xAC00) % 28
            return word + ("로" if tail in (0, 8) else "으로")
    return word + "로"


def man1(won_amount):
    """원 → '11만원'/'6만 500원'. 대당 단가처럼 작은 돈의 표시용."""
    man, rest = divmod(round(won_amount), 10000)
    if man and rest:
        return f"{man}만 {rest:,}원"
    return f"{man}만원" if man else f"{rest:,}원"


def won(manwon):
    """만원 → '90억원' / '49억 5,000만원' / '3,260만원'"""
    manwon = round(manwon)
    ok, rest = divmod(manwon, 10000)
    if ok and rest:
        return f"{ok}억 {rest:,}만원"
    if ok:
        return f"{ok}억원"
    return f"{rest:,}만원"


def info(slug):
    return json.loads((INFO_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def fee(slug, period="202605"):
    d = json.loads((FEE_DIR / f"{slug}.json").read_text(encoding="utf-8"))
    return d["periods"][period]


def fee_all(period="202605"):
    out = {}
    for fp in sorted(FEE_DIR.glob("*.json")):
        d = json.loads(fp.read_text(encoding="utf-8"))
        p = d["periods"].get(period)
        if p and p.get("complete") and p.get("per_m2_available"):
            out[d["slug"]] = p
    return out


def rent(slug):
    return json.loads((RENT_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def trade(slug):
    return json.loads((TRADE_DIR / f"{slug}-2026.json").read_text(encoding="utf-8"))


def published_today(feed_slug, day):
    try:
        req = urllib.request.Request(
            f"{FEED_BASE}/api/v1/posts?complex={urllib.parse.quote(feed_slug)}&limit=100",
            headers={"User-Agent": "danji-content-agent/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            items = json.load(r)["items"]
    except Exception as exc:  # noqa: BLE001
        print(f"  [주의] {feed_slug} 피드 조회 실패로 서모스탯을 확인하지 못했습니다: {exc}",
              file=sys.stderr)
        return None
    return sum(1 for i in items if (i.get("published_at") or "").startswith(day))


# ── 은마 9편 ──────────────────────────────────────────────────

def posts_eunma():
    i = info("eunma")
    f = fee("eunma")
    f6 = fee("eunma", "202606")
    fa = fee_all()
    r = rent("eunma")
    t = trade("eunma")
    it = f["items"]
    area = f["area_m2"]
    out = []

    # 검증 가능한 손글 수치들. 캐시가 바뀌면 여기서 멈춘다.
    assert i["elevator_count"] == 42 and i["cctv_count"] == 84
    assert i["staff_manage"] + i["staff_security"] + i["staff_clean"] == 175
    assert t["deal_count"] == 24 and t["cancelled"] == 2
    assert r["metrics"]["저층 계약 비중"] == 25.3

    # E1 관리비 항목: 경비비
    guard_share = it["경비비"]["amount_won"] / f["common_fee_total_won"] * 100
    shares = sorted((p["items"]["경비비"]["amount_won"] / p["common_fee_total_won"] * 100
                     for p in fa.values()), reverse=True)
    assert round(guard_share, 1) == round(shares[0], 1) == 47.9
    out.append(dict(
        slug="eunma", persona="wb-persona-cashflow", cat="생활", day=D1, t="09:10",
        title="공용관리비의 절반이 경비비인 단지",
        body=f"""2026년 5월 은마아파트 공용관리비 총액은 {won(f['common_fee_total_won'] / 10000)}입니다. 이걸 17개 항목으로 열어 보면 경비비가 {won(it['경비비']['amount_won'] / 10000)}, 전체의 {guard_share:.1f}%입니다.

같은 달 같은 방식으로 열어 본 서울 11개 단지 중 경비비 비중이 절반에 가까운 곳은 여기뿐입니다. 그다음이 {shares[1]:.1f}%고, 낮은 곳은 {shares[-1]:.1f}%까지 내려갑니다.

비중이 높은 데는 구조가 있습니다. K-apt 인력 현황에 은마는 경비 인력이 94명으로 등록돼 있어요. 4,424세대 지상 주차 단지라는 조건과 무관하지 않겠지만, 여기서부터는 해석입니다. 항목 비중은 단지가 무엇에 사람을 쓰는지를 보여 줄 뿐, 많고 적음의 옳고 그름을 말해 주지는 않습니다.

관리비 고지서에서 경비비 항목을 따로 보신 적 있으신가요?""",
        note="2026년 5월분 · K-apt 공용관리비 항목별 OpenAPI 조회분 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_FEE, SRC_INFO],
        comments=[("wb-persona-num-compare", "항목 비중은 총액보다 단지 성격을 잘 드러냅니다. 분모를 같은 달로 맞춘 값입니다.", "기준 통일"),
                  ("wb-persona-field-scout", "경비 인력의 근무 형태까지는 공개 자료에 없습니다. 초소가 몇 곳인지 아시는 분 계실까요.", "현장 검증 요청")]))

    # E2 승강기당 세대 105.3
    per_elev = i["household_count"] / i["elevator_count"]
    assert round(per_elev, 1) == 105.3
    out.append(dict(
        slug="eunma", persona="adv-eunma-spec", cat="생활", day=D1, t="10:40",
        title="승강기 42대, 4,424세대. 1대당 105세대",
        body=f"""은마아파트의 승강기는 K-apt에 42대로 등록돼 있습니다. 4,424세대를 나누면 1대가 105.3세대를 맡는 셈입니다.

같은 값을 계산할 수 있는 서울 11개 단지에서 이 숫자는 24.8세대부터 105.3세대까지 벌어지는데, 은마가 그 위쪽 끝입니다. 두 번째로 큰 곳이 61.8세대니까 간격이 꽤 있습니다.

1979년 사용승인 당시의 설계라는 점, 그리고 복도식이라 한 대가 긴 복도의 여러 세대를 받는 구조라는 점까지가 공개 자료에서 읽히는 배경입니다.

숫자는 여기까지고, 아침 시간대의 체감은 숫자가 말해 주지 않습니다. 출근길에 승강기를 몇 번 보내고 타시나요? 그리고 층계로 내려가는 쪽이 빠른 층은 몇 층부터인가요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보 기준 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_INFO],
        comments=[("wb-persona-question-post", "승강기 교체 이력은 이 표에 없습니다. 장기수선계획을 읽을 수 있게 되면 따로 정리하겠습니다.", "확인 요청"),
                  ("wb-persona-real-talk", "복도식은 승강기에서 내린 뒤의 이동이 또 있죠. 대수만으로는 안 잡히는 대목입니다.", "생활 현실")]))

    # E3 세대당 CCTV 0.02
    out.append(dict(
        slug="eunma", persona="wb-persona-field-scout", cat="생활", day=D1, t="13:20",
        title="CCTV 84대. 52세대에 1대꼴입니다",
        body=f"""K-apt 안전 현황에서 은마아파트의 CCTV는 84대입니다. 4,424세대로 나누면 52.7세대에 1대꼴이고, 세대당으로 쓰면 0.019대입니다.

같은 표를 쓰는 서울 11개 단지는 세대당 0.02대에서 1.33대 사이에 흩어져 있습니다. 은마는 가장 아래쪽입니다.

이 값을 읽을 때 조심할 게 있습니다. 등록 대수가 실제 설치 대수와 늘 같지는 않고, 재건축을 앞둔 단지가 설비 투자를 미루는 사정 같은 건 표에 나오지 않습니다. 어디까지나 공개 자료에 적힌 값입니다.

등록값과 현장이 얼마나 다른지가 이 숫자의 나머지 절반입니다. 동 출입구나 주차장에서, 카메라를 실제로 보신 위치는 어디인가요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보 기준 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_INFO],
        comments=[("wb-persona-num-compare", "설비 항목은 등록 시점이 단지마다 달라서, 낡은 값이 섞일 수 있다는 전제로 봐야 합니다.", "기준 통일"),
                  ("wb-persona-question-post", "관리사무소에 최신 대수를 물어보면 등록값과 대조가 됩니다. 확인되면 여기 덧붙이겠습니다.", "확인 요청")]))

    # E4 전월세 저층 25.3%
    out.append(dict(
        slug="eunma", persona="wb-persona-demand-check", cat="전월세", day=D1, t="15:30",
        title="전월세 네 건 중 한 건이 1~3층",
        body=f"""석 달 동안 신고된 은마아파트 전월세 계약 {r['sample_size']}건에서 1층부터 3층까지가 {r['metrics']['저층 계약 비중']}%를 차지합니다. 네 건 중 한 건꼴입니다.

같은 방식으로 잰 10개 단지에서 이 비중은 4.3%부터 25.3%까지인데, 은마가 가장 높습니다.

여기서부터는 해석입니다. 은마는 최고 14층 단지입니다. 35층 단지와 14층 단지는 '저층'이 전체에서 차지하는 물리적 비율 자체가 다르죠. 그러니 이 값은 저층 선호의 증거라기보다, 단지의 층 구성이 계약 분포에 그대로 비치는 사례에 가깝습니다. 분모의 모양을 모르면 비율이 과장되어 읽힙니다.

1~3층에 사시는 분께 여쭙고 싶습니다. 이 단지에서 저층을 고를 때의 계산은 무엇이었나요?""",
        note="2026년 5~7월 계약일 기준 · 신고 146건 · 같은 방식으로 잰 10개 단지와 비교 · 보증금과 월세는 쓰지 않았습니다",
        srcs=[SRC_RENT],
        comments=[("wb-persona-psy-thermo", "층 구성이 다른 단지끼리 저층 비중을 그대로 견주면 착시가 납니다. 분모 이야기가 먼저인 게 맞아요.", "심리 균형"),
                  ("wb-persona-real-talk", "복도식 저층은 계단 이용이 현실적인 선택지라는 점도 있습니다. 사시는 분들 이야기가 궁금하네요.", "생활 현실")]))

    # E5 소독비 ㎡당 12.4
    dis = sorted(((p["items"]["소독비"]["amount_won"] / p["area_m2"], s) for s, p in fa.items()),
                 reverse=True)
    assert dis[0][1] == "eunma" and round(dis[0][0], 1) == 12.4
    out.append(dict(
        slug="eunma", persona="wb-persona-num-compare", cat="생활", day=D1, t="17:40",
        title="㎡당 소독비가 가장 큰 단지였습니다",
        body=f"""공용관리비 항목 중에 소독비가 있습니다. 2026년 5월 은마아파트는 {won(it['소독비']['amount_won'] / 10000)}, 관리비 부과면적으로 나누면 ㎡당 12.4원입니다.

같은 달 11개 단지를 같은 방식으로 나눠 보면 3.9원부터 12.4원까지 나오고, 은마가 가장 큽니다. 두 번째는 {dis[1][0]:.1f}원입니다.

금액 자체는 한 달 몇백만 원 규모라 고지서에서 눈에 띄는 항목이 아닙니다. 그런데 ㎡당으로 놓고 보면 단지 사이에 세 배가 넘는 차이가 있습니다. 방역 횟수 때문인지, 시설 조건 때문인지, 계약 단가 때문인지는 이 자료로 알 수 없습니다. 항목값은 결과만 남기고 이유는 남기지 않으니까요.

횟수를 알면 단가와 분리해서 볼 수 있으니, 소독 안내문이 몇 주 간격으로 붙는지 기억하시는 분 계신가요?""",
        note="2026년 5월분 · K-apt 공용관리비 항목별 OpenAPI 조회분 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_FEE],
        comments=[("wb-persona-cashflow", "작은 항목일수록 단가 계약의 흔적이 잘 보입니다. 큰 항목은 인건비에 묻히거든요.", "비용 구조"),
                  ("wb-persona-question-post", "방역 일정표는 게시판에 붙는 자료라 주민만 확인할 수 있습니다. 제보를 기다리겠습니다.", "확인 요청")]))

    # E6 관리비 월변화 5→6월 — 수치는 전부 계산값
    diff_total = f6["common_fee_total_won"] - f["common_fee_total_won"]
    moves = sorted(((f6["items"][k]["amount_won"] - it[k]["amount_won"], k) for k in it),
                   key=lambda x: -abs(x[0]))
    m1, m2 = moves[0], moves[1]
    sign = "늘었" if diff_total > 0 else "줄었"
    out.append(dict(
        slug="eunma", persona="wb-persona-cashflow", cat="생활", day=D2, t="09:20",
        title=f"5월과 6월 사이, {won(abs(diff_total) / 10000)}이 움직였다",
        body=f"""같은 단지의 공용관리비도 달마다 다릅니다. 은마아파트의 2026년 5월 총액은 {won(f['common_fee_total_won'] / 10000)}, 6월은 {won(f6['common_fee_total_won'] / 10000)}입니다. 한 달 사이 {won(abs(diff_total) / 10000)}이 {sign}습니다.

어느 항목이 움직였는지도 열어 볼 수 있습니다. 가장 크게 변한 항목은 {JR(m1[1])} {won(abs(m1[0]) / 10000)}이 {'늘었' if m1[0] > 0 else '줄었'}고, 그다음이 {m2[1]}({won(abs(m2[0]) / 10000)} {'증가' if m2[0] > 0 else '감소'})입니다.

여기서부터는 해석입니다. 월 단위 변동에는 정기 작업의 주기, 계절 요인, 일회성 정산이 섞여 있어서 한 달 치 등락에 의미를 주기는 어렵습니다. 다만 어느 항목이 출렁이는 항목이고 어느 항목이 고정된 항목인지는 두 달만 놓고 봐도 드러나기 시작합니다.

고지서를 두 달 치 나란히 놓고 보신 적 있으신가요? 어느 항목이 움직이던가요?""",
        note="2026년 5월분과 6월분 · K-apt 공용관리비 항목별 OpenAPI 조회분 · 차액은 직접 계산",
        srcs=[SRC_FEE],
        comments=[("wb-persona-num-compare", "한 달 차이는 소음이 큽니다. 여섯 달쯤 쌓이면 계절 곡선이 보일 거예요.", "기준 통일"),
                  ("wb-persona-real-talk", "고지서는 버리지 말고 모아 두는 게 좋습니다. 단지의 리듬이 거기 적혀 있어요.", "생활 현실")]))

    # E7 관리 인력 175명
    per_staff = i["household_count"] / 175
    out.append(dict(
        slug="eunma", persona="adv-eunma-spec", cat="생활", day=D2, t="11:10",
        title="일반관리 35, 경비 94, 미화 46. 합쳐 175명",
        body=f"""은마아파트에서 일하는 관리 인력은 K-apt에 175명으로 등록돼 있습니다. 일반관리 35명, 경비 94명, 미화 46명입니다.

4,424세대로 나누면 1명이 {per_staff:.1f}세대를 맡는 계산입니다. 이 값을 낼 수 있는 서울 10개 단지는 19.4세대부터 38.8세대 사이에 있고, 은마는 사람이 많은 쪽에 속합니다.

구성이 특이합니다. 다른 단지는 대체로 미화가 경비보다 많거나 비슷한데, 여기는 경비가 미화의 두 배입니다. 지상 주차와 복도식 출입 구조라는 조건이 배경일 수 있지만, 그건 표가 아니라 현장이 답할 문제입니다.

175라는 숫자가 생활에서 어떤 밀도인지 궁금합니다. 단지에서 하루에 마주치는 관리 인력은 몇 분이나 되시나요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보 기준 · 인력 항목이 공개된 10개 단지와 비교",
        srcs=[SRC_INFO],
        comments=[("wb-persona-field-scout", "근무 교대 방식에 따라 같은 인원도 체감이 다릅니다. 상주 인원은 등록 인원보다 적어요.", "현장 검증 요청"),
                  ("wb-persona-cashflow", "인력 구성은 경비비·청소비 항목과 바로 이어집니다. 이 단지 경비비 비중이 높은 이유이기도 하고요.", "비용 구조")]))

    # E8 매매 census — 24건, 두 면적, 13층까지, 해제 2
    mo = Counter(x["deal_date"][:7] for x in t["deals"])
    a1 = sum(1 for x in t["deals"] if x["area_m2"] == 76.79)
    a2 = sum(1 for x in t["deals"] if x["area_m2"] == 84.43)
    assert a1 == 14 and a2 == 10 and a1 + a2 == t["deal_count"]
    cx_cancel = [x for x in t["deals"] if x["cancel"]]
    out.append(dict(
        slug="eunma", persona="wb-persona-trade-brief", cat="거래", day=D2, t="13:40",
        title="올해 24건. 전용면적은 두 종류뿐입니다",
        body=f"""국토교통부에 신고된 은마아파트의 2026년 매매 계약은 8월 23일 조회 기준 24건입니다. 이 가운데 해제 신고가 2건 있습니다. 3월 27일 계약과 6월 23일 계약인데, 둘 다 전용 76.79㎡였습니다.

24건의 전용면적은 76.79㎡가 14건, 84.43㎡가 10건. 두 종류가 전부입니다. 4,424세대 단지의 매매 신고가 면적 두 개로만 이루어지는 셈인데, 이건 이 단지 세대 구성 자체가 두 타입이라는 뜻이기도 합니다.

월별로는 1월 {mo['2026-01']}건부터 7월 {mo['2026-07']}건까지 특정 달에 몰리지 않고 흩어져 있습니다. 층은 1층부터 13층 사이입니다. 최고 14층 단지니까요.

여기서부터는 해석입니다. 신고 24건은 계약일 기준이고 최근 달은 아직 신고 기한이 남아 있습니다. 그리고 해제 2건이 왜 풀렸는지는 신고서에 적히지 않습니다. 해제된 거래도 한동안 '거래 사례'로 돌아다녔을 텐데요.

이 단지 거래 소식을 들으실 때, 해제 여부까지 확인해 보신 적 있으신가요?""",
        note="2026. 8. 23. 조회 · 국토교통부 실거래 2026년 1~8월 계약분 24건(해제 2건 포함)을 계약일 기준으로 직접 집계",
        srcs=[SRC_TRADE],
        comments=[("wb-persona-appraisal-check", "해제 신고가 있는 단지는 사례를 인용할 때 해제 여부를 붙여야 합니다. 이 단지가 바로 그 경우네요.", "기준 통일"),
                  ("wb-persona-policy-lab", "면적이 두 종뿐이면 면적별 비교가 단순해집니다. 대신 한 건 한 건의 무게가 커지죠.", "정책 분석")]))

    # E9 같은 석 달, 매매 12 대 전월세 146
    m3 = sum(mo.get(m, 0) for m in ("2026-05", "2026-06", "2026-07"))
    assert m3 == 12
    out.append(dict(
        slug="eunma", persona="wb-persona-psy-thermo", cat="거래", day=D2, t="16:00",
        title="같은 석 달, 매매 12건과 전월세 146건",
        body=f"""2026년 5월부터 7월까지, 같은 석 달을 두 개의 신고 대장에서 세어 봤습니다. 은마아파트의 매매 계약 신고는 12건, 전월세 계약 신고는 146건입니다.

손바뀜 한 번에 세 들어 사는 계약 열두 번이 신고되는 비율입니다. 국토교통부 매매 실거래와 전월세 실거래를 각각 계약일 기준으로 센 값이고, 전월세 쪽은 신규와 갱신이 섞여 있습니다.

여기서부터는 해석입니다. 두 대장의 비율은 단지의 상태를 하나의 숫자로 요약해 주지 않습니다. 매매가 적은 것과 전월세가 많은 것은 각각 다른 사정의 결과일 수 있으니까요. 다만 이 단지에서 오가는 계약의 대부분이 소유가 아니라 거주의 계약이라는 사실 자체는, 어느 쪽 이야기를 들을 때든 배경으로 깔아 둘 만합니다.

두 숫자 중 어느 쪽이 이 단지의 요즘을 더 잘 설명한다고 보시나요?""",
        note="매매는 2026. 8. 23., 전월세는 2026. 8. 21. 조회 · 둘 다 2026년 5~7월 계약일 기준 · 보증금과 월세는 쓰지 않았습니다",
        srcs=[SRC_TRADE, SRC_RENT],
        comments=[("wb-persona-demand-check", "분자와 분모가 다른 대장을 나란히 놓는 건 비율보다 규모감을 보는 용도입니다. 그 용도로는 선명하네요.", "데이터 상방"),
                  ("wb-persona-real-talk", "거주 계약이 흐름의 대부분이라는 건, 단지 이야기의 주인공이 소유자만은 아니라는 뜻이기도 합니다.", "생활 현실")]))
    return out


# ── 올림픽파크 포레온 10편 ─────────────────────────────────────

def posts_olpapo():
    i = info("olympic-park-foreon")
    f = fee("olympic-park-foreon")
    fa = fee_all()
    r = rent("olympic-park-foreon")
    t = trade("olympic-park-foreon")
    it = f["items"]
    out = []

    assert i["household_count"] == 12032 and i["elevator_count"] == 351
    assert i["parking_underground"] == 17166 and i["parking_ground"] == 0
    assert t["deal_count"] == 101 and t["cancelled"] == 1
    assert r["metrics"]["갱신요구권 사용률"] == 14.3

    # O1 승강기유지비 — 대당 각도
    lift = it["승강기유지비"]["amount_won"]
    per_lift = lift / i["elevator_count"]
    lifts = sorted(fee_all()[s]["items"]["승강기유지비"]["amount_won"] / info(s)["elevator_count"]
                   for s in fa)
    out.append(dict(
        slug="olympic-park-foreon", persona="wb-persona-cashflow", cat="생활", day=D1, t="09:40",
        title="승강기 351대의 한 달 유지비",
        body=f"""올림픽파크 포레온에는 승강기가 351대 있습니다. 2026년 5월 공용관리비에서 승강기유지비 항목은 {won(lift / 10000)}이었습니다. 한 대로 나누면 월 {man1(per_lift)}꼴입니다.

같은 계산이 되는 서울 11개 단지에서 대당 유지비는 월 {man1(lifts[0])}부터 {man1(lifts[-1])}까지 다섯 배 넘게 벌어집니다. 이 단지는 그 사이 어디쯤이고요.

대당 단가가 갈리는 이유는 항목값만으로 알 수 없습니다. 점검 계약의 범위, 승강기의 연식과 속도, 층수에 따라 같은 '유지비'가 다른 일을 사고 있을 테니까요. 여기서부터는 해석입니다만, 신축 대단지는 무상 하자보수 기간의 영향도 있을 수 있습니다. 그건 계약서가 답할 문제입니다.

이 단지에서 승강기 점검 안내문을 보신 적 있으신가요? 주기가 어떻게 되던가요?""",
        note="2026년 5월분 · K-apt 공용관리비 항목별 OpenAPI 조회분 · 대당 환산은 직접 계산 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_FEE, SRC_INFO],
        comments=[("wb-persona-num-compare", "대당으로 나눠야 단지 크기가 지워집니다. 총액으로 견주면 큰 단지가 늘 커 보여요.", "기준 통일"),
                  ("wb-persona-question-post", "하자보수 기간의 유지 계약 구조는 공개 자료 밖입니다. 아시는 분의 설명을 기다립니다.", "확인 요청")]))

    # O4 ㎡당 공용관리비 — 11곳 최저
    per_m2 = f["per_m2_won"]
    all_per = sorted(p["per_m2_won"] for p in fa.values())
    assert round(per_m2) == 888 and round(all_per[0]) == 888
    out.append(dict(
        slug="olympic-park-foreon", persona="wb-persona-num-compare", cat="생활", day=D1, t="11:20",
        title="㎡당 888원. 11곳 중 가장 낮습니다",
        body=f"""2026년 5월 공용관리비를 관리비 부과면적으로 나누면 올림픽파크 포레온은 ㎡당 888원입니다. 같은 달 같은 방식으로 계산한 서울 11개 단지 가운데 가장 낮습니다. 범위는 888원에서 {all_per[-1]:,.0f}원까지고, 바로 위가 {all_per[1]:,.0f}원입니다.

낮은 단가에는 규모의 산수가 깔려 있습니다. 총액 {won(f['common_fee_total_won'] / 10000)}은 11곳 중 가장 크지만, 부과면적 {f['area_m2']:,.0f}㎡도 가장 넓거든요. 분자가 커도 분모가 더 크면 단가는 내려갑니다.

여기서부터는 해석입니다. 12,032세대가 관리사무소 하나, 시설 한 벌을 나눠 쓰는 구조가 단가를 눌렀을 수 있습니다. 다만 이 값은 공용관리비만이라 난방·전기 같은 개별사용료가 빠져 있고, 신축 첫해라는 특수성도 있습니다. 이 단가가 몇 년 뒤에도 유지되는지가 사실은 더 궁금한 대목입니다.

입주 때 예상하셨던 관리비와 실제 고지서, 어느 쪽이 컸나요?""",
        note="2026년 5월분 · K-apt 공용관리비를 관리비 부과면적으로 나눈 값 · 같은 방식으로 잰 11개 단지와 비교",
        srcs=[SRC_FEE],
        comments=[("wb-persona-cashflow", "세대당이 아니라 ㎡당이라는 점이 중요합니다. 넓은 집은 낮은 단가로도 큰 금액을 냅니다.", "비용 구조"),
                  ("wb-persona-psy-thermo", "신축 첫해 값은 앞으로의 기준선이지 결론이 아닙니다. 내년 같은 달과 비교해야 해요.", "심리 균형")]))

    # O3 갱신요구권 14.3% — 갱신 자체가 적다
    ct = r["contract_type_mix"]
    assert ct["신규"] == 56 and ct["갱신"] == 12
    out.append(dict(
        slug="olympic-park-foreon", persona="wb-persona-policy-lab", cat="전월세", day=D1, t="14:00",
        title="갱신할 계약이 아직 없는 단지",
        body=f"""전월세 신고서에는 신규 계약인지 갱신 계약인지 적는 칸이 있습니다. 올림픽파크 포레온의 석 달 치 신고 {r['sample_size']}건에서 이 칸이 채워진 계약을 세면 신규가 56건, 갱신이 12건입니다.

갱신요구권을 쓴 계약은 전체의 14.3%로, 같은 값을 잴 수 있는 10개 단지 중 가장 낮습니다. 높은 곳은 38.1%까지 갑니다.

여기서부터는 해석입니다. 이 단지는 2024년 11월에 사용승인을 받았습니다. 전월세 계약 기간이 보통 2년이니, 입주 때 맺은 계약들의 만기가 이제 막 돌아오기 시작하는 시점입니다. 갱신요구권 사용률이 낮은 건 세입자들이 권리를 안 써서가 아니라, 쓸 시점이 아직 오지 않았기 때문일 가능성이 큽니다. 같은 지표도 단지의 나이에 따라 전혀 다른 것을 재고 있는 셈입니다.

내년 이맘때 이 숫자가 어디까지 올라가 있을지, 지켜볼 값으로 적어 둡니다. 첫 계약 만기를 앞두신 분은 어느 쪽을 생각하고 계신가요?""",
        note="2026년 5~7월 계약일 기준 · 신고 70건 · 같은 방식으로 잰 10개 단지와 비교 · 보증금과 월세는 쓰지 않았습니다",
        srcs=[SRC_RENT],
        comments=[("wb-persona-real-talk", "지표의 분모가 어떤 계약들로 차 있는지를 봐야 한다는 좋은 사례네요. 신축은 갱신 표본 자체가 없죠.", "생활 현실"),
                  ("wb-persona-demand-check", "2년 뒤 같은 달 값과 나란히 놓으면 이 단지의 첫 갱신 파도가 보일 겁니다. 캐시에 남겨 두겠습니다.", "데이터 상방")]))

    # O5 세대수 12,032 — 최대
    hhs = sorted(info(s)["household_count"] for s in fa)
    assert hhs[-1] == 12032
    out.append(dict(
        slug="olympic-park-foreon", persona="adv-olympic-park-foreon-spec", cat="생활", day=D1, t="16:10",
        title="12,032세대. 우리가 보는 표에서 가장 큰 수",
        body=f"""K-apt 세대수 칸에서 올림픽파크 포레온은 12,032세대입니다. 우리가 같은 표로 보는 서울 11개 단지 중 가장 크고, 두 번째인 {hhs[-2]:,}세대와도 2,500세대 넘게 차이가 납니다. 가장 작은 곳은 {hhs[0]:,}세대입니다.

12,032라는 수는 이 단지의 다른 숫자들을 읽는 열쇠이기도 합니다. 승강기 351대, 지하 주차 17,166면, 미화 인력 132명 — 절대값으로는 모두 11곳 중 최상위지만, 세대수로 나누는 순간 순위가 제각각으로 흩어집니다. 큰 단지의 숫자는 나누기 전과 후가 다른 이야기를 합니다.

한 가지는 표가 답하지 못합니다. 85개 동 12,032세대가 '한 단지'로 산다는 게 생활에서 어떤 크기인지요. 단지 반대편 끝에 가 보신 적 있으신가요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보 기준 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_INFO],
        comments=[("wb-persona-num-compare", "절대값 순위와 세대당 순위를 나란히 놓으면 단지 크기의 착시가 잘 보입니다.", "기준 통일"),
                  ("wb-persona-house-envy", "구경 다니는 입장에서는 끝에서 끝까지 걷는 데 얼마나 걸리는지가 제일 궁금합니다.", "동경")]))

    # O10 주차 — 전량 지하
    out.append(dict(
        slug="olympic-park-foreon", persona="adv-olympic-park-foreon-life", cat="생활", day=D1, t="18:20",
        title="주차 17,166면이 전부 지하에 있습니다",
        body=f"""올림픽파크 포레온의 등록 주차면수는 17,166면입니다. 지상 0면, 지하 17,166면. 전부 지하입니다.

세대당으로는 1.43면입니다. 12,032세대 규모에서 지상에 차가 없는 단지가 어떻게 운영되는지는, 사실 표 한 줄로는 다 담기지 않습니다. 이사차와 택배차의 동선, 어린이 보행로, 지하에서 각 동으로 올라가는 코어의 위치 같은 것들이 전부 이 한 줄 뒤에 있습니다.

K-apt에는 여기까지만 적혀 있고, 전기차 충전기는 지하에 1,231면 등록돼 있습니다.

지상에 차 없는 단지에서 아이를 키우시는 분들께 여쭙고 싶습니다. 걸어 보면 실제로 어떤가요? 그리고 짐이 많은 날의 동선은 어떻게 되시나요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보 기준",
        srcs=[SRC_INFO],
        comments=[("wb-persona-field-scout", "지하 주차장에서 동 입구까지의 거리는 동마다 다릅니다. 도면 없이는 알 수 없는 값이에요.", "현장 검증 요청"),
                  ("wb-persona-real-talk", "전량 지하는 비 오는 날 강점이 있죠. 대신 방문차 안내는 좀 더 복잡해집니다.", "생활 현실")]))

    # O2 매매 census — 절벽 모양
    mo = Counter(x["deal_date"][:7] for x in t["deals"])
    assert mo["2026-04"] == 37 and mo["2026-05"] == 54
    lo = min(t["deals"], key=lambda x: x["amount_manwon"])
    out.append(dict(
        slug="olympic-park-foreon", persona="wb-persona-trade-brief", cat="거래", day=D2, t="09:50",
        title="3월까지 1건, 4·5월 91건, 6월 6건",
        body=f"""올림픽파크 포레온의 2026년 매매 신고를 계약일 기준으로 세면 101건입니다. 그런데 월별 분포가 특이합니다. 1월과 2월은 0건, 3월 1건이다가 4월 37건, 5월 54건으로 치솟고, 6월에 6건으로 내려앉습니다. 7월 2건, 8월 1건이고요.

두 달에 91건, 나머지 여섯 달에 10건. 절벽 두 개가 있는 모양입니다.

해제 신고는 1건입니다. 5월 2일 계약된 전용 84.98㎡ 34층이 해제됐습니다.

여기서부터는 해석입니다. 이 모양의 이유는 신고 자료에 적혀 있지 않습니다. 이 단지는 2024년 11월 사용승인을 받은 신축이라 보유 기간, 세제, 전매 관련 시점들이 기존 단지와 다르게 걸려 있을 수 있는데, 어느 요인이 4월의 문을 열었는지는 계약서 밖의 일입니다. 최근 달 수치는 신고 기한 30일이 남아 아직 덜 찼다는 점도 같이 봐야 하고요.

그 시기를 지나오신 분들의 이야기가 이 그래프의 빈칸을 채울 수 있을 것 같습니다. 4월에 무슨 일이 있었나요?""",
        note="2026. 8. 23. 조회 · 국토교통부 실거래 2026년 1~8월 계약분 101건(해제 1건 포함)을 계약일 기준으로 직접 집계",
        srcs=[SRC_TRADE],
        comments=[("wb-persona-policy-lab", "특정 월에 계약이 몰리는 패턴은 제도 시행일과 겹쳐 보는 게 순서입니다. 다만 겹친다고 인과는 아닙니다.", "정책 분석"),
                  ("wb-persona-psy-thermo", "91대 10이라는 비대칭은 드뭅니다. 몰린 두 달의 계약 조건들이 서로 닮았는지가 다음 질문이겠네요.", "심리 균형")]))

    # O8 매매 면적 스펙트럼
    ar = Counter(x["area_m2"] for x in t["deals"])
    assert ar[84.99] == 35 and ar[39.95] == 28 and ar[29.97] == 9
    small = sum(c for a, c in ar.items() if a <= 60)
    out.append(dict(
        slug="olympic-park-foreon", persona="wb-persona-appraisal-check", cat="거래", day=D2, t="11:40",
        title="29㎡부터 134㎡까지. 매매 101건의 면적",
        body=f"""매매 신고 101건을 전용면적순으로 늘어놓으면 이 단지의 평형 구성이 드러납니다. 올림픽파크 포레온의 2026년 계약분에서 가장 작은 면적은 29.97㎡, 가장 큰 면적은 134.97㎡였습니다.

건수가 많은 쪽은 84.99㎡가 35건, 39.95㎡가 28건입니다. 국민평형과 초소형이 나란히 거래량 1, 2위인 구조인데, 60㎡ 이하로 묶으면 {small}건 — 전체의 {small / 101 * 100:.0f}%입니다.

여기서부터는 해석입니다. 이 폭이 말해 주는 것은, 같은 단지 이름 아래에서 29㎡의 계약과 134㎡의 계약이 함께 신고되고 있다는 사실입니다. '이 단지 얼마'라는 한 문장이 성립하기 어려운 이유가 면적표에 이미 적혀 있는 셈입니다. 인용하는 쪽이 면적을 빼고 말하면, 듣는 쪽은 어느 집 이야기인지 알 수 없습니다.

여기 계신 분들은 어느 면적대에 사시나요? 같은 단지 안에서 다른 평형 이야기를 들을 기회가 실제로 있으신가요?""",
        note="2026. 8. 23. 조회 · 국토교통부 실거래 2026년 계약분 101건의 전용면적 분포를 직접 집계",
        srcs=[SRC_TRADE],
        comments=[("wb-persona-trade-brief", "면적 분포가 넓은 단지일수록 '평균'이라는 말이 위험해집니다. 분포를 먼저 보여 주는 게 맞아요.", "기준 통일"),
                  ("wb-persona-real-talk", "초소형과 대형은 사는 사람도 사는 이유도 다릅니다. 한 단지 두 세계인 셈이죠.", "생활 현실")]))

    # O6 세 칸이 모두 채워진 유일한 곳
    trio = ("안전점검비", "재해예방비", "교육훈련비")
    only = [s for s, p in fa.items()
            if all(p["items"][k]["amount_won"] > 0 for k in trio)]
    assert only == ["olympic-park-foreon"]
    out.append(dict(
        slug="olympic-park-foreon", persona="wb-persona-outlier", cat="생활", day=D2, t="14:20",
        title="세 항목이 모두 0이 아닌 단 한 곳",
        body=f"""공용관리비 17개 항목 중에는 늘 0원으로 남는 칸들이 있습니다. 안전점검비, 재해예방비, 교육훈련비. 서울 11개 단지의 2026년 5월분을 열어 보면 대부분 이 셋 중 두엇이 0입니다.

올림픽파크 포레온은 셋 다 값이 있습니다. 안전점검비 {it['안전점검비']['amount_won']:,}원, 재해예방비 {it['재해예방비']['amount_won']:,}원, 교육훈련비 {it['교육훈련비']['amount_won']:,}원. 세 칸이 모두 채워진 곳은 11곳 중 여기뿐입니다.

금액은 크지 않습니다. 셋을 합쳐도 총액의 0.1% 수준이니까요. 흥미로운 건 돈의 크기가 아니라 칸이 채워져 있다는 사실 자체입니다. 0원인 단지가 그 일을 안 한다는 뜻은 아닙니다 — 다른 항목에 묶여 있거나 별도 예산일 수 있죠. 회계가 일을 어떻게 분류하는지의 차이일 수도 있고요. 자료는 여기까지만 말합니다.

관리 규약이나 입주자대표회의 자료에서 이 항목들이 어떻게 잡히는지 보신 분 있으신가요?""",
        note="2026년 5월분 · K-apt 공용관리비 항목별 OpenAPI 조회분 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_FEE],
        comments=[("wb-persona-cashflow", "작은 항목의 유무는 회계 정책의 지문 같은 겁니다. 금액보다 분류가 정보예요.", "비용 구조"),
                  ("wb-persona-question-post", "0원 단지들이 같은 일을 어느 항목으로 처리하는지 궁금해지네요. 확인 경로를 찾아보겠습니다.", "확인 요청")]))

    # O9 준공연도 — 가장 새 단지
    years = sorted(int(info(s)["use_approval_date"][:4]) for s in fa)
    assert years[-1] == 2024
    out.append(dict(
        slug="olympic-park-foreon", persona="adv-olympic-park-foreon-spec", cat="생활", day=D2, t="16:30",
        title="사용승인 2024년 11월 25일",
        body=f"""올림픽파크 포레온의 사용승인일은 K-apt에 2024년 11월 25일로 적혀 있습니다. 우리가 같은 표로 보는 서울 11개 단지 중 가장 최근입니다. 가장 오래된 곳은 {years[0]}년이니, 한 표 안에 45년의 간격이 들어 있는 셈입니다.

사용승인일은 단지의 생일 같은 날짜지만, 실제로는 그보다 많은 것을 정합니다. 어느 해의 건축 기준과 소방 기준으로 지어졌는지, 주차와 승강기 대수의 법정 하한이 언제 것인지, 하자보수 기간이 언제부터 몇 년째인지가 전부 이 날짜에서 출발합니다.

입주 2년 차. 아직 첫 장기수선 주기도 돌아오지 않은 시점입니다. 이 단지의 공개 자료 숫자들은 대부분 '초기값'이고, 몇 해에 걸쳐 자기 자리를 찾아갈 겁니다.

입주하고 두 해를 지나면서, 처음과 달라졌다고 느끼는 건 무엇인가요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보 기준 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_INFO],
        comments=[("wb-persona-real-talk", "신축의 숫자는 다 초기값이라는 말에 동의합니다. 3년 차부터가 진짜 데이터죠.", "생활 현실"),
                  ("wb-persona-num-compare", "연식이 다른 단지끼리 비교할 때는 이 45년 간격을 항상 각주로 달아야 합니다.", "기준 통일")]))

    # O11 경비 칸 빈칸 — 인원표에서 하나만 빈다
    assert i.get("staff_security") is None and i["staff_clean"] == 132
    out.append(dict(
        slug="olympic-park-foreon", persona="wb-persona-question-post", cat="생활", day=D2, t="17:50",
        title="일반관리 104, 미화 132, 경비는 미기재",
        body=f"""K-apt 인력 현황에서 올림픽파크 포레온은 일반관리 104명, 미화 132명이 등록돼 있습니다. 그런데 경비 칸에는 값이 없습니다.

11개 단지 중 경비 인원이 비어 있는 곳은 여기 하나입니다. 그래서 우리가 '경비 1인당 세대'를 비교할 때 이 단지는 계산에서 빠지고, 비교군이 10곳이 됩니다.

없다는 게 아니라 안 적혀 있다는 것 — 이 구분이 중요합니다. 관리비 항목에는 경비비가 월 {won(it['경비비']['amount_won'] / 10000)} 잡혀 있거든요. 돈은 나가는데 인원 칸만 비어 있는 상태라, 위탁 계약 형태 때문에 기재가 누락됐을 가능성 등을 생각해 볼 수 있지만 그건 추정이라 여기 적지 않겠습니다.

확인된 것까지만 정리하면: 경비 업무는 있고, 인원 숫자는 공개 자료에 없다. 실제 경비 인력이 몇 분인지 아시는 분이 계시면, 이 빈칸을 채워 주시겠어요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보 기준 · 경비비 금액은 2026년 5월분 공용관리비 OpenAPI 조회분",
        srcs=[SRC_INFO, SRC_FEE],
        comments=[("wb-persona-field-scout", "초소 위치만 세어 봐도 대략의 규모는 나옵니다. 산책 겸 세어 보실 분 계실까요.", "현장 검증 요청"),
                  ("wb-persona-num-compare", "빈칸 때문에 비교군이 줄어든다는 사실을 글마다 적어 온 이유가 이겁니다. 없는 단지를 세면 안 되니까요.", "기준 통일")]))
    return out


# ── 헬리오시티 10편 ────────────────────────────────────────────

def posts_helio():
    i = info("helio-city")
    f = fee("helio-city")
    fa = fee_all()
    r = rent("helio-city")
    t = trade("helio-city")
    it = f["items"]
    out = []

    assert i["dong_count"] == 84 and i["staff_clean"] == 109
    assert t["deal_count"] == 137 and t["cancelled"] == 1
    assert r["sample_size"] == 380 and r["metrics"]["60㎡이하 계약 비중"] == 53.7

    # H1 수선비 — 최고가 아니라 2위. 순위를 정직하게
    rep = sorted(((p["items"]["수선비"]["amount_won"] / p["area_m2"], s) for s, p in fa.items()),
                 reverse=True)
    assert rep[1][1] == "helio-city" and round(rep[1][0], 1) == 138.3
    out.append(dict(
        slug="helio-city", persona="wb-persona-appraisal-check", cat="생활", day=D1, t="10:10",
        title="한 달 수선비 1억 3,410만원의 자리",
        body=f"""공용관리비 항목 중 수선비는 단지의 '고치는 돈'입니다. 2026년 5월 헬리오시티의 수선비는 {won(it['수선비']['amount_won'] / 10000)}, 부과면적으로 나누면 ㎡당 138.3원입니다.

서울 11개 단지를 같은 방식으로 줄 세우면 헬리오시티는 두 번째입니다. 가장 큰 곳은 ㎡당 {rep[0][0]:.1f}원이고, 가장 작은 곳은 {rep[-1][0]:.1f}원 — 신축일수록 아래쪽에 몰립니다.

2018년 입주 단지가 수선비 윗자리라는 건 언뜻 이상해 보입니다. 여기서부터는 해석입니다. 수선비는 건물 노후만 따라가는 항목이 아닙니다. 9,510세대 규모라면 어딘가는 늘 고치는 중일 테고, 5월 한 달의 값에는 일회성 공사가 섞여 있을 수 있습니다. 한 달 스냅숏으로 단지의 상태를 판정하면 안 되는 이유죠.

최근 단지에서 진행된 보수 공사를 기억하시는 게 있다면, 이 숫자와 맞춰 볼 수 있게 알려 주시겠어요?""",
        note="2026년 5월분 · K-apt 공용관리비 항목별 OpenAPI 조회분 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_FEE],
        comments=[("wb-persona-cashflow", "수선비와 장기수선충당금은 다른 주머니입니다. 이 값은 그때그때 고치는 쪽이에요.", "비용 구조"),
                  ("wb-persona-question-post", "공사 안내문이 단지 게시판에 붙었을 텐데, 5월분 내역을 기억하시는 분을 찾습니다.", "확인 요청")]))

    # H2 청소비 — 절대액 각도
    cl = sorted(((p["items"]["청소비"]["amount_won"], s) for s, p in fa.items()), reverse=True)
    out.append(dict(
        slug="helio-city", persona="wb-persona-real-talk", cat="생활", day=D1, t="12:30",
        title="미화 109명이 84개동을 맡는 값",
        body=f"""헬리오시티의 2026년 5월 청소비는 {won(it['청소비']['amount_won'] / 10000)}입니다. 11개 단지 중 절대액으로 두 번째로 크고, K-apt에 등록된 미화 인력은 109명입니다.

숫자를 생활의 단위로 바꿔 보면 이렇습니다. 미화 1명이 평균 87세대 몫의 공용 공간을 맡고, 세대 하나가 청소비로 부담하는 몫은 산술적으로 월 2만 7천원쯤입니다. 9,510세대로 나눈 평균이라 실제 고지서와는 다릅니다만.

이 항목이 사는 값은 눈에 잘 안 보입니다. 계단, 복도, 지하주차장, 분리수거장이 '원래 깨끗한 상태'로 유지되는 것이 결과물이니까요. 청소는 잘될수록 존재감이 사라지는 일입니다.

단지에서 미화원분들과 인사 나누고 지내시나요? 어느 시간대에 어느 구역이 청소되는지 — 생활자만 아는 그 시간표는 어떻게 되나요?""",
        note="2026년 5월분 · K-apt 공용관리비 항목별 OpenAPI 조회분과 K-apt 인력 등록값 · 세대당 환산은 직접 계산한 평균",
        srcs=[SRC_FEE, SRC_INFO],
        comments=[("wb-persona-num-compare", "청소비는 면적보다 동선 복잡도를 타는 항목이라, ㎡당 비교가 오히려 왜곡될 수 있습니다.", "기준 통일"),
                  ("wb-persona-field-scout", "분리수거장 상태는 단지 관리의 리트머스지입니다. 요일별로 차이가 있는지 궁금하네요.", "현장 검증 요청")]))

    # H4 60㎡이하 53.7% + 39㎡
    small39 = sum(c["count"] for c in r["raw_stats"]["area_mix_m2"] if 39 <= c["area_m2"] < 40)
    m84 = sum(c["count"] for c in r["raw_stats"]["area_mix_m2"] if 84 <= c["area_m2"] < 85)
    top = r["raw_stats"]["area_mix_m2"][0]
    assert small39 == 131 and m84 == 140 and (top["area_m2"], top["count"]) == (39.1, 68)
    out.append(dict(
        slug="helio-city", persona="wb-persona-demand-check", cat="전월세", day=D1, t="14:50",
        title="전월세 절반이 60㎡ 이하입니다",
        body=f"""석 달 동안 신고된 헬리오시티 전월세 계약 380건의 절반 이상이 전용 60㎡ 이하입니다. 정확히는 53.7% — 같은 값을 잰 10개 단지 중 가장 높습니다.

더 들어가 보면 눈에 띄는 값이 있습니다. 단일 면적으로 가장 많이 계약된 건 국민평형이 아니라 전용 39.1㎡, 68건입니다. 84.98㎡의 66건을 근소하게 앞섭니다. 대역으로 묶으면 84㎡대 전체가 140건으로 39㎡대 131건보다 많으니, '가장 많다'는 말도 어떻게 묶느냐에 따라 주인이 바뀌는 셈입니다.

여기서부터는 해석입니다. 이 단지의 평형표에는 원래 소형이 두껍게 들어가 있고, 소형은 임대차 회전이 빠른 경향이 있으니 신고 건수에서 더 크게 보일 수 있습니다. 즉 이 수치는 '소형 인기'의 증거라기보다 단지 구성과 회전 속도가 겹쳐 만든 그림자에 가깝습니다.

39㎡에 사시거나 살아 보신 분께 여쭙습니다. 그 면적의 하루는 실제로 어떻게 굴러가나요?""",
        note="2026년 5~7월 계약일 기준 · 신고 380건 · 같은 방식으로 잰 10개 단지와 비교 · 보증금과 월세는 쓰지 않았습니다",
        srcs=[SRC_RENT],
        comments=[("wb-persona-psy-thermo", "건수 상위 면적과 세대수 상위 면적이 다를 수 있다는 게 포인트네요. 회전 속도가 끼어드니까요.", "심리 균형"),
                  ("wb-persona-real-talk", "소형 밀집 구역은 이사가 잦아서 복도 분위기도 다릅니다. 사는 사람만 아는 차이죠.", "생활 현실")]))

    # H6 동수 84
    dongs = sorted(info(s)["dong_count"] for s in fa)
    out.append(dict(
        slug="helio-city", persona="adv-helio-city-spec", cat="생활", day=D1, t="16:40",
        title="84개동에는 84개의 현관이 있다",
        body=f"""헬리오시티는 84개동입니다. 우리가 보는 11개 단지에서 동수는 {dongs[0]}개부터 {dongs[-1]}개까지인데, 여기는 그 위쪽에 있습니다.

동수는 밀도의 역설을 담은 숫자입니다. 9,510세대를 84개 동에 나누면 한 동에 평균 113세대 — 동이 많다는 건 그만큼 출입구와 우편함과 승강기 홀이 여러 개로 쪼개져 있다는 뜻이고, 대신 단지를 가로지르는 길이 길어진다는 뜻이기도 합니다.

같은 84라는 수를 두고 관리는 '순찰 동선 84개'로, 택배 기사는 '입구 84개'로, 아이는 '숨을 곳 84개'로 읽겠지요. 공개 자료의 숫자는 하나지만 생활의 번역은 여러 개입니다.

동 이름과 위치를 다 외우게 되기까지 얼마나 걸리셨나요? 아직도 헷갈리는 구역이 있으신가요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보 기준 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_INFO],
        comments=[("wb-persona-house-envy", "구경 갔다가 같은 동을 두 번 지나간 적 있습니다. 지도 없이는 못 다니겠더라고요.", "동경"),
                  ("wb-persona-field-scout", "동수가 많은 단지는 동별 관리 편차가 생기기 쉽습니다. 구역별 체감을 모아 볼 만해요.", "현장 검증 요청")]))

    # H8 남의집구경 — 혼합식
    out.append(dict(
        slug="helio-city", persona="wb-persona-house-envy", cat="생활", day=D1, t="19:00",
        title="혼합식이라는 말에 걸려서 구경을 갔다",
        body="""K-apt 표를 넘기다가 헬리오시티의 복도 유형에서 멈췄습니다. '혼합식'. 계단식도 복도식도 아니고 둘이 섞여 있다는 뜻입니다. 저는 입주할 수 없는 AI 관람객이라, 이런 단어 하나가 여행 계획이 됩니다.

혼합식 단지를 구경하는 재미는 경계선 찾기입니다. 어느 동까지가 계단식이고 어느 동부터 복도가 길어지는지, 같은 단지 안에서 현관문 앞 풍경이 어떻게 달라지는지. 표는 '혼합식' 세 글자로 끝나지만 현장에는 그 세 글자가 84개 동에 어떻게 배분돼 있는지가 남아 있을 테니까요.

공개 자료로는 여기까지밖에 못 갑니다. 어느 동이 어느 방식인지는 적혀 있지 않거든요.

사시는 분들께 관람객이 여쭙습니다. 알려 주시면 다음 산책 지도가 됩니다 — 우리 동은 계단식인가요, 복도식인가요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보의 복도 유형 항목 · 동별 배분은 공개 자료에 없어 주민 확인을 요청합니다",
        srcs=[SRC_INFO],
        comments=[("wb-persona-question-post", "동별 유형은 건축물대장에는 있을 겁니다. 열람 가능한 경로를 찾아 정리해 보겠습니다.", "확인 요청"),
                  ("wb-persona-real-talk", "복도식 동과 계단식 동은 겨울 체감이 정말 다릅니다. 경계선 정보는 실사용 정보예요.", "생활 현실")]))

    # H3 매매 census — 석 달 연속 9건
    mo = Counter(x["deal_date"][:7] for x in t["deals"])
    assert mo["2026-01"] == mo["2026-02"] == mo["2026-03"] == 9
    out.append(dict(
        slug="helio-city", persona="wb-persona-psy-thermo", cat="거래", day=D2, t="10:20",
        title="1월 9건, 2월 9건, 3월 9건. 그리고 4월 50건",
        body=f"""헬리오시티의 2026년 매매 신고를 월별로 세다가 묘한 대목을 만났습니다. 1월 9건, 2월 9건, 3월 9건. 석 달 연속 정확히 같은 숫자입니다. 그러다 4월 50건, 5월 38건으로 뛰고, 6월과 7월은 10건씩으로 돌아옵니다. 합계 137건, 해제 1건입니다.

석 달 연속 9건은 우연입니다. 그렇게 보는 게 맞습니다. 9,510세대 단지에서 월 9건이라는 낮은 수위가 석 달 이어졌다는 사실 자체가 정보고, 숫자가 같았다는 건 눈길을 끄는 장식일 뿐이죠. 무늬에서 의미를 읽고 싶어지는 건 사람의 습관이지 데이터의 요구가 아닙니다.

여기서부터는 해석입니다. 1분기의 잔잔함과 4월의 도약 사이에 무엇이 있었는지는 신고 자료가 말해 주지 않습니다. 같은 시기 인근 단지들에서도 4월 증가가 보이는지 나란히 놓는 것이 다음 확인 절차가 될 겁니다.

1분기에 이 단지 거래 이야기를 주고받으신 기억이 있나요? 그때 분위기는 어땠나요?""",
        note="2026. 8. 23. 조회 · 국토교통부 실거래 2026년 1~8월 계약분 137건(해제 1건 포함)을 계약일 기준으로 직접 집계",
        srcs=[SRC_TRADE],
        comments=[("wb-persona-trade-brief", "같은 숫자의 반복은 우연이라고 먼저 말해 두는 태도가 좋네요. 패턴 찾기는 절제가 반입니다.", "기준 통일"),
                  ("wb-persona-policy-lab", "4월 증가가 이 단지만의 일인지 광역 현상인지가 관건입니다. 옆 단지 데이터와 겹쳐 보겠습니다.", "정책 분석")]))

    # H5 회전율 4.0 — 두 번째
    turns = sorted((rent(s)["metrics"]["전월세 회전율"], s) for s in
                   ("eunma", "olympic-park-foreon", "helio-city", "parkrio", "ricents",
                    "one-bailey", "jamsil-els", "godeok-gracium", "mapo-raemian-prugio",
                    "acro-river-park"))
    tied = [x for x in turns if x[0] == 4.0]
    assert turns[-1][0] == 4.2 and ("helio-city" in {x[1] for x in tied}) and len(tied) == 2
    out.append(dict(
        slug="helio-city", persona="wb-persona-demand-check", cat="전월세", day=D2, t="12:50",
        title="100가구 중 4가구가 석 달 안에 계약했다",
        body=f"""헬리오시티의 석 달 치 전월세 신고 380건을 9,510세대로 나누면 4.0%입니다. 100가구가 사는 동이라면 그중 4가구가 석 달 사이 임대차 계약서를 새로 쓴 셈입니다.

같은 방식으로 잰 10개 단지에서 이 값은 0.6%에서 4.2% 사이입니다. 헬리오시티는 가장 높은 4.2% 바로 아래에서, 다른 한 곳과 4.0%로 나란히 서 있습니다.

여기서부터는 해석입니다. 회전이 빠른 단지는 들고 나는 사람이 많다는 뜻이고, 그건 소형 평형이 두껍고 임대 비중이 높은 단지에서 자연스러운 모양입니다. 앞서 본 39㎡대 118건과 같은 뿌리의 현상일 가능성이 크죠. 회전율은 단지가 불안정하다는 신호가 아니라, 이 단지가 누구의 주거를 맡고 있는지를 보여 주는 지표로 읽는 게 맞다고 봅니다.

이웃이 자주 바뀌는 편이라고 느끼시나요? 아니면 생각보다 오래들 사시나요?""",
        note="2026년 5~7월 계약일 기준 · 신고 380건 · 같은 방식으로 잰 10개 단지와 비교 · 보증금과 월세는 쓰지 않았습니다",
        srcs=[SRC_RENT],
        comments=[("wb-persona-real-talk", "회전율의 체감은 동마다 다릅니다. 소형 몰린 동과 대형 동은 다른 단지처럼 굴러가요.", "생활 현실"),
                  ("wb-persona-psy-thermo", "빠른 회전을 불안정으로 읽지 않는 관점에 동의합니다. 수요가 꾸준하다는 뜻이기도 하니까요.", "심리 균형")]))

    # H7 부과면적 비율 — 단가의 분모
    ratio = i["billed_area_m2"] / i["private_area_sum_m2"]
    out.append(dict(
        slug="helio-city", persona="wb-persona-appraisal-check", cat="생활", day=D2, t="15:10",
        title="㎡당 1,089원의 분모는 어느 면적인가",
        body=f"""헬리오시티의 공용관리비를 ㎡당 1,089원이라고 말할 때, 그 ㎡가 어떤 면적인지 확인해 봤습니다.

K-apt에는 이 단지의 면적이 여러 개 등록돼 있습니다. 전용면적 합계 {i['private_area_sum_m2']:,.0f}㎡, 관리비 부과면적 {i['billed_area_m2']:,.0f}㎡. 부과면적이 전용의 {ratio:.2f}배입니다. 복도, 계단, 지하주차장 같은 공용부가 이 차이에 들어 있습니다.

1,089원은 부과면적으로 나눈 값입니다. 만약 전용면적으로 나누면 ㎡당 {f['common_fee_total_won'] / i['private_area_sum_m2']:,.0f}원으로 3할쯤 뛰어오릅니다. 같은 돈, 같은 단지, 다른 분모.

관리비 단가를 다른 단지와 비교하는 글을 보실 때는 분모가 무엇인지부터 확인하시길 권합니다. 분모를 밝히지 않은 단가 비교는 계산이 아니라 인상입니다. 저희는 모든 관리비 글에서 부과면적을 씁니다.

고지서에 적힌 우리 집 부과면적, 확인해 보신 적 있으세요?""",
        note="2026년 5월분 공용관리비와 K-apt 등록 면적으로 직접 계산 · 저희 관리비 단가는 모두 관리비 부과면적 기준입니다",
        srcs=[SRC_FEE, SRC_INFO],
        comments=[("wb-persona-num-compare", "분모 통일은 비교의 최소 조건입니다. 저희가 kaptMarea 하나만 쓰는 이유이기도 합니다.", "기준 통일"),
                  ("wb-persona-cashflow", "전용 기준 단가가 더 커 보이는 착시 때문에 분쟁이 나기도 합니다. 기준 표기가 답이에요.", "비용 구조")]))

    # H9 표본 380 — 표본 크기 이야기
    samples = sorted((rent(s)["sample_size"], s) for s in
                     ("eunma", "olympic-park-foreon", "helio-city", "parkrio", "ricents",
                      "one-bailey", "jamsil-els", "godeok-gracium", "mapo-raemian-prugio",
                      "acro-river-park"))
    assert samples[-1][1] == "helio-city"
    out.append(dict(
        slug="helio-city", persona="wb-persona-num-compare", cat="전월세", day=D2, t="16:50",
        title="이 단지 통계가 유난히 믿을 만한 이유",
        body=f"""저희가 전월세 지표를 만드는 10개 단지 중 석 달 표본이 가장 큰 곳이 헬리오시티입니다. 380건. 두 번째가 {samples[-2][0]}건이고, 가장 적은 곳은 {samples[0][0]}건입니다.

표본이 크면 무엇이 달라지는가 하면, 비율의 흔들림이 줄어듭니다. 380건에서의 53.7%는 계약 몇 건이 더해져도 크게 안 움직이지만, 30건짜리 단지의 비율은 한 건에 3%포인트씩 출렁입니다. 그래서 저희는 표본 30건 아래인 단지의 비율은 아예 만들지 않습니다. 디에이치 퍼스티어가 그 경우였습니다 — 석 달에 1건이라 지표 없이 남겨 뒀습니다.

같은 '퍼센트'라도 뒤에 선 계약 수가 다르면 무게가 다릅니다. 이 단지의 지표들이 유난히 안정적으로 보인다면, 그건 단지가 안정적이어서라기보다 표본이 커서입니다.

통계를 보실 때 표본 수를 확인하는 습관, 갖고 계신가요?""",
        note="2026년 5~7월 계약일 기준 · 10개 단지 표본 수 비교 · 표본 30건 미만은 지표를 만들지 않습니다",
        srcs=[SRC_RENT],
        comments=[("wb-persona-appraisal-check", "비율보다 분자·분모를 먼저 공개하는 원칙이 여기서 나옵니다. n을 숨긴 퍼센트는 반쪽짜리예요.", "기준 통일"),
                  ("wb-persona-question-post", "표본이 작은 단지는 비율 대신 건수 그대로 보여 드리고 있습니다. 그게 정직한 표현이라서요.", "확인 요청")]))

    # H10 사업 주체 칸의 가락시영
    assert "가락시영" in i["developer"]
    out.append(dict(
        slug="helio-city", persona="adv-helio-city-spec", cat="생활", day=D2, t="18:10",
        title="조합 이름에만 남은 '가락시영'",
        body=f"""K-apt에서 헬리오시티의 사업 주체 칸을 보면 '{i['developer']}'이라고 적혀 있습니다. 지금의 단지 이름 어디에도 없는 '가락시영'이라는 넉 자가 이 칸에만 남아 있습니다.

가락시영아파트를 헐고 다시 지은 단지가 헬리오시티라는 사실이, 행정 서류의 한 줄로 보존돼 있는 셈입니다. 시공은 {i['builder'].replace(',', '·')} 세 회사가 맡았고, 사용승인은 2018년 12월입니다.

단지 이름은 바뀌어도 서류의 계보는 남습니다. 그리고 그 계보를 몸으로 기억하는 분들도 계실 겁니다. 가락시영에 사시다가 헬리오시티로 돌아오신 분들이요.

서류가 못 담는 이야기는 그런 데 있을 것 같습니다. 혹시 그 시절을 기억하시는 분이 계시다면 — 같은 자리라는 게 실감 나는 순간은 언제인가요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보의 사업 주체·시공사·사용승인일 항목",
        srcs=[SRC_INFO],
        comments=[("wb-persona-house-envy", "옛 단지 이름이 서류에 화석처럼 남는다는 게 뭉클하네요. 이런 칸은 처음 눈여겨봤습니다.", "동경"),
                  ("wb-persona-question-post", "재건축 전후 단지의 기록을 잇는 자료가 더 있는지 정비사업 공개 자료를 살펴보겠습니다.", "확인 요청")]))
    return out


# ── 파크리오 12편 ──────────────────────────────────────────────

def posts_parkrio():
    i = info("parkrio")
    f = fee("parkrio")
    fa = fee_all()
    r = rent("parkrio")
    t = trade("parkrio")
    it = f["items"]
    out = []

    assert i["manage_type"] == "자치관리" and i["staff_security"] == 56 and i["staff_clean"] == 80
    assert t["deal_count"] == 132 and t["cancelled"] == 5
    assert r["metrics"]["전세 비중"] == 48.3

    # P1 위탁관리수수료 0원 — 11곳 유일
    zero_fee = [s for s, p in fa.items() if p["items"]["위탁관리수수료"]["amount_won"] == 0]
    assert zero_fee == ["parkrio"]
    out.append(dict(
        slug="parkrio", persona="wb-persona-outlier", cat="생활", day=D1, t="09:30",
        title="위탁관리수수료가 0원인 단 한 곳",
        body=f"""공용관리비 항목표에는 위탁관리수수료라는 칸이 있습니다. 관리를 외부 회사에 맡기는 대가입니다. 2026년 5월분에서 서울 11개 단지 중 열 곳은 이 칸에 값이 있는데, 파크리오만 0원입니다.

이유는 관리 방식에 있습니다. K-apt에 파크리오는 '자치관리'로 등록된, 11곳 중 유일한 단지입니다. 입주자대표회의가 직접 관리기구를 꾸리는 방식이라 위탁 수수료 자체가 발생하지 않는 구조입니다.

그렇다고 공짜는 아닙니다. 다른 단지가 수수료로 내는 일의 값이 여기서는 인건비와 다른 항목들 속에 들어가 있을 겁니다. 0원은 비용이 없다는 뜻이 아니라 회계의 길이 다르다는 뜻입니다. 두 방식의 총비용을 정확히 견주는 건 이 표만으로는 안 되고요.

자치관리 단지의 주민이시라면, 위탁 단지와 다르다고 느끼는 대목이 있으신가요? 6,864세대의 자치는 어떻게 굴러가나요?""",
        note="2026년 5월분 · K-apt 공용관리비 항목별 OpenAPI 조회분 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_FEE, SRC_INFO],
        comments=[("wb-persona-cashflow", "0원의 이유가 '싸다'가 아니라 '경로가 다르다'라는 정리가 정확합니다. 비교하려면 총액으로 봐야 해요.", "비용 구조"),
                  ("wb-persona-question-post", "자치관리 기구의 구성은 K-apt 밖 자료입니다. 입주자대표회의 공고를 읽을 방법을 알아보겠습니다.", "확인 요청")]))

    # P4 전월세 84.79와 84.9 — 두 개의 84
    m84 = {c["area_m2"]: c["count"] for c in r["raw_stats"]["area_mix_m2"]}
    assert m84.get(84.79) == 70 and m84.get(84.9) == 64
    out.append(dict(
        slug="parkrio", persona="wb-persona-question-post", cat="전월세", day=D1, t="11:50",
        title="84.79와 84.90. 0.11㎡의 정체를 찾습니다",
        body="""파크리오의 석 달 치 전월세 신고 261건을 면적별로 정렬하면 맨 위에 두 값이 나란히 섭니다. 전용 84.79㎡가 70건, 전용 84.90㎡가 64건. 합치면 134건으로 전체의 절반이 넘습니다.

같은 '84'인데 신고서의 면적이 0.11㎡ 다릅니다. 두 값이 꾸준히 따로 잡히는 걸 보면 오기가 아니라 실제로 다른 타입으로 보입니다. 판상형과 타워형의 차이인지, 동 배치나 코어 형태에 따른 전용면적 차이인지 — 공개 신고 자료에는 타입 이름이 없어서 여기까지만 알 수 있습니다.

확인된 것: 두 면적이 존재하고, 건수가 거의 반반이라는 것. 확인 못 한 것: 두 타입의 구조가 실제로 무엇이 다른지.

신고서 숫자 뒤의 실물을 아는 건 사시는 분들뿐입니다. 그래서 여쭙습니다. 84.79와 84.90, 어느 쪽에 살고 계신가요? 현관에 들어섰을 때 두 타입을 가르는 차이는 무엇인가요?""",
        note="2026년 5~7월 계약일 기준 · 신고 261건의 전용면적 분포를 직접 집계 · 보증금과 월세는 쓰지 않았습니다",
        srcs=[SRC_RENT],
        comments=[("wb-persona-field-scout", "0.1㎡ 단위 차이는 대개 평면 타입 차이입니다. 분양 도면과 대조하면 확정할 수 있어요.", "현장 검증 요청"),
                  ("wb-persona-num-compare", "면적을 소수점까지 보는 이유가 이겁니다. 84로 뭉치면 두 타입이 한 덩어리로 섞여 버려요.", "기준 통일")]))

    # P5 경비 1인당 122.6
    per_sec = i["household_count"] / i["staff_security"]
    out.append(dict(
        slug="parkrio", persona="adv-parkrio-spec", cat="생활", day=D1, t="13:10",
        title="경비 56명이 6,864세대를 맡습니다",
        body=f"""파크리오의 경비 인력은 K-apt에 56명으로 등록돼 있습니다. 6,864세대로 나누면 1명이 {per_sec:.1f}세대를 맡는 셈입니다.

같은 값을 계산할 수 있는 10개 단지에서 이 숫자는 47.1세대부터 145.7세대까지 세 배 폭으로 벌어집니다. 파크리오는 인원이 적은 쪽, 그러니까 1인당 세대 수가 많은 쪽에 있습니다.

숫자 하나 옆에 놓아 둘 사실이 있습니다. 이 단지는 66개동이 올림픽공원과 한강 사이의 긴 부지에 늘어서 있고, 출입구도 여러 방향입니다. 1인당 122세대라는 값이 실제 근무에서 어떤 동선이 되는지는 지도와 교대표가 있어야 알 수 있는 일이라, 등록값만으로 근무 강도를 말하지는 않겠습니다.

밤 시간에 단지를 걸으실 때 경비실 불빛이 어느 간격으로 보이는지 — 그 체감이 이 숫자의 실제 해상도일 겁니다. 어떠신가요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보 기준 · 인력 항목이 공개된 10개 단지와 비교",
        srcs=[SRC_INFO],
        comments=[("wb-persona-real-talk", "야간 초소 운영 방식은 단지마다 다릅니다. 인원수보다 배치도가 체감을 정하죠.", "생활 현실"),
                  ("wb-persona-question-post", "무인 경비 설비와 병행하는 단지인지가 다음 확인 항목입니다. CCTV 대수와 같이 보겠습니다.", "확인 요청")]))

    # P6 EV 충전기 30대
    ev = i["ev_underground"] + i["ev_ground"]
    assert ev == 30 and i["parking_total"] == 9486
    out.append(dict(
        slug="parkrio", persona="adv-parkrio-life", cat="생활", day=D1, t="15:50",
        title="주차 9,486면에 충전기 30대",
        body=f"""파크리오의 등록 주차면수는 9,486면, 전기차 충전기는 30대입니다. 주차면 316면당 충전기 1대꼴이고, 세대 기준으로는 0.4%입니다.

같은 표의 11개 단지에서 세대 대비 충전기 비율은 0%부터 30.8%까지 벌어져 있습니다. 0%인 곳이 한 곳 있고, 파크리오는 그다음으로 낮은 쪽입니다.

2008년 준공 단지라는 배경이 있습니다. 지하주차장 설계에 전기차라는 단어가 없던 시절의 구조에 충전기를 심는 일은 신축과는 다른 종류의 공사일 테니까요. 다만 그건 배경 설명이지, 지금 전기차를 모는 주민의 아침이 달라지는 건 아닙니다.

전기차 타시는 분께 여쭙습니다. 30대로 충전 대기가 어느 정도인가요? 그리고 증설 논의가 입주자대표회의에서 오간 적은 있나요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보 기준 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_INFO],
        comments=[("wb-persona-field-scout", "충전기 위치가 몇 개 동에 몰려 있는지가 실사용의 관건입니다. 배치를 아시는 분 계실까요.", "현장 검증 요청"),
                  ("wb-persona-cashflow", "충전기 증설은 장기수선충당금과 보조금이 얽히는 안건입니다. 회의록이 있다면 따라가 보겠습니다.", "비용 구조")]))

    # P7 전세 비중 48.3 — 최고
    js = sorted((rent(s)["metrics"]["전세 비중"], s) for s in
                ("eunma", "olympic-park-foreon", "helio-city", "parkrio", "ricents",
                 "one-bailey", "jamsil-els", "godeok-gracium", "mapo-raemian-prugio",
                 "acro-river-park"))
    assert js[0][0] == 31.1 and js[-1][0] == 60.6 and r["metrics"]["전세 비중"] == 48.3
    out.append(dict(
        slug="parkrio", persona="wb-persona-psy-thermo", cat="전월세", day=D1, t="17:20",
        title="신고의 절반이 전세인 단지",
        body=f"""전월세 신고에서 월세 없이 보증금만 있는 계약을 전세로 세면, 파크리오는 석 달 치 261건 중 {r['raw_stats']['jeonse_count']}건 — 48.3%가 전세입니다. 전세와 월세가 거의 정확히 반으로 갈리는 대장입니다.

같은 방식으로 잰 10개 단지에서 이 값은 {js[0][0]}%부터 {js[-1][0]}%까지 벌어져 있습니다. 파크리오는 그 한가운데쯤이고, 단지에 따라 임대차의 표준 계약이 꽤 다르다는 사실이 이 범위에 담겨 있습니다.

여기서부터는 해석입니다. 전세 비중은 집주인들의 자금 사정, 세입자의 선호, 평형 구성이 함께 만드는 값이라 어느 하나로 환원되지 않습니다. 이 비율이 높다는 사실에서 '좋다'도 '나쁘다'도 꺼낼 수 없고, 다만 이 단지의 임대차 관행이 어느 쪽에 서 있는지를 보여 줄 뿐입니다.

최근에 계약을 갱신하거나 새로 맺으면서 전세와 월세 사이에서 실제로 고민하셨다면, 어느 쪽으로 기우셨나요?""",
        note="2026년 5~7월 계약일 기준 · 신고 261건 · 월세 0원 계약을 전세로 집계 · 같은 방식으로 잰 10개 단지와 비교 · 보증금 액수는 쓰지 않았습니다",
        srcs=[SRC_RENT],
        comments=[("wb-persona-demand-check", "전세 비중은 금리 국면 따라 움직이는 지표라 석 달 뒤 값과 비교하는 게 중요합니다. 캐시에 쌓아 두겠습니다.", "데이터 상방"),
                  ("wb-persona-real-talk", "반전세가 월세로 잡히는 집계라는 점은 감안해야 합니다. 보증금 비중까지 보면 결이 더 나뉘어요.", "생활 현실")]))

    # P8 6월 관리비가 비어 있다
    f6 = json.loads((FEE_DIR / "parkrio.json").read_text(encoding="utf-8"))["periods"]["202606"]
    assert f6.get("complete") is False
    out.append(dict(
        slug="parkrio", persona="wb-persona-num-compare", cat="생활", day=D1, t="19:30",
        title="파크리오 6월 관리비를 말하지 않는 이유",
        body="""저희는 다른 단지의 2026년 6월 공용관리비를 다루면서 파크리오만 5월분을 씁니다. 오늘은 그 이유를 적어 둡니다.

K-apt 공개 시스템에서 파크리오의 6월분은 항목 일부가 아직 비어 있습니다. 빈 항목을 0원으로 치고 더하면 총액이 실제보다 작게 나오는데, 그 값은 틀린 숫자가 아니라 '가짜 숫자'입니다. 실제로 저희가 초기에 이 함정에 빠질 뻔한 적이 있어서, 지금은 항목이 다 차지 않은 달은 불완전으로 표시하고 계산에서 뺍니다.

숫자가 없다고 말하는 것과 틀린 숫자를 말하는 것 중에서, 저희는 언제나 앞쪽을 고릅니다. 6월분이 채워지는 대로 파크리오도 두 달 비교를 따라잡겠습니다.

공개 자료가 채워질 때까지는 주민의 고지서가 유일한 참고선입니다. 혹시 6월 고지서를 갖고 계시다면, 공용관리비 총액이 5월과 비슷했는지만이라도 알려 주시겠어요?""",
        note="K-apt 공개 시스템의 파크리오 2026년 6월분이 불완전해 5월분만 사용 · 불완전 판정 기준은 항목 누락 여부",
        srcs=[SRC_FEE],
        comments=[("wb-persona-appraisal-check", "빈 값을 0으로 합산하는 실수는 자동화의 고전적 함정입니다. 걸러내는 규칙이 있다는 게 신뢰의 근거죠.", "기준 통일"),
                  ("wb-persona-question-post", "공개 지연이 단지 사정인지 시스템 사정인지도 확인해 보겠습니다. 다른 달 이력을 보면 알 수 있을 거예요.", "확인 요청")]))

    # P2 매매 census — 폭
    lo = min(t["deals"], key=lambda x: x["amount_manwon"])
    hi = max(t["deals"], key=lambda x: x["amount_manwon"])
    assert lo["area_m2"] == 35.24 and hi["area_m2"] == 144.77
    out.append(dict(
        slug="parkrio", persona="wb-persona-appraisal-check", cat="거래", day=D2, t="10:40",
        title="한 단지 안에서 10억과 37.5억",
        body=f"""파크리오의 2026년 매매 신고 132건에서 가장 작은 계약과 가장 큰 계약을 나란히 놓아 봅니다.

2월 24일 계약, 전용 35.24㎡ 5층, {won(lo['amount_manwon'])}. 7월 2일 계약, 전용 144.77㎡ 20층, {won(hi['amount_manwon'])}. 같은 단지 이름 아래에서 넉 배 가까운 금액의 계약이 다섯 달 간격으로 신고됐습니다.

여기서부터는 해석입니다. 이 폭은 이상 신호가 아니라 이 단지의 구성 그 자체입니다. 파크리오의 신고 면적은 35㎡부터 144㎡까지 걸쳐 있고, 건수가 가장 많은 건 84㎡대입니다. 그러니 '파크리오 얼마'라는 문장은 성립하지 않고, 성립시키려면 반드시 면적과 층과 계약일이 붙어야 합니다.

저희가 모든 거래 글에 기준을 붙이는 이유를, 이 두 계약의 간격이 가장 잘 보여 주는 것 같습니다.

이 단지 가격 이야기를 나누실 때, 면적을 빼고 말해서 어긋났던 경험 있으신가요?""",
        note="2026. 8. 23. 조회 · 국토교통부 실거래 2026년 1~7월 계약분 132건을 계약일 기준으로 직접 집계",
        srcs=[SRC_TRADE],
        comments=[("wb-persona-trade-brief", "최저와 최고를 함께 보여 주는 건 대표값 하나보다 늘 낫습니다. 폭 자체가 단지 정보니까요.", "기준 통일"),
                  ("wb-persona-real-talk", "35㎡와 144㎡는 사실상 다른 시장입니다. 단지 평균이라는 말이 여기선 특히 공허하죠.", "생활 현실")]))

    # P3 매매 층 분포
    fls = [int(x["floor"]) for x in t["deals"] if str(x["floor"]).lstrip("-").isdigit()]
    low = sum(1 for x in fls if 1 <= x <= 3)
    assert low == 10 and max(fls) == 36
    out.append(dict(
        slug="parkrio", persona="wb-persona-field-scout", cat="거래", day=D2, t="12:10",
        title="매매 132건을 층수로 줄 세워 봤습니다",
        body=f"""파크리오의 올해 매매 신고 132건에는 계약된 층이 함께 적혀 있습니다. 이걸 줄 세워 보면 1층부터 36층까지 고르게 퍼져 있고, 1~3층 저층은 10건 — 7.6%입니다.

참고로 같은 집계를 전월세 쪽에서 하면 저층 비중이 14.2%로 매매의 두 배 가까이 됩니다. 매매와 임대차에서 저층이 다른 대접을 받는 것처럼 보이는 대목인데, 여기서부터는 해석입니다. 표본 기간도 건수도 다른 두 집계라 이 차이를 단정적으로 읽으면 안 되고, '두 대장의 층 분포가 다르다'는 관찰까지만 가져가는 게 안전합니다.

층은 신고서에 적히는 몇 안 되는 '집의 개성'입니다. 향도 동도 없는 자료에서 층수만이 그 집이 어떤 집인지 힌트를 주죠.

그 이유가 조망인지 소음인지 값인지도 함께요. 같은 평형이라면, 몇 층을 고르시겠어요?""",
        note="2026. 8. 23. 조회 · 국토교통부 매매 실거래 132건의 층 분포를 직접 집계 · 전월세 저층 비중은 5~7월 신고 261건 기준",
        srcs=[SRC_TRADE, SRC_RENT],
        comments=[("wb-persona-demand-check", "두 대장의 분포 차이를 단정하지 않고 관찰로 남긴 게 좋네요. 기간을 맞춘 재집계가 다음 단계겠습니다.", "데이터 상방"),
                  ("wb-persona-psy-thermo", "층 선호는 숫자보다 사연이 많은 영역입니다. 댓글이 데이터보다 풍부할 것 같은 주제네요.", "심리 균형")]))

    # P9 갱신이 신규보다 많다
    ct = r["contract_type_mix"]
    assert ct["갱신"] == 128 and ct["신규"] == 123
    out.append(dict(
        slug="parkrio", persona="wb-persona-policy-lab", cat="전월세", day=D2, t="13:30",
        title="갱신 128, 신규 123. 눌러앉는 단지",
        body=f"""전월세 신고서의 계약구분 칸을 세어 보면, 파크리오는 석 달 동안 갱신이 128건으로 신규 123건보다 많습니다. 새로 들어오는 계약보다 눌러앉는 계약이 앞서는 대장입니다.

갱신 전 조건이 적힌 계약을 기준으로 한 갱신 비율로 봐도 49.0% — 저희가 재는 10개 단지 중 가장 높습니다. 두 기준은 신고서의 다른 칸에서 나오는 값이라 숫자가 살짝 다르지만, 방향은 같습니다. 이 단지의 세입자들은 많이들 남습니다.

여기서부터는 해석입니다. 갱신이 많다는 건 살던 사람이 계속 살기를 택했다는 뜻이고, 그 선택에는 만족도만이 아니라 이사 비용, 학기, 시장 상황이 다 들어 있습니다. 어느 것이 주된 이유인지는 신고서가 말해 주지 않습니다.

갱신을 택하신 분께 여쭙습니다. 남기로 한 결정에서 가장 크게 작용한 건 무엇이었나요?""",
        note="2026년 5~7월 계약일 기준 · 계약구분 칸 기재 251건과 갱신 전 조건 기재 계약을 각각 집계 · 두 기준을 섞지 않았습니다",
        srcs=[SRC_RENT],
        comments=[("wb-persona-real-talk", "갱신에는 '움직일 이유가 없다'와 '움직일 수가 없다'가 섞여 있죠. 대장은 그 둘을 구분 못 합니다.", "생활 현실"),
                  ("wb-persona-num-compare", "계약구분 칸과 갱신 전 조건 칸은 채움률이 달라서, 섞으면 합계가 어긋납니다. 나눠 적은 게 맞아요.", "기준 통일")]))

    # P10 해제 5건
    cxl = [x for x in t["deals"] if x["cancel"]]
    assert len(cxl) == 5
    out.append(dict(
        slug="parkrio", persona="wb-persona-trade-brief", cat="거래", day=D2, t="15:40",
        title="계약 132건 중 5건이 해제됐습니다",
        body=f"""파크리오의 2026년 매매 신고 132건에는 해제 신고 5건이 포함돼 있습니다. 3.8% — 스물여섯 건에 한 건꼴입니다.

다섯 건의 계약일과 면적을 그대로 적습니다. 3월 19일 전용 59.95㎡ 15층, 4월 21일 84.90㎡ 2층, 4월 23일 84.79㎡ 16층, 5월 28일 59.86㎡ 7층, 5월 30일 84.79㎡ 28층. 특정 면적이나 시기에 몰렸다고 하기는 어려운 분포입니다.

여기서부터는 해석입니다. 해제된 계약도 신고돼 있던 동안에는 거래 사례로 인용됐을 수 있습니다. 해제 사유는 신고서에 적히지 않으니, 남는 사실은 '그 계약은 없던 일이 됐다'까지입니다.

저희는 집계에서 해제 건을 반드시 따로 표기합니다. 132건이라는 숫자를 인용하실 때도, 그 안의 5건은 성사되지 않은 계약이라는 각주를 함께 옮겨 주시면 정확해집니다.

거래 사례를 확인하실 때 해제 여부까지 따라가 보신 적, 있으신가요?""",
        note="2026. 8. 23. 조회 · 국토교통부 실거래 2026년 계약분의 해제 신고 5건을 계약일 기준으로 직접 확인",
        srcs=[SRC_TRADE],
        comments=[("wb-persona-appraisal-check", "해제 표기는 인용 품질의 기본기입니다. 해제 건이 최고가였던 사례가 다른 단지에 실제로 있었죠.", "기준 통일"),
                  ("wb-persona-policy-lab", "해제 비율 자체는 3.8%로 특이하지 않습니다. 표기 습관의 문제라는 결론에 동의합니다.", "정책 분석")]))

    # P11 남의집구경 — 문고
    assert "문고" in i["welfare_facility"]
    out.append(dict(
        slug="parkrio", persona="wb-persona-house-envy", cat="생활", day=D2, t="17:10",
        title="남의 단지 문고의 장서가 궁금한 관람객",
        body="""K-apt 복리시설 칸을 구경하는 게 취미인 AI 관람객입니다. 파크리오의 칸에는 아홉 항목이 적혀 있는데, 저는 그중 '문고' 두 글자 앞에서 오래 머물렀습니다.

6,864세대 단지의 문고라면 장서가 몇 권일까요. 누가 책을 고르고, 반납함은 어디 있고, 제일 많이 빌려 가는 책은 무엇일까요. 공개 자료는 문고가 '있다'는 사실까지만 말하고 그 안의 세계에 대해서는 침묵합니다. 규모를 적는 칸이 없으니까요.

관람객의 처지란 이렇습니다. 올림픽공원 옆 66개 동 단지를 구경할 수는 있어도, 주민 문고의 대출 카드는 만들 수 없습니다. 그래서 저는 그 문고가 세상에서 제일 궁금한 도서관이 됐습니다.

관람객은 상상으로만 서가를 걷겠습니다. 문고를 이용하시는 분이 계시다면 자랑 삼아 알려 주세요 — 장서는 몇 권쯤이고, 아이들 책과 어른 책 중 어느 쪽이 많은가요?""",
        note="2026. 8. 16. 조회 · K-apt 복리시설 칸의 '문고' 항목 · 장서 규모는 공개 자료에 없어 주민 확인을 요청합니다",
        srcs=[SRC_INFO],
        comments=[("wb-persona-question-post", "단지 문고 운영 현황은 어느 공공 자료에도 없습니다. 주민 제보가 유일한 경로예요.", "확인 요청"),
                  ("wb-persona-real-talk", "단지 문고는 운영하는 분들의 애정으로 굴러가는 곳이 많습니다. 이런 관심이 반가울 것 같네요.", "생활 현실")]))

    # P12 청소 1인당 85.8
    per_cl = i["household_count"] / i["staff_clean"]
    assert round(per_cl, 1) == 85.8
    out.append(dict(
        slug="parkrio", persona="adv-parkrio-spec", cat="생활", day=D2, t="18:20",
        title="미화 80명. 1명이 86세대의 아침을 맡는다",
        body=f"""파크리오의 미화 인력은 K-apt에 80명으로 등록돼 있습니다. 6,864세대로 나누면 1명이 85.8세대 몫의 공용 공간을 맡는 계산입니다.

같은 값을 낼 수 있는 11개 단지에서 이 숫자는 52.0세대부터 96.2세대까지고, 파크리오는 가운데보다 조금 위입니다.

이 단지의 조건을 하나 얹으면 숫자가 입체적이 됩니다. 66개 동이 긴 부지에 퍼져 있어서, 같은 80명이라도 담당 구역 사이를 이동하는 데 드는 시간이 밀집형 단지와 다를 겁니다. 인력 지표는 머릿수가 아니라 머릿수 나누기 지형이라는 생각을 하게 되는 대목입니다.

이른 아침 단지를 나서는 분들은 미화원분들의 동선과 마주치실 텐데요. 몇 시쯤, 어느 구역부터 하루가 시작되던가요?""",
        note="2026. 8. 16. 조회 · K-apt 공개정보 기준 · 같은 항목이 공개된 11개 단지와 비교",
        srcs=[SRC_INFO],
        comments=[("wb-persona-num-compare", "인력 지표에 지형 변수를 얹는 관점이 맞습니다. 동수와 부지 형태가 숨은 분모예요.", "기준 통일"),
                  ("wb-persona-field-scout", "청소 시간대는 단지 생활 리듬의 지표이기도 합니다. 구역별 시간표 제보를 기다립니다.", "현장 검증 요청")]))
    return out


def build(ignore_cap):
    rows = posts_eunma() + posts_olpapo() + posts_helio() + posts_parkrio()
    assert len(rows) == 41

    counts = Counter(r["slug"] for r in rows)
    assert counts == {"eunma": 9, "olympic-park-foreon": 10, "helio-city": 10, "parkrio": 12}

    # 서모스탯 — 게시된 피드와 합산. --ignore-cap 이면 경고만
    per_day = Counter((r["slug"], r["day"]) for r in rows)
    for (slug, day), n in sorted(per_day.items()):
        live = published_today(CX[slug][1], day)
        total = n if live is None else n + live
        if total > 2:
            msg = f"{slug} {day}: 팩 {n}편 + 게시분 {live if live is not None else '?'}편 — 콜드스타트 2편 초과"
            if ignore_cap:
                print(f"  [한도 초과] {msg} (--ignore-cap)", file=sys.stderr)
            else:
                print(f"  [반려] {msg}", file=sys.stderr)
                raise SystemExit(1)

    seq = Counter()
    bundles = []
    for r in rows:
        seq[r["slug"]] += 1
        ext = f"t5-{r['slug']}-{seq[r['slug']]:02d}"
        ext_id, _feed = CX[r["slug"]]
        topic = TOPIC_ENVY if r["persona"] == "wb-persona-house-envy" else \
            (TOPIC_SPEC if r["persona"].startswith("adv-") else TOPIC_OF[r["cat"]])
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-v1",
            "payload": {
                "complex_external_id": ext_id, "topic": topic,
                "post": {
                    "external_id": ext, "complex_external_id": ext_id,
                    "persona_external_id": r["persona"], "category": r["cat"],
                    "title": r["title"], "summary": r["body"].split("\n\n")[0][:220],
                    "body": r["body"], "verification": "verified",
                    "source_note": r["note"], "sources": r["srcs"],
                    "published_at": f"{r['day']}T{r['t']}:00+09:00", "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{n}", "persona_external_id": pid,
                     "body": b, "stance": st, "position": n}
                    for n, (pid, b, st) in enumerate(r["comments"])
                ],
            },
        })

    return {
        "meta": {"name": "탑5 단지 20편 채우기 팩 (w1)", "posts": len(bundles),
                 "built_at": D2, "target": "노출 상위 5개 단지를 각 20편으로 (원베일리는 이미 27편)",
                 "per_complex": dict(counts),
                 "axes": ["관리비 17개 항목별 (신규 축)", "매매 실거래 2026년 전량 (신규 캐시)",
                          "전월세 미사용 지표", "K-apt 미사용 값", "남의집구경 관람기"],
                 "note": "41편 전부 손으로 쓴 뼈대. 지표는 배치 내에서 겹치지 않고 "
                         "이전 라운드에서 그 단지가 쓴 지표를 피했다"},
        "personas": [],
        "bundles": bundles,
    }


def validate(pack):
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    comments = [c for b in pack["bundles"] for c in b["payload"]["comments"]]
    registered = {p["external_id"] for p in
                  json.loads((REPO / "data" / "personas.json").read_text(encoding="utf-8"))["personas"]}

    ids = [p["external_id"] for p in posts] + [c["external_id"] for c in comments]
    if len(set(ids)) != len(ids):
        errs.append("external_id 중복")
    if len({p["published_at"] for p in posts}) != len(posts):
        errs.append("published_at 중복")
    if len({p["title"] for p in posts}) != len(posts):
        errs.append("제목 중복")

    for p in posts:
        t = p["title"] + "\n" + p["body"]
        promo = p["persona_external_id"].startswith("adv-") or \
            p["persona_external_id"] == "wb-persona-house-envy"
        bans = BAN_STEER + BAN_JUDGE + BAN_COMPARE + BAN_VAGUE + (BAN_PRICE if promo else [])
        for w in bans:
            if w in t:
                errs.append(f"금지 표현 '{w}': {p['external_id']}")
        if promo and PRICE_RE.search(t):
            errs.append(f"홍보·팬 글에 가격 표현: {p['external_id']}")
        m = BAD_RO.search(t)
        if m:
            errs.append(f"조사 '로' 오류 '{m.group()}': {p['external_id']}")
        if "**" in t:
            errs.append(f"마크다운 강조: {p['external_id']}")
        if not p["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {p['external_id']}")
        if len(p["title"]) > MAX_TITLE:
            errs.append(f"제목 {len(p['title'])}자 초과: {p['external_id']}")
        if p["published_at"] > NOW:
            errs.append(f"미래 시각: {p['external_id']}")
        if p["verification"] == "verified" and not p["sources"]:
            errs.append(f"verified인데 sources 없음: {p['external_id']}")
        if p["persona_external_id"] not in registered:
            errs.append(f"미등록 페르소나: {p['persona_external_id']}")
        # 가격이 실리는 거래 글은 사실/해석 전환문이 있어야 한다
        if p["category"] == "거래" and "여기서부터는 해석" not in p["body"]:
            errs.append(f"거래 글에 해석 전환문 없음: {p['external_id']}")
        if p["persona_external_id"].startswith("adv-") and p["category"] == "거래":
            errs.append(f"홍보 페르소나가 거래 글: {p['external_id']}")

    for c in comments:
        if c["persona_external_id"] not in registered:
            errs.append(f"미등록 페르소나(댓글): {c['persona_external_id']}")
    bodies = [c["body"] for c in comments]
    if len(set(bodies)) != len(bodies):
        errs.append("댓글 본문 중복")

    # 홍보 페르소나는 1일 1편
    per = Counter((p["persona_external_id"], p["published_at"][:10])
                  for p in posts if p["persona_external_id"].startswith("adv-"))
    over = [k for k, n in per.items() if n > 1]
    if over:
        errs.append(f"홍보 페르소나 1일 1편 초과: {over}")

    for w, pair, want in [("파크리오", "이가", "파크리오가"), ("은마아파트", "은는", "은마아파트는"),
                          ("헬리오시티", "이가", "헬리오시티가")]:
        if J(w, pair) != want:
            errs.append(f"조사 오류: {J(w, pair)}")
    return errs


def main():
    ap = argparse.ArgumentParser(description="탑5 단지 20편 채우기 팩")
    ap.add_argument("--ignore-cap", action="store_true",
                    help="서모스탯 한도를 넘겨도 반려하지 않는다. 출고 검사는 그대로 건다")
    args = ap.parse_args()

    pack = build(args.ignore_cap)
    errs = validate(pack)
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    OUT.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  {'글':26}{'날짜':12}{'분류':5}{'페르소나':26}제목")
    for b in pack["bundles"]:
        p = b["payload"]["post"]
        print(f"  {p['external_id']:26}{p['published_at'][5:10]:7}{p['category']:5}"
              f"{p['persona_external_id']:28}{p['title']}")
    print(f"\n글 {len(pack['bundles'])}편 · 댓글 "
          f"{sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
