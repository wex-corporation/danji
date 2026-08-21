#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""주변 공공시설 조사글 + 단지 단일 사실 글 생성기.

왜 만들었나
  1~3라운드가 K-apt 시설·인력·비용과 전월세 실거래를 다 썼다. 4라운드 후보였던
  매매 실거래는 쓸 만한 지표가 해제신고 비율 하나뿐이라 6곳을 못 채운다.
  그래서 축을 바꿨다. 단지 간 z-score 비교가 아니라 **단지 주변을 조사해
  확인된 사실을 제시하고, 공개 자료로 안 되는 지점을 주민에게 묻는다.**

두 계열
  A. 주변 조사(nearby) — data/nearby/<slug>.json 의 조사 캐시를 읽는다.
     페르소나는 adv-{slug}-life(생활권).
  B. 단지 단일 사실(kapt) — data/complex-info 에서 그 단지에만 있는 값 하나를 잡는다.
     페르소나는 adv-{slug}-spec(설계노트).

출처 규칙
  캐시의 모든 fact 에 source.url 과 checked_at 이 있어야 한다. 없으면 중단한다.
  "인터넷에서", "알려져 있다" 같은 **출처 불명 표현은 검증에서 막는다.**
  CLAUDE.md 가 금지한 "바깥 커뮤니티에서 가져왔다"류와 같은 종류다.

넘지 않는 선
  홍보 페르소나는 가격·전망을 말할 수 없다. 단지 간 우열 비교도 하지 않는다.
  학교 이야기는 이번 팩에 넣지 않았다 — 출처 페이지를 읽지 못했다(503).

실행: python3 scripts/build_nearby_pack.py
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "content" / "nearby-w1.json"
NEARBY_DIR = REPO / "data" / "nearby"
INFO_DIR = REPO / "data" / "complex-info"
NOW = "2026-08-18T15:10:00+09:00"

PILOT = ["olympic-park-foreon", "eunma", "helio-city", "parkrio", "ricents", "one-bailey"]

# 단지 external_id 는 slug 와 다를 수 있다. 지어내지 않는다.
CX = {
    "olympic-park-foreon": "cx-olympic-park-foreon", "helio-city": "cx-helio-city",
    "ricents": "cx-ricents", "parkrio": "cx-parkrio",
    "eunma": "cx-eunma", "one-bailey": "cx-one-bailey",
}

# 서모스탯을 게시된 피드까지 합쳐 세기 위한 것. external_id 와 피드 slug 는 다를 수 있다.
FEED_BASE = os.environ.get("BASE_URL", "https://danji.life")
FEED_SLUG = {v: k for k, v in CX.items()}

TOPIC_NEARBY = {"external_id": "wb-topic-2026-08-nearby", "title": "단지 밖에서 확인한 것",
                "summary": "공공기관 공개 자료로 주변을 확인하고, 안 나오는 건 주민에게 묻는다",
                "category": "생활", "heat": 4}
TOPIC_KAPT = {"external_id": "wb-topic-2026-08-onlyhere", "title": "이 단지에만 있는 항목",
              "summary": "공개 자료에서 이 단지만 값이 다른 항목 하나를 본다",
              "category": "생활", "heat": 3}


def _batchim(w):
    for ch in reversed(w.rstrip(")]}」』\"' ")):
        if "가" <= ch <= "힣":
            return (ord(ch) - 0xAC00) % 28 != 0
        if ch.isdigit():
            return ch in "13678" or ch == "0"
    return False


# J() 는 받침에 따라 갈리는 조사쌍만 받는다. '에서'를 넘기면 '파크리오서'가 된다.
JOSA_PAIRS = {"은는", "이가", "을를", "과와", "아야"}


def J(word, pair):
    if pair not in JOSA_PAIRS:
        raise ValueError(f"J()는 조사쌍만 받는다. '{pair}'는 쌍이 아니다 — 그냥 붙여 쓸 것")
    return word + (pair[0] if _batchim(word) else pair[1])


def JR(word):
    """로/으로. ㄹ 받침은 '로'다. '47명로'가 실제로 나왔던 자리다."""
    for ch in reversed(word.rstrip(")]}」』\"' ")):
        if "가" <= ch <= "힣":
            return word + ("로" if (ord(ch) - 0xAC00) % 28 in (0, 8) else "으로")
        if ch.isdigit():
            return word + ("로" if ch in "013678" else "으로")
    return word + "로"


BAN_PRICE = ["억", "호가", "시세", "매수", "매도", "저점", "고점", "전망", "집값", "상승", "하락"]
BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "뒤처", "부럽", "명문", "상위권", "학군지"]
# 출처를 대지 않고 사실인 척하는 표현. 명세 3.2.1 과 같은 취지다.
BAN_VAGUE = ["인터넷에서", "알려져 있", "라고 한다", "찾아보니", "검색해 보니", "카페에서", "커뮤니티에서"]
# 단지 간 우열. 홍보 페르소나가 넘으면 안 되는 선이다.
BAN_COMPARE = ["보다 낫", "보다 좋", "보다 우수", "보다 편리"]
BAD_RO = ["명로", "층로", "원로", "동로", "분로"]


def cite(fact):
    """본문에 그대로 들어가는 인용구. 기관과 자료명, 확인 날짜를 함께 밝힌다.

    출처 없이 사실인 척하는 문장을 쓰지 않기 위한 장치다. 검증기가
    '알려져 있다' 류를 막고, 이 함수가 대신 쓸 문구를 만든다.
    """
    s = fact["source"]
    doc = s["label"].split("—")[-1].strip()
    return f"{J(s['publisher'], '이가')} 공개한 {doc} 안내(확인 {s['checked_at']})"


def load_nearby():
    rows = {}
    for slug in PILOT:
        p = NEARBY_DIR / f"{slug}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for f in d["facts"]:
            src = f.get("source") or {}
            if not src.get("url") or not src.get("checked_at"):
                sys.exit(f"[중단] {slug}: 출처 없는 사실이 있다 — {f['statement'][:40]}")
        rows[slug] = d
    return rows


def info(slug):
    return json.loads((INFO_DIR / f"{slug}.json").read_text(encoding="utf-8"))


# ── 주변 조사 프레임 6종 ────────────────────────────────────────────
# 소재가 단지마다 달라서 내용은 자연히 갈린다. 그래도 뼈대까지 같으면
# 마스킹 후 유사도가 오른다. 도입·문단 수·질문 방식을 서로 다르게 쓴다.

def f_eco(name, d, i):
    a, b, c, e = d["facts"]
    return f"""{J(name, '이가')} 들어선 자리 뒤편에 서울시가 보호구역으로 묶어 둔 땅이 있습니다. 산책 삼아 지나치기 쉬운 자리죠. 그런데 지정 이력을 보면 그냥 야산이 아닙니다.

{cite(a)}를 봤습니다. {a['statement']}. {b['statement']}. 26년 사이 여섯 배 넘게 넓어진 셈이죠.

{c['statement']}. 조사 기록도 함께 올라와 있는데, {e['statement']}.

여기서부터는 해석입니다. 보호구역은 사람이 덜 드나들도록 관리되는 땅이라, 가까이 산다고 해서 마음대로 쓸 수 있는 공간이 아닙니다. 도시에서 이런 땅이 옆에 있다는 건 조용함과 접근 제한을 동시에 받는다는 뜻이죠. 어느 쪽이 더 크게 느껴지는지, 그건 공개 자료로 알 수 없습니다.

거기까지 걸어가 보신 적 있으신가요? 어느 길로 들어가셨고, 실제로 들어갈 수 있는 데는 어디까지였나요?"""


def f_library(name, d, i):
    a, b, c, e, g = d["facts"]
    return f"""도서관이 단지 밖 어딘가가 아니라 상가 건물 안에 있는 경우, 흔치 않죠. {J(name, '이가')} 그렇습니다.

{cite(a)}에 적힌 내용입니다. {a['statement']}. 운영 시간은 이렇습니다 — {b['statement']}. 그런데 {c['statement']}. {e['statement']}. {g['statement']}.

눈에 띄는 건 열람실 시간입니다. 자료실보다 세 시간 먼저 열고, 닫는 시각은 같고요.

여기서부터는 해석입니다. 운영 시간표는 그 시설을 누가 쓰는지를 드러냅니다. 새벽에 여는 열람실은 출근 전이나 시험 준비를 하는 사람을 상정한 시간표죠. 다만 78석이 언제 차는지, 그 자리를 누가 채우는지, 공개된 표에는 없습니다.

이 도서관을 써 보신 적 있으신가요? 아침에 가면 자리가 남아 있던가요?"""


def f_sports(name, d, i):
    a, b, c, e = d["facts"]
    return f"""운동 시설 이야기는 단지 안이냐 밖이냐로 끝나기 쉽죠. 밖에 있는 쪽도 무엇이 있는지는 공개돼 있습니다.

{cite(a)}부터 옮깁니다. {a['statement']}. 시설은 층으로 나뉩니다 — {b['statement']}. {c['statement']}. 그리고 {e['statement']}.

한 건물에 수영장·구기·헬스·골프연습장이 층별로 나뉘어 들어간 구조.

여기서부터는 해석입니다. 목록은 있는 것만 알려 주지, 쓸 수 있는지는 알려 주지 않습니다. 강습 정원이 몇 명인지, 접수가 언제 열리고 얼마 만에 마감되는지, 저녁 일곱 시에 러닝머신이 비어 있는지. 어디에도 공개되지 않는 것들이죠. 목록이 길수록 그 격차도 커집니다.

여기 다니시는 분 계신가요? 등록이 실제로 되던가요, 아니면 매번 밀리시나요?"""


def f_trail(name, d, i):
    a, b, c = d["facts"]
    return f"""산책로 이야기는 대개 "가깝다"에서 끝나죠. 거리와 시간이 적힌 자료가 있어 옮겨 둡니다.

{cite(a)} 기준입니다. {a['statement']}. {b['statement']}. 나머지는 {c['statement']}.

네 코스를 더하면 21km. 안내에 적힌 소요시간을 다 더하면 5시간 30분입니다.

여기서부터는 해석입니다. 이 숫자는 코스 전체를 걷는 기준이지 {name}에서 나가 걷는 기준이 아닙니다. 단지에서 어느 지점으로 붙느냐에 따라 실제로 걷는 거리는 완전히 달라집니다. 진입 지점은 지도에 나오죠. 어디가 편한지는 나오지 않고요.

어느 코스로 나가시나요? 그 길을 밤에 걸어도 괜찮다고 느끼시나요?"""


def f_transit(name, d, i):
    a, b, c, e, _cost = d["facts"]
    return f"""K-apt 공개정보에는 단지마다 지하철 항목이 있습니다. {J(name, '은는')} 그 칸이 비어 있습니다. 노선도 역 이름도 도보 시간도, 아무것도 없습니다.

그래서 단지 자료 대신 역 쪽 자료를 봤습니다. {cite(a)}입니다. {a['statement']}. 규모는 이렇고요 — {b['statement']}. {c['statement']}. 개통 효과로 적힌 수치도 있는데, {e['statement']}.

여기서부터는 해석입니다. 환승 시간이 4분 30초 줄었다는 건 시설 전체의 평균이지 특정 동선의 값이 아닙니다. 어느 출구로 나가는지, 어느 층에서 갈아타는지에 따라 사람마다 다르죠. 그리고 공식 자료가 비어 있다는 건 그 단지에 정보가 없다는 뜻이지, 역이 멀다는 뜻은 아닙니다.

저희가 채우지 못한 칸은 여기입니다. 출근하실 때 어느 출구를 쓰시고, 문 앞에서 개찰구까지 몇 분 걸리시나요?"""


def f_fountain(name, d, i):
    a, b, c, e = d["facts"]
    return f"""같은 동에 있는 다리에서 정해진 시각에 물이 나옵니다. 시간표는 공개돼 있고요.

{cite(a)}에 있는 값입니다. {a['statement']}. {b['statement']}. 가동은 계절을 탑니다 — {c['statement']}. {e['statement']}.

여기서부터는 해석입니다. 시간표가 공개된 시설은 생활 리듬에 영향을 줍니다. 저녁 일곱 시 반부터 아홉 시까지 30분 간격. 그 시간대에 사람과 차가 움직인다는 뜻이기도 하죠. 다만 그게 소음으로 닿는지 아예 안 들리는지는 거리와 층과 방향에 달렸고, 어느 자료에도 없습니다.

가동 시간에 단지 쪽에서 달라지는 게 느껴지시나요? 소리든 사람이든 차든 무엇이라도 좋으니 알려 주시겠어요?"""


# ── 단지 단일 사실 프레임 4종 ───────────────────────────────────────
# 파일럿 6곳 가운데 그 단지에서만 값이 다른 항목을 하나씩 잡는다.

def f_selfmanage(name, d, i):
    return f"""관리주체가 위탁이냐 자치냐는 고지서에 안 나오는데, K-apt 공개정보에는 적혀 있습니다.

{J(name, '은는')} 자치관리입니다. 같은 잣대로 보는 파일럿 6개 단지 가운데 자치관리는 이 단지 하나이고 나머지 다섯 곳은 위탁관리입니다. 세대수는 {i['household_count']:,}세대, 관리 인력은 일반관리 {i['staff_manage']}명·경비 {i['staff_security']}명·청소 {i['staff_clean']}명으로 등록돼 있습니다.

여기서부터는 해석입니다. 자치관리는 입주자대표회의가 관리사무소 직원을 직접 두는 방식이고, 위탁관리는 관리업체와 계약하는 방식입니다. 자치는 위탁수수료가 빠지는 대신 채용과 노무를 단지가 직접 집니다. 어느 쪽이 낫다기보다 누가 결정하고 누가 책임지느냐가 다른 것이죠. 그 차이는 관리비 총액보다 회의록에서 먼저 드러납니다.

관리 방식이 자치라는 걸 알고 계셨나요? 알고 계셨다면 그게 생활에서 체감되는 지점이 있으신가요?"""


def f_garbage(name, d, i):
    return f"""쓰레기 버리는 방식은 매일 쓰는 설비인데 단지 소개에는 거의 안 나옵니다. K-apt에는 한 줄로 적혀 있습니다.

{J(name, '은는')} 거점장비수거방식입니다. 파일럿 6개 단지 중 이 방식으로 등록된 곳은 여기뿐이고, 나머지는 음식물쓰레기 종량제로 적혀 있습니다. 준공은 {i['use_approval_date'][:4]}년, {i['household_count']:,}세대입니다.

여기서부터는 해석입니다. 거점 수거는 세대가 특정 지점까지 들고 나가는 대신 수거 동선이 짧아지는 구조입니다. 신축 단지가 설계 단계에서 넣는 방식이라 준공 연도와 같이 봐야 하죠. 다만 K-apt에 적힌 건 등록된 방식일 뿐입니다. 거점이 몇 곳인지, 동에서 얼마나 걸어야 하는지, 여름에 냄새가 어떤지는 공개돼 있지 않고요.

배출 거점까지 몇 걸음이나 걸으시나요? 그 방식이 편하신가요, 번거로우신가요?"""


def f_corridor(name, d, i):
    return f"""복도식이냐 계단식이냐는 도면 이야기 같지만 실제로는 매일의 동선과 소음에 붙는 항목입니다.

{J(name, '은는')} K-apt에 복도식으로 등록돼 있습니다. 파일럿 6개 단지 중 복도식은 이 단지뿐이고 계단식이 둘, 혼합식이 셋입니다. {i['dong_count']}개동 {i['household_count']:,}세대, 최고 {i['top_floor']}층, 준공 {i['use_approval_date'][:4]}년입니다.

여기서부터는 해석입니다. 복도식은 한 층의 여러 세대가 복도를 함께 쓰는 구조. 오가는 사람이 많아지는 대신 양쪽으로 창을 낼 수 있어 통풍이 달라집니다. 어느 쪽이 크게 느껴지는지는 층과 위치에 따라 갈리고, 같은 단지 안에서도 다르겠죠. 공개 자료는 복도식이라는 사실까지만 말해 줍니다.

복도식에 살아 보신 분이 계시다면, 겨울과 여름 중 어느 쪽에서 차이가 더 크게 느껴지시나요?"""


def f_welfare(name, d, i):
    items = [x.strip() for x in (i.get("welfare_facility") or "").split(",") if x.strip()]
    listed = " · ".join(x for x in items if x != "기타")
    return f"""주민공동시설은 단지마다 목록이 다르게 등록됩니다. {J(name, '은는')} 어떤 항목이 올라가 있는지 그대로 옮깁니다.

K-apt 공개정보 기준 {len(items)}개 항목입니다 — {listed}. {i['household_count']:,}세대가 이 목록을 함께 씁니다.

여기서부터는 해석입니다. 목록은 등록된 항목이지 운영되는 상태가 아닙니다. 문고에 책이 몇 권인지, 커뮤니티공간을 예약 없이 쓸 수 있는지, 휴게시설이 어느 동 가까이 있는지. 이 표에는 없죠. 항목 수가 많다는 건 지어 놓은 게 많다는 뜻이지, 쓰이고 있다는 뜻은 아닙니다.

이 중에서 실제로 자주 쓰시는 건 무엇인가요? 그리고 목록에는 있는데 있는 줄 몰랐던 항목이 있으신가요?"""


NEARBY_FRAMES = {"생태보전지역": f_eco, "도서관": f_library, "체육시설": f_sports,
                 "하천 산책로": f_trail, "환승센터": f_transit, "한강 분수": f_fountain}
NEARBY_TITLES = {
    "생태보전지역": lambda d, i: "단지 뒤 29,952㎡가 보호구역입니다. 어디까지 들어가 보셨나요?",
    "도서관": lambda d, i: "구립도서관이 상가 2층에 있습니다. 새벽 6시 열람실, 자리 있던가요?",
    "체육시설": lambda d, i: "수영장 6레인에 골프 9타석. 목록은 아는데 등록은 되시나요?",
    "하천 산책로": lambda d, i: "네 하천 21km가 이어집니다. 어느 코스로 나가시나요?",
    "환승센터": lambda d, i: "공식 자료에 이 단지 지하철 칸이 비어 있습니다. 어느 출구 쓰시나요?",
    "한강 분수": lambda d, i: "하루 다섯 번, 20분씩. 단지에서 뭔가 느껴지시나요?",
}

KAPT_ASSIGN = {
    "parkrio": ("자치관리", f_selfmanage,
                lambda i: "6곳 중 이 단지만 자치관리입니다. 알고 계셨나요?"),
    "one-bailey": ("쓰레기수거", f_garbage,
                   lambda i: "6곳 중 이 단지만 거점장비수거방식입니다. 몇 걸음이나 걸으시나요?"),
    "eunma": ("복도식", f_corridor,
              lambda i: "6곳 중 이 단지만 복도식입니다. 겨울과 여름 중 어느 쪽이 다른가요?"),
    "helio-city": ("주민공동시설", f_welfare,
                   lambda i: "주민공동시설 10개 항목. 이 중 실제로 쓰시는 건 무엇인가요?"),
}

DAYS_NEARBY = ["2026-08-18T08:05:00+09:00", "2026-08-18T09:15:00+09:00",
               "2026-08-18T10:20:00+09:00", "2026-08-18T11:30:00+09:00",
               "2026-08-18T12:40:00+09:00", "2026-08-18T13:50:00+09:00"]
DAYS_KAPT = ["2026-08-18T14:25:00+09:00", "2026-08-18T14:45:00+09:00",
             "2026-08-18T15:00:00+09:00", "2026-08-18T15:05:00+09:00"]

COMMENTS_NEARBY = [
    ("wb-persona-field-scout", "공개 자료는 있다는 것까지만 말해 줍니다. 실제로 쓰이는지는 사시는 분 얘기가 유일한 자료예요.", "현장 검증 요청"),
    ("wb-persona-real-talk", "시설 목록과 생활 체감이 어긋나는 자리가 늘 있습니다. 그 간격이 어디인지가 궁금하네요.", "생활 현실"),
]
COMMENTS_KAPT = [
    ("wb-persona-appraisal-check", "K-apt 등록값이라 검증은 되는데, 등록 시점 이후 바뀐 건 반영이 늦습니다. 기준일을 같이 봐야 합니다.", "기준 명시"),
    ("wb-persona-psy-thermo", "항목 하나로 단지를 규정할 수는 없습니다. 다르다는 사실까지만 보는 게 맞아요.", "해석 주의"),
]


def build():
    near = load_nearby()
    bundles = []

    for idx, slug in enumerate(PILOT):
        d, i = near[slug], info(slug)
        name = i["complex_name"]
        topic = d["topic"]
        body = NEARBY_FRAMES[topic](name, d, i)
        ext = f"nearby-2026-08-{slug}"
        srcs = []
        for f in d["facts"]:
            s = f["source"]
            item = {"label": s["label"], "url": s["url"], "publisher": s["publisher"]}
            if item not in srcs:
                srcs.append(item)
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-v3",
            "payload": {
                "complex_external_id": CX[slug], "topic": TOPIC_NEARBY,
                "post": {
                    "external_id": ext, "complex_external_id": CX[slug],
                    "persona_external_id": f"adv-{slug}-life", "category": "생활",
                    "title": NEARBY_TITLES[topic](d, i),
                    "summary": body.split("\n\n")[1][:220], "body": body,
                    "verification": "verified",
                    "source_note": f"{d['checked_at']} 공공기관 공개 페이지에서 확인 · 확인되지 않은 항목은 본문에 넣지 않았다",
                    "sources": srcs,
                    "published_at": DAYS_NEARBY[idx], "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{n}", "persona_external_id": pid,
                     "body": b, "stance": s, "position": n}
                    for n, (pid, b, s) in enumerate(COMMENTS_NEARBY)
                ],
            },
        })

    for idx, (slug, (key, frame, title)) in enumerate(KAPT_ASSIGN.items()):
        i = info(slug)
        name = i["complex_name"]
        body = frame(name, None, i)
        ext = f"onlyhere-2026-08-{slug}"
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-v3",
            "payload": {
                "complex_external_id": CX[slug], "topic": TOPIC_KAPT,
                "post": {
                    "external_id": ext, "complex_external_id": CX[slug],
                    "persona_external_id": f"adv-{slug}-spec", "category": "생활",
                    "title": title(i), "summary": body.split("\n\n")[1][:220], "body": body,
                    "verification": "verified",
                    "source_note": "2026. 8. 16. 조회 · K-apt 공개정보 기준 · 파일럿 6개 단지와 같은 항목을 비교한 값",
                    "sources": [{"label": "공동주택 기본 정보제공 서비스(K-apt) OpenAPI",
                                 "url": "https://www.data.go.kr/data/15058453/openapi.do",
                                 "publisher": "국토교통부"}],
                    "published_at": DAYS_KAPT[idx], "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{n}", "persona_external_id": pid,
                     "body": b, "stance": s, "position": n}
                    for n, (pid, b, s) in enumerate(COMMENTS_KAPT)
                ],
            },
        })

    return {
        "meta": {"name": "주변 조사 + 단지 단일 사실 팩 (w1)", "posts": len(bundles),
                 "built_at": NOW[:10], "pilot": PILOT,
                 "nearby_topics": {s: near[s]["topic"] for s in PILOT},
                 "kapt_topics": {s: v[0] for s, v in KAPT_ASSIGN.items()},
                 "purpose": "z-score 비교가 아니라 조사한 사실 + 주민에게 묻기 구조로 축을 넓힌다",
                 "thermostat": "인간 액션 0 기준 콜드스타트(단지당 1일 글 2). 이 팩은 단지당 1~2편"},
        "personas": [],
        "bundles": bundles,
    }



def published_today(feed_slug, day):
    """그날 이미 게시된 편수를 서버에서 센다.

    팩 안에서만 세면 팩 사이를 넘는 초과를 못 잡는다. 2026-08-18 에 원베일리가
    특이값 1편 + 주변 2편으로 3편 나간 적이 있다 — 각 생성기가 자기 팩만 봤기 때문이다.
    """
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


def cap_errors(posts, feed_of, ignore_cap=False):
    """서모스탯(명세 6.3)을 게시된 피드까지 합쳐 센다.

    ignore_cap 이면 반려하지 않고 경고만 남긴다. 출고 검사는 이 플래그와 무관하게
    그대로 걸린다 — 진짜 상한은 서모스탯이 아니라 출고 검사다.
    """
    errs = []
    per = Counter((p["complex_external_id"], p["published_at"][:10]) for p in posts)
    for (cx, day), n in sorted(per.items()):
        live = published_today(feed_of.get(cx, cx.removeprefix("cx-")), day)
        # 재전송이면 이미 있는 글을 다시 세게 되므로, 팩 안 편수만으로도 초과면 그걸로 판정한다
        total = n if live is None else max(n, live)
        if total > 2:
            msg = f"{cx} {day}: 팩 {n}편 + 게시분 포함 {total}편 — 콜드스타트 한도 2편 초과"
            if ignore_cap:
                print(f"  [한도 초과] {msg} (--ignore-cap 으로 진행)", file=sys.stderr)
            else:
                errs.append(msg)
    return errs

def validate(pack, ignore_cap=False):
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    comments = [c for b in pack["bundles"] for c in b["payload"]["comments"]]

    reg = {"wb-persona-field-scout", "wb-persona-real-talk",
           "wb-persona-appraisal-check", "wb-persona-psy-thermo"}
    reg |= {f"adv-{s}-life" for s in PILOT} | {f"adv-{s}-spec" for s in KAPT_ASSIGN}

    ids = [p["external_id"] for p in posts] + [c["external_id"] for c in comments]
    if len(set(ids)) != len(ids):
        errs.append("external_id 중복")
    if len({p["published_at"] for p in posts}) != len(posts):
        errs.append("published_at 중복")

    for p in posts:
        t = p["title"] + "\n" + p["body"]
        for w in BAN_PRICE + BAN_JUDGE + BAN_VAGUE + BAN_COMPARE + BAD_RO:
            if w in t:
                errs.append(f"금지 표현 '{w}': {p['external_id']}")
        # 서버가 본문 마크다운을 렌더링하지 않는다. ** 는 화면과 공유 카드에 그대로 보인다.
        if "**" in t:
            errs.append(f"마크다운 강조(**)는 렌더링되지 않는다: {p['external_id']}")
        if not p["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {p['external_id']}")
        if p["verification"] == "verified" and not p["sources"]:
            errs.append(f"verified인데 sources 없음: {p['external_id']}")
        if p["published_at"] > NOW:
            errs.append(f"미래 시각: {p['external_id']} {p['published_at']}")
        if int(p["published_at"][11:13]) < 7:
            errs.append(f"야간 게시: {p['published_at']}")
        if p["persona_external_id"] not in reg:
            errs.append(f"미등록 페르소나: {p['persona_external_id']}")
        for s in p["sources"]:
            if not s.get("url"):
                errs.append(f"출처 URL 없음: {p['external_id']}")
    for c in comments:
        if c["persona_external_id"] not in reg:
            errs.append(f"미등록 페르소나: {c['persona_external_id']}")

    # 인용일이 게시일보다 앞서야 한다
    near = load_nearby()
    for slug, d in near.items():
        pub = next(p["published_at"][:10] for p in posts if p["external_id"].endswith(slug)
                   and p["external_id"].startswith("nearby"))
        if d["checked_at"] > pub:
            errs.append(f"확인일이 게시일보다 뒤: {slug} {d['checked_at']} > {pub}")

    # 서모스탯은 단지당 한도다(명세 6.3). 팩 안에서만 세면 팩 사이 초과를 못 잡는다.
    errs += cap_errors(posts, FEED_SLUG, ignore_cap)

    # 조사 헬퍼 단위 검증
    for w, pair, want in [("올림픽파크 포레온", "은는", "올림픽파크 포레온은"),
                          ("리센츠", "은는", "리센츠는"), ("파크리오", "이가", "파크리오가"),
                          ("강동구청", "이가", "강동구청이"), ("서울특별시", "이가", "서울특별시가")]:
        if J(w, pair) != want:
            errs.append(f"조사 헬퍼 오류: J({w}) → {J(w, pair)}")
    try:
        J("파크리오", "에서")
        errs.append("J()가 조사쌍이 아닌 인자를 통과시켰다")
    except ValueError:
        pass
    return errs


def main():
    ap = argparse.ArgumentParser(description="주변 조사 + 단지 단일 사실 생성기")
    ap.add_argument("--ignore-cap", action="store_true",
                    help="서모스탯 한도를 넘겨도 반려하지 않는다. 출고 검사는 그대로 건다")
    args = ap.parse_args()
    pack = build()
    errs = validate(pack, args.ignore_cap)
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    OUT.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{'단지':22}{'소재':14}{'페르소나':24}제목")
    for b in pack["bundles"]:
        p = b["payload"]["post"]
        slug = p["external_id"].rsplit("-", 1)[-1] if False else p["external_id"]
        print(f"  {p['complex_external_id'][3:21]:20}{'주변' if p['external_id'].startswith('nearby') else '단지':6}"
              f"{p['persona_external_id']:26}{p['title'][:34]}")
    print(f"\n글 {len(pack['bundles'])}편 · 댓글 {sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
