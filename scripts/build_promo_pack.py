#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""홍보 페르소나 복귀 팩 — 휴면 12명에게 글을 준다.

왜 휴면이었나
  홍보 페르소나 22명 중 12명이 노출 글 0편이었다. 두 가지가 겹쳤다.
  파일럿 축소로 5곳의 글이 통째로 hidden 됐고, 그 전에 홍보글 7종 템플릿을
  단지별로 찍어 낸 65편이 출고 검사(명세 8.3)에서 반려됐다.

  그래서 되살리는 방식이 중요하다. 반려된 글을 다시 올리는 게 아니라,
  **단지마다 다른 사실 하나에서 글을 시작**한다. 특이값 생성기와 같은 원칙이다.

축
  설계노트 7명 — K-apt 기본정보에서 그 단지에만 해당하는 항목 하나
  생활권  5명 — K-apt 교통·편의·교육 칸에 관리주체가 적어 낸 값

  두 축 모두 "공개 자료에 이렇게 적혀 있다"까지만 말하고, 실제가 어떤지는
  주민에게 묻는다. K-apt 편의시설·교육시설 칸은 관리주체 자기기입값이고
  오타와 빈칸이 흔하다. 이걸 사실로 단정하면 안 된다.

홍보 페르소나 금지선
  가격·전망·매수 권유·인근 단지 폄하. 이 팩은 값을 하나도 다루지 않는다.
  단지 간 비교는 "몇 곳이 같은 값으로 적혀 있다" 수준의 사실 진술까지만 쓴다.

실행
  python3 scripts/build_promo_pack.py --ignore-cap
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
OUT = REPO / "content" / "promo-w1.json"
NOW = "2026-08-21T23:30:00+09:00"
DAY = NOW[:10]

# (디렉터리 slug, 인제스트 external_id, 피드 slug)
CX = {
    "olympic-park-foreon": ("cx-olympic-park-foreon", "olympic-park-foreon"),
    "ricents": ("cx-ricents", "ricents"),
    "acro-river-park": ("cx-acro-river-park", "acro-river-park"),
    "dh-firstier": ("cx-dh-firstier", "dh-firstier-ipark"),
    "jamsil-els": ("cx-jamsil-els", "jamsil-els"),
    "godeok-gracium": ("cx-godeok-gracium", "godeok-gracium"),
    "mapo-raemian-prugio": ("cx-mapo-raemian-prugio", "mapo-raemian-prugio"),
}
FEED_BASE = os.environ.get("BASE_URL", "https://danji.life")

SRC_KAPT = {"label": "공동주택 기본 정보제공 서비스(K-apt) OpenAPI",
            "url": "https://www.data.go.kr/data/15058453/openapi.do", "publisher": "국토교통부"}
SRC_PARK = {"label": "하늘공원 억새축제 안내 — 장소 표기",
            "url": "https://mediahub.seoul.go.kr/archives/2012557", "publisher": "서울특별시"}

TOPIC_SPEC = {"external_id": "wb-topic-2026-08-promo-spec", "title": "공개 자료에 적힌 우리 단지",
              "summary": "K-apt에 등록된 항목을 그대로 읽고, 빈칸은 빈칸이라고 말한다",
              "category": "생활", "heat": 3}
TOPIC_LIFE = {"external_id": "wb-topic-2026-08-promo-life", "title": "걸어서 닿는 것들",
              "summary": "관리주체가 적어 낸 생활 인프라 목록을 옮기고, 실제는 주민에게 묻는다",
              "category": "생활", "heat": 3}

NOTE_KAPT = ("2026. 8. 16. 조회 · K-apt 공동주택 기본 정보제공 서비스 등록값 · "
             "복리시설·편의시설·교육시설 칸은 관리주체 기입값이라 실제와 다를 수 있습니다")

BAN_PRICE = ["억", "호가", "시세", "매수", "매도", "상승", "하락", "전망", "집값", "평당"]
BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "뒤처", "명문", "상위권", "학군지",
             "가장 좋", "가장 나쁜", "최고의", "최하", "명문학군"]
BAN_COMPARE = ["보다 낫", "보다 좋", "보다 우수", "보다 편리", "부럽"]
BAN_VAGUE = ["인터넷에서", "알려져 있", "라고 한다", "찾아보니", "카더라"]
# '로/으로'를 잘못 붙인 자리를 잡는다. 단어 목록으로 잡으면 '하늘공원로 95' 같은
# 도로명이 걸린다 — 숫자와 단위가 앞에 올 때만 오류다.
BAD_RO = re.compile(r"\d+(?:,\d{3})*\s*(?:명|층|원|동|분|회|대|개)로(?![가-힣])")

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


def info(slug):
    return json.loads((INFO_DIR / f"{slug}.json").read_text(encoding="utf-8"))


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


# ── 글 12편 ────────────────────────────────────────────────────
# 뼈대를 함수로 공유하지 않는다. 공유하는 순간 마스킹 후 같은 글이 된다.
# 반려 65편이 정확히 그렇게 나왔다 — 템플릿 7종에 단지를 인자로 넣은 결과였다.

def posts():
    o = info("olympic-park-foreon")
    r = info("ricents")
    a = info("acro-river-park")
    d = info("dh-firstier")
    e = info("jamsil-els")
    g = info("godeok-gracium")
    m = info("mapo-raemian-prugio")
    out = []
    # 본문에 한글 수사(여덟·넷·일곱)를 쓴 자리는 캐시가 바뀌면 조용히 틀어진다.
    # 숫자로 바꿔 쓸 수 없는 자리이므로 값이 그대로인지 여기서 못박는다.
    assert len([x for x in a["welfare_facility"].split(",")]) == 9, "아리팍 복리시설 항목 수가 바뀌었다"
    assert len([x for x in g["welfare_facility"].split(",")]) == 8, "그라시움 복리시설 항목 수가 바뀌었다"
    assert g["education_facility"].count(",") + 3 == 14, "그라시움 교육시설 학교 수가 바뀌었다"
    assert m["convenient_facility"].count("(") == 2, "마래푸 편의시설 칸 구성이 바뀌었다"

    # 1. 올파포설계노트 — 빈칸
    out.append(dict(
        slug="olympic-park-foreon", persona="adv-olympic-park-foreon-spec", axis="spec",
        title="복리시설 칸이 비어 있습니다. 실제로는요?",
        body=f"""K-apt 공동주택 기본정보에서 올림픽파크 포레온을 열면 복리시설 칸이 비어 있습니다. 편의시설과 교육시설 칸도 마찬가지입니다. 쓰레기 처리 방식 칸도 비어 있고요.

채워져 있는 쪽은 규모와 구조입니다. {o['structure']}, {o['dong_count']}개동, {o['household_count']:,}세대, 최고 {o['top_floor']}층. 주차는 지상 없이 지하 {o['parking_underground']:,}대입니다.

여기서부터는 해석입니다. {o['use_approval_date'][:4]}년 {int(o['use_approval_date'][4:6])}월 사용승인이니 등록이 아직 안 찬 것으로 보입니다. 빈칸이 곧 없다는 뜻은 아니죠. 다만 공개 자료만 보는 사람에게는 없는 것과 구분되지 않습니다.

단지 안에 실제로 무엇이 있는지 알려 주시면 그대로 적어 두겠습니다. 요즘 쓰고 계신 시설은 어디인가요?""",
        comments=[("wb-persona-question-post",
                   "빈칸을 채워 달라고 관리사무소에 요청하는 절차가 따로 있는지도 같이 확인해 두겠습니다.", "확인 요청"),
                  ("wb-persona-field-scout",
                   "등록이 늦은 건 새 단지에서 흔합니다. 다만 그 사이에는 사시는 분 말이 유일한 자료예요.", "현장 검증 요청")]))

    # 2. 리센츠설계노트 — 네 회사가 나눠 지었다
    out.append(dict(
        slug="ricents", persona="adv-ricents-spec", axis="spec",
        title="네 회사가 나눠 지었습니다. 동마다 다른가요",
        body=f"""리센츠의 K-apt 시공사 항목에는 네 곳이 적혀 있습니다. {r['builder'].replace(',', '·')}. 사용승인일은 {r['use_approval_date'][:4]}년 {int(r['use_approval_date'][4:6])}월 {int(r['use_approval_date'][6:])}일입니다.

한 회사가 전부 지은 단지도 있고 이렇게 나눠 지은 단지도 있습니다. 다만 어느 동을 어느 회사가 맡았는지는 공개 자료에 없습니다. 시공사 이름만 나란히 적혀 있을 뿐이에요.

같은 표에서 복리시설 칸은 비어 있습니다. 등록된 값은 {r['dong_count']}개동 {r['household_count']:,}세대, 최고 {r['top_floor']}층, 지하 주차 {r['parking_underground']:,}대까지입니다.

창호든 마감이든, 같은 단지인데 동마다 다르더라 싶었던 게 있으신가요?""",
        comments=[("wb-persona-field-scout",
                   "공동 시공 단지는 동별 사양 차이 이야기가 꾸준히 나옵니다. 자료로는 안 잡히는 대목이에요.", "현장 검증 요청"),
                  ("wb-persona-question-post",
                   "동별 시공사 배분은 사업시행인가 서류에 남아 있을 수 있습니다. 열람 경로를 찾아보겠습니다.", "확인 요청")]))

    # 3. 아리팍설계노트 — 구조 + 단독 시공 + 복리시설 9종
    w = [x.strip() for x in a["welfare_facility"].split(",")]
    out.append(dict(
        slug="acro-river-park", persona="adv-acro-river-park-spec", axis="spec",
        title="철골철근콘크리트. 11곳 중 두 곳뿐입니다",
        body=f"""아크로리버파크는 구조 항목이 {a['structure']}로 적혀 있습니다. 우리가 같은 표로 보는 11개 단지 가운데 이 값이 적힌 곳은 두 곳입니다. 나머지는 철근콘크리트구조이거나 철골콘크리트구조로 등록돼 있어요.

시공은 {a['builder'].replace('(주)', '')} 한 곳, 사업 주체는 {a['developer']}입니다. 사용승인은 {a['use_approval_date'][:4]}년 {int(a['use_approval_date'][4:6])}월이고요.

복리시설 칸에는 아홉 항목이 등록돼 있습니다. {' · '.join(w)}.

목록은 있는데 규모가 없습니다. 문고에 책이 몇 권인지, 커뮤니티공간이 얼마나 되는지는 적는 칸 자체가 없어요. {a['dong_count']}개동 {a['household_count']:,}세대입니다. 이 목록 가운데 실제로 발길이 가는 데는 어디인가요?""",
        comments=[("wb-persona-question-post",
                   "구조 항목은 내진이나 층간소음과 바로 이어지지 않습니다. 표기 기준을 따로 확인해 두겠습니다.", "확인 요청"),
                  ("wb-persona-field-scout",
                   "아홉 항목 중 실제로 문이 열려 있는 곳이 몇인지가 늘 관건입니다.", "현장 검증 요청")]))

    # 4. 디퍼아설계노트 — 복도 유형 '기타'
    out.append(dict(
        slug="dh-firstier", persona="adv-dh-firstier-spec", axis="spec",
        title="복도 유형이 '기타'로 적힌 단 한 곳입니다",
        body=f"""K-apt 복도 유형 칸에는 보통 계단식·복도식·혼합식 중 하나가 들어갑니다. 디에이치 퍼스티어 아이파크는 '{d['hall_type']}'로 적혀 있어요. 11개 단지 중 이 값을 쓴 곳은 여기 하나입니다.

'{d['hall_type']}'가 무엇을 가리키는지는 항목 설명에 없습니다. {d['dong_count']}개동을 한 값으로 묶기 어려워 그렇게 됐을 수도 있고, 세 분류에 안 들어가는 평면이 섞여 있을 수도 있습니다. 어느 쪽인지 우리는 확인하지 못했습니다.

같은 표에 함께 등록된 값은 이렇습니다. {d['household_count']:,}세대, 최고 {d['top_floor']}층, 승강기 {d['elevator_count']}대, 지하 주차 {d['parking_underground']:,}대.

계단식인 동과 아닌 동이 섞여 있다면 그게 '기타'의 실체일 텐데, 그건 사시는 분들만 아십니다. 사시는 동은 어느 쪽인가요?""",
        comments=[("wb-persona-field-scout",
                   "평면이 섞인 단지는 같은 단지 안에서도 겨울 체감이 갈리는 편입니다.", "현장 검증 요청"),
                  ("wb-persona-question-post",
                   "K-apt 항목 정의서에 '기타'의 기준이 있는지 찾아보고, 없으면 없다고 적어 두겠습니다.", "확인 요청")]))

    # 5. 엘스설계노트 — 차량수거방식
    out.append(dict(
        slug="jamsil-els", persona="adv-jamsil-els-spec", axis="spec",
        title="음식물 처리가 차량수거방식으로 적힌 곳",
        body=f"""잠실엘스의 음식물 쓰레기 처리 방식은 K-apt에 '{e['garbage_type']}'으로 등록돼 있습니다. 11개 단지 중 이 값이 적힌 곳은 여기 하나예요. 다른 곳은 음식물쓰레기종량제나 거점장비수거방식으로 적혀 있습니다.

세 값이 실제 운영에서 어떻게 다른지는 이 항목만으로 알 수 없습니다. 배출 장소도, 시간도, 요금 부과 방식도 적는 칸이 없거든요. 이름만 남아 있는 셈입니다.

단지 규모는 {e['dong_count']}개동 {e['household_count']:,}세대, 사용승인은 {e['use_approval_date'][:4]}년 {int(e['use_approval_date'][4:6])}월입니다.

어디에 내놓고 언제 걷어 가는지 적어 주시면 항목 이름 옆에 그 설명을 붙여 두겠습니다. 실제로는 어떻게 버리시나요?""",
        comments=[("wb-persona-question-post",
                   "같은 항목명을 쓰는 다른 단지와 운영이 같은지도 확인해 볼 만합니다.", "확인 요청"),
                  ("wb-persona-field-scout",
                   "쓰레기 동선은 매일 걷는 길입니다. 자료에 없는 대목치고는 체감이 큽니다.", "현장 검증 요청")]))

    # 6. 그라시움설계노트 — 목록에 없는 두 항목
    gw = [x.strip() for x in g["welfare_facility"].split(",")]
    out.append(dict(
        slug="godeok-gracium", persona="adv-godeok-gracium-spec", axis="spec",
        title="목록에 휴게시설과 유치원이 없습니다",
        body=f"""고덕그라시움의 K-apt 복리시설 칸은 여덟 항목입니다. {' · '.join(gw)}.

같은 항목표를 쓰는 다른 단지에는 여기에 '휴게시설'과 '유치원'이 더 붙어 있는 곳이 있습니다. 이 단지 목록에는 그 둘이 없습니다.

없다는 뜻인지 등록을 안 한 것인지는 자료로 구분되지 않습니다. 이 칸은 관리주체가 채우고, 빈칸의 이유는 남지 않으니까요. 우리가 확인할 수 있는 건 적혀 있는 것과 적혀 있지 않은 것의 차이까지입니다.

{g['dong_count']}개동 {g['household_count']:,}세대입니다. 단지 안에 쉬어 갈 자리와 유치원이 실제로 있나요? 있다면 어디쯤인가요?""",
        comments=[("wb-persona-field-scout",
                   "목록에 없다가 실제로는 있는 경우가 종종 있습니다. 반대도 있고요.", "현장 검증 요청"),
                  ("wb-persona-question-post",
                   "유치원은 인가 여부에 따라 등록 칸이 갈릴 수 있습니다. 그 기준을 확인해 두겠습니다.", "확인 요청")]))

    # 7. 마래푸설계노트 — 재개발
    out.append(dict(
        slug="mapo-raemian-prugio", persona="adv-mapo-raemian-prugio-spec", axis="spec",
        title="11곳 중 재개발로 적힌 곳은 여기 하나입니다",
        body=f"""K-apt 사업 주체 칸을 보면 마포래미안푸르지오는 '{m['developer']}'입니다. 우리가 같은 표로 보는 11개 단지 가운데 재개발로 적힌 곳은 여기 하나예요. 나머지는 재건축조합이거나 시공사 이름이 그 자리에 들어가 있습니다.

재건축과 재개발은 이름만 다른 게 아니라 대상이 다릅니다. 재건축은 기존 공동주택을 헐고 다시 짓고, 재개발은 주택과 함께 도로·상하수도 같은 기반시설을 정비합니다.

시공은 {m['builder'].replace(',', '과 ')}, 사용승인은 {m['use_approval_date'][:4]}년 {int(m['use_approval_date'][4:6])}월 {int(m['use_approval_date'][6:])}일입니다. {m['dong_count']}개동 {m['household_count']:,}세대고요.

여기서부터는 해석입니다. 사업 종류가 다르면 단지 밖으로 나가는 길이 만들어진 과정도 다릅니다. 지금 주로 쓰시는 출입구는 어느 쪽인가요?""",
        comments=[("wb-persona-question-post",
                   "정비사업 종류는 준공 이후 생활과 직접 이어지진 않습니다. 다만 길의 내력은 남습니다.", "확인 요청"),
                  ("wb-persona-field-scout",
                   "출입구 이야기는 자료가 못 따라가는 영역입니다. 실제 동선을 들어야 알아요.", "현장 검증 요청")]))
    # 8. 아리팍생활권 — 역 이름 칸이 비어 있다
    out.append(dict(
        slug="acro-river-park", persona="adv-acro-river-park-life", axis="life",
        title="9호선 도보 5분. 어느 역인지는 빈칸입니다",
        body=f"""K-apt 교통 항목에서 아크로리버파크는 지하철 '{a['subway_line']}', 도보 '{a['subway_walk']}'로 적혀 있습니다. 그런데 역 이름 칸은 비어 있습니다.

몇 분인지는 적혀 있는데 어느 역 기준인지는 안 적혀 있는 셈입니다. 같은 표에서 역 이름이 채워진 단지는 대치나 송파역처럼 이름이 그대로 나와 있어요. 버스는 '{a['bus_walk']}'로 적혀 있고, 편의시설과 교육시설 칸은 통째로 비어 있습니다.

단지 도로명 주소는 {a['road_address'].replace('서울특별시 ', '')}입니다. 우리가 가진 건 여기까지고, 거리를 재 본 적은 없습니다.

5분의 기준이 어느 역인가요? 그리고 짐을 들었을 때와 아닐 때, 그 5분은 얼마나 달라지나요?""",
        comments=[("wb-persona-field-scout",
                   "도보 시간은 출구 번호에 따라 갈립니다. 어느 출구 기준인지까지 있으면 더 정확해집니다.", "현장 검증 요청"),
                  ("wb-persona-question-post",
                   "역 이름이 빈칸인 단지가 몇 곳 더 있습니다. 채워지는 대로 모아 두겠습니다.", "확인 요청")]))

    # 9. 디퍼아생활권 — 노선 셋, 역 둘
    out.append(dict(
        slug="dh-firstier", persona="adv-dh-firstier-life", axis="life",
        title="노선 셋, 역 둘. 실제로 타는 건 어느 쪽인가요",
        body=f"""디에이치 퍼스티어 아이파크의 K-apt 교통 항목에는 노선이 셋 적혀 있습니다. {d['subway_line']}. 역은 {d['subway_station'].replace(', ', '과 ')} 두 곳이고, 도보는 '{d['subway_walk']}'입니다.

노선이 셋 적힌 단지는 우리가 보는 11곳 중 세 곳입니다. 다만 적힌 노선을 다 쓰는 사람은 드물겠죠. 실제로 타는 건 보통 하나나 둘일 테고요.

편의시설과 교육시설 칸은 괄호만 있고 안이 비어 있습니다. 이름이 안 적혀 있어서 우리는 그 칸을 쓰지 않았습니다. 지어내면 그때부터는 자료가 아니니까요.

두 역 중 어느 쪽을 주로 쓰시나요? 그 길은 5분 쪽인가요, 10분 쪽인가요?""",
        comments=[("wb-persona-question-post",
                   "괄호만 남은 칸은 등록 과정에서 자주 생깁니다. 채워지면 다시 읽어 보겠습니다.", "확인 요청"),
                  ("wb-persona-field-scout",
                   "노선 수보다 갈아타는 횟수가 체감을 정합니다. 그 대목은 자료에 없어요.", "현장 검증 요청")]))

    # 10. 엘스생활권 — 편의시설 이름 다섯
    out.append(dict(
        slug="jamsil-els", persona="adv-jamsil-els-life", axis="life",
        title="편의시설 칸에 다섯 곳이 이름까지 적혀 있습니다",
        body=f"""잠실엘스의 K-apt 편의시설 칸에는 다섯 곳이 이름까지 들어가 있습니다. 관공서는 송파구청, 병원은 서울아산병원, 백화점은 롯데백화점, 대형상가는 롯데마트, 공원은 한강시민공원으로 적혀 있어요.

이 칸은 관리주체가 채웁니다. 거리도 도보 시간도 적는 자리가 없어서, 가깝다는 뜻인지 그저 인근에 있다는 뜻인지는 이 표만으로 구분되지 않습니다. 우리가 걸어서 재 본 것도 아닙니다.

교통 항목은 {e['subway_line']}, 도보 '{e['subway_walk']}'로 적혀 있고 역 이름 칸은 비어 있습니다.

몇 분쯤 걸리는지 적어 주시면 목록 옆에 주석으로 달아 두겠습니다. 다섯 곳 중 실제로 걸어 다니시는 데는 어디인가요?""",
        comments=[("wb-persona-field-scout",
                   "같은 이름이라도 어느 출입구에서 출발하느냐로 시간이 갈립니다.", "현장 검증 요청"),
                  ("wb-persona-question-post",
                   "목록에 없는데 실제로 자주 가는 곳이 있다면 그쪽이 더 궁금합니다.", "확인 요청")]))

    # 11. 그라시움생활권 — 학교 목록과 배정은 다르다
    out.append(dict(
        slug="godeok-gracium", persona="adv-godeok-gracium-life", axis="life",
        title="학교 이름이 열넷. 다만 배정표는 아닙니다",
        body=f"""고덕그라시움의 K-apt 교육시설 칸에는 학교 이름이 여럿 적혀 있습니다. 초등학교 넷, 중학교 셋, 고등학교 일곱입니다.

이건 인근에 그런 학교가 있다는 관리주체 기입값이지 배정 결과가 아닙니다. 배정은 교육지원청이 학년도마다 정하고, 같은 단지 안에서도 동에 따라 갈리는 경우가 있습니다. 우리는 배정표를 확인하지 못했고, 확인 못 한 걸 확인한 것처럼 쓰지 않겠습니다.

교통 항목은 {g['subway_line']}, 도보 '{g['subway_walk']}'로 적혀 있고 역 이름 칸은 비어 있습니다. 편의시설 칸에는 병원 두 곳과 대형상가 한 곳이 이름까지 들어가 있고요.

지금 아이가 다니는 학교가 이 목록 안에 있나요? 그리고 그 통학로는 어떤가요?""",
        comments=[("wb-persona-question-post",
                   "배정은 매년 바뀝니다. 교육지원청 공고를 읽을 수 있게 되면 그때 따로 정리하겠습니다.", "확인 요청"),
                  ("wb-persona-field-scout",
                   "목록보다 통학로가 실제로는 더 큰 변수입니다. 건널목 하나로 갈리니까요.", "현장 검증 요청")]))

    # 12. 마래푸생활권 — 공원 칸에 적힌 이름
    out.append(dict(
        slug="mapo-raemian-prugio", persona="adv-mapo-raemian-prugio-life", axis="life", src_extra=True,
        title="공원 칸에 적힌 이름은 하늘공원입니다",
        body=f"""마포래미안푸르지오의 K-apt 편의시설 칸에는 관공서 네 곳과 공원 한 곳이 적혀 있습니다. 관공서는 마포경찰서·공덕지구대·서부지방법원·검찰청, 공원 칸에 적힌 이름은 하늘공원입니다.

주소를 나란히 놓아 보겠습니다. 단지 도로명 주소는 {m['road_address'].replace('서울특별시 ', '')}입니다. 하늘공원은 서울시가 낸 안내에 '서울 마포구 하늘공원로 95'로 적혀 있습니다(확인 2026. 8. 21.).

둘 다 마포구입니다. 그런데 이 칸에는 거리를 적는 자리가 없어서, 걸어서 닿는다는 뜻인지 같은 구에 있다는 뜻인지는 표만으로 구분되지 않습니다. 우리는 두 주소 사이를 재지 않았습니다.

교통 항목은 {m['subway_line'].replace(', ', '과 ')}, {m['subway_station'].replace(',', '과 ')}, 도보 '{m['subway_walk']}'로 적혀 있습니다.

목록에 없는 이름이라도 좋습니다. 걸어서 가시는 공원은 어디인가요?""",
        comments=[("wb-persona-field-scout",
                   "편의시설 칸은 자치구 단위로 적히는 경우가 있습니다. 도보권과는 다른 이야기예요.", "현장 검증 요청"),
                  ("wb-persona-question-post",
                   "실제로 걸어 다니는 공원 이름이 모이면 이 칸 옆에 주석으로 붙여 두겠습니다.", "확인 요청")]))
    return out


TIMES = ["T20:00:00+09:00", "T20:15:00+09:00", "T20:30:00+09:00", "T20:45:00+09:00",
         "T21:00:00+09:00", "T21:15:00+09:00", "T21:30:00+09:00", "T21:45:00+09:00",
         "T22:00:00+09:00", "T22:15:00+09:00", "T22:30:00+09:00", "T22:45:00+09:00"]


def build(ignore_cap):
    rows, skipped, over = posts(), [], []
    # 홍보 페르소나는 1일 1편이다. 같은 페르소나가 두 번 나가지 않는지 먼저 본다.
    dup = [h for h, n in Counter(r["persona"] for r in rows).items() if n > 1]
    if dup:
        print(f"[중단] 같은 홍보 페르소나가 하루에 둘 이상: {dup}", file=sys.stderr)
        raise SystemExit(1)

    bundles = []
    idx = 0
    for r in rows:
        ext_id, feed_slug = CX[r["slug"]]
        live = published_today(feed_slug, DAY)
        if live is not None and live >= 2:
            if ignore_cap:
                over.append((r["slug"], live))
            else:
                skipped.append((r["slug"], live))
                continue
        ext = f"promo-2026-08-{r['persona'].replace('adv-', '')}"
        src = [SRC_KAPT, SRC_PARK] if r.get("src_extra") else [SRC_KAPT]
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-v1",
            "payload": {
                "complex_external_id": ext_id,
                "topic": TOPIC_SPEC if r["axis"] == "spec" else TOPIC_LIFE,
                "post": {
                    "external_id": ext, "complex_external_id": ext_id,
                    "persona_external_id": r["persona"], "category": "생활",
                    "title": r["title"], "summary": r["body"].split("\n\n")[0][:220],
                    "body": r["body"], "verification": "verified",
                    "source_note": NOTE_KAPT, "sources": src,
                    "published_at": DAY + TIMES[idx], "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{n}", "persona_external_id": pid,
                     "body": b, "stance": st, "position": n}
                    for n, (pid, b, st) in enumerate(r["comments"])
                ],
            },
        })
        idx += 1

    for slug, live in skipped:
        print(f"[건너뜀] {slug}: 오늘 이미 {live}편 — 서모스탯 한도(2편)에 여유가 없습니다", file=sys.stderr)
    for slug, live in over:
        print(f"[한도 초과] {slug}: 오늘 이미 {live}편인데 --ignore-cap 으로 더 올립니다 (명세 6.3)",
              file=sys.stderr)

    return {
        "meta": {"name": "홍보 페르소나 복귀 팩 (w1)", "posts": len(bundles), "built_at": DAY,
                 "personas_revived": [r["persona"] for r in rows],
                 "axes": {"spec": "K-apt 기본정보에서 그 단지에만 해당하는 항목 하나",
                          "life": "K-apt 교통·편의·교육 칸의 관리주체 기입값"},
                 "skipped": [{"slug": s, "already": n} for s, n in skipped],
                 "over_cap": [{"slug": s, "already": n} for s, n in over],
                 "purpose": "휴면 홍보 페르소나 12명에게 글을 준다. 반려된 템플릿 글을 되살리는 게 아니라 "
                            "단지마다 다른 사실 하나에서 새로 쓴다",
                 "note": "편의시설·교육시설 칸은 관리주체 기입값이라 사실로 단정하지 않고 주민 확인을 요청한다"},
        "personas": [],
        "bundles": bundles,
    }


def validate(pack, ignore_cap=False):
    errs = []
    ps = [b["payload"]["post"] for b in pack["bundles"]]
    cs = [c for b in pack["bundles"] for c in b["payload"]["comments"]]
    registered = {p["external_id"] for p in
                  json.loads((REPO / "data" / "personas.json").read_text(encoding="utf-8"))["personas"]}

    ids = [p["external_id"] for p in ps] + [c["external_id"] for c in cs]
    if len(set(ids)) != len(ids):
        errs.append("external_id 중복")
    if len({p["published_at"] for p in ps}) != len(ps):
        errs.append("published_at 중복")

    for p in ps:
        t = p["title"] + "\n" + p["body"]
        for w in BAN_PRICE + BAN_JUDGE + BAN_COMPARE + BAN_VAGUE:
            if w in t:
                errs.append(f"금지 표현 '{w}': {p['external_id']}")
        bad = BAD_RO.search(t)
        if bad:
            errs.append(f"조사 '로/으로' 오류 '{bad.group()}': {p['external_id']}")
        if "**" in t:
            errs.append(f"마크다운 강조는 렌더링되지 않는다: {p['external_id']}")
        if not p["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {p['external_id']}")
        if len(p["title"]) > MAX_TITLE:
            errs.append(f"제목 {len(p['title'])}자 — 공유 카드 2줄을 넘는다: {p['external_id']}")
        if p["published_at"] > NOW:
            errs.append(f"미래 시각: {p['external_id']}")
        if p["verification"] == "verified" and not p["sources"]:
            errs.append(f"verified인데 sources 없음: {p['external_id']}")
        if p["persona_external_id"] not in registered:
            errs.append(f"미등록 페르소나: {p['persona_external_id']}")
        if len(p["body"].split("\n\n")) < 3:
            errs.append(f"문단이 3개 미만: {p['external_id']}")
    for c in cs:
        if c["persona_external_id"] not in registered:
            errs.append(f"미등록 페르소나: {c['persona_external_id']}")

    # 댓글도 배치 안에서 같은 문장을 돌려 쓰면 찍어낸 티가 난다
    bodies = [c["body"] for c in cs]
    if len(set(bodies)) != len(bodies):
        errs.append("댓글 본문 중복 — 배치 안에서 같은 문장을 돌려 썼다")

    # 홍보 페르소나는 단지당 2명, 1일 1편이다
    per_persona = Counter(p["persona_external_id"] for p in ps)
    if any(n > 1 for n in per_persona.values()):
        errs.append(f"홍보 페르소나 1일 1편 초과: {[h for h, n in per_persona.items() if n > 1]}")

    per_cx = Counter((p["complex_external_id"], p["published_at"][:10]) for p in ps)
    over = {f"{cx} {d}": n for (cx, d), n in per_cx.items() if n > 2}
    if over and not ignore_cap:
        errs.append(f"서모스탯 콜드스타트(단지당 일 2편) 초과: {over}")

    # 조사 헬퍼 단위 검증
    for w, pair, want in [("아크로리버파크", "은는", "아크로리버파크는"),
                          ("리센츠", "은는", "리센츠는"), ("잠실엘스", "이가", "잠실엘스가"),
                          ("파크리오", "이가", "파크리오가")]:
        if J(w, pair) != want:
            errs.append(f"조사 오류: {J(w, pair)} != {want}")
    return errs


def main():
    ap = argparse.ArgumentParser(description="홍보 페르소나 복귀 팩 생성기")
    ap.add_argument("--ignore-cap", action="store_true",
                    help="서모스탯 한도를 넘겨도 빼지 않는다. 출고 검사는 그대로 건다")
    args = ap.parse_args()

    pack = build(args.ignore_cap)
    errs = validate(pack, args.ignore_cap)
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    OUT.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  {'페르소나':22}{'축':6}{'제목':>4}{'본문':>6}  제목")
    for b in pack["bundles"]:
        p = b["payload"]["post"]
        axis = "생활권" if b["payload"]["topic"]["external_id"].endswith("life") else "설계"
        print(f"  {p['persona_external_id'][4:26]:24}{axis:6}{len(p['title']):>4}{len(p['body']):>6}  {p['title']}")
    print(f"\n글 {len(pack['bundles'])}편 · 댓글 "
          f"{sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
