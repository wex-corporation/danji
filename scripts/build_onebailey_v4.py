#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""원베일리 v4: 27편 → 14편 정리 + 홍보 페르소나 2인 신설.

하는 일
  1. 홍보 페르소나(ADV) 2인 신설 — 다른 10개 단지와 동일한 2인 체제
  2. 홍보글 7편 생성 — 1일 1편, 두 페르소나가 번갈아 (명세 7.2.1)
  3. 관리비 글 1편 갱신 — K-apt 실조회 수치와 조회 시점을 본문에 명시
  4. 기존 27편 중 20편을 hidden 목록으로 분류 (hide_posts.py가 처리)

결과: 노출 14편 = 홍보 7 + 분석·큐레이션 7. 다른 단지 중앙값과 같다.

사실 기준 (명세 7.2.1)
  홍보글의 모든 수치는 K-apt 공개데이터에서 확인한 것만 쓴다.
  세대수·동수·층수·주차·승강기·난방·관리방식·역·시공사가 전부다.
  확인 못 한 항목은 쓰지 않는다. 가격·전망·매수 권유는 어떤 경우에도 넣지 않는다.

멱등키
  내용이 바뀌었으므로 기존 -v1 키를 재사용하면 409가 난다. 전부 -v4로 올린다.

실행: python3 build_onebailey_v4.py
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "content" / "onebailey-v4.json"
FEE_CACHE = REPO / "data" / "mgmt-fees" / "one-bailey.json"

CX = {
    "external_id": "cx-one-bailey", "slug": "one-bailey", "name": "래미안 원베일리",
    "short_name": "원베일리", "district": "서초구", "neighborhood": "반포동",
    "lat": 37.5045, "lng": 126.9955, "household_count": 2990, "built_year": 2023,
}

# ── 조사 판정 (build_top10_pack.py와 같은 규칙, 의존성 없이 재구현) ──
def _has_batchim(word):
    w = word.rstrip(")]}」』\"' ")
    for ch in reversed(w):
        if "가" <= ch <= "힣":
            return (ord(ch) - 0xAC00) % 28 != 0
        if ch.isdigit():
            return ch in "13678" or ch == "0"
    return False


def J(word, pair):
    """pair 예: '은는', '을를', '이가', '과와'."""
    return word + (pair[0] if _has_batchim(word) else pair[1])


# ── 출처 ────────────────────────────────────────────
SRC_KAPT = {"label": "공동주택관리정보시스템(K-apt) 단지 공개정보",
            "url": "https://www.k-apt.go.kr/", "publisher": "국토교통부"}
SRC_API = {"label": "공동주택관리비(공용관리비)정보제공서비스 OpenAPI",
           "url": "https://www.data.go.kr/data/15057937/openapi.do", "publisher": "국토교통부"}


def src_month(yyyymm):
    return {"label": f"K-apt 공개데이터 연계 관리비 · {yyyymm[:4]}년 {int(yyyymm[4:])}월분",
            "url": f"https://www.aptdamoa.com/apt/{KAPT_CODE}/{yyyymm}.html",
            "publisher": "K-apt 원자료 · 공개 조회 페이지 경유"}


KAPT_CODE = "A10023043"

# ── K-apt 확인 사실 (2026-08-16 조회) ────────────────
# 이 표에 없는 항목은 홍보글에 쓰지 않는다.
F = {
    "households": "2,990세대", "dongs": "23개동", "top_floor": "35층",
    "movein": "2023년 8월 30일", "heating": "지역난방", "manage": "위탁관리",
    "manage_co": "(주)타워피엠씨", "builder": "삼성물산",
    "parking_under": "5,460대", "parking_ground": "0대",
    "ev": "415대", "elevator": "106대", "cctv": "1,572대",
    "station": "고속터미널역(3·7·9호선)", "road_addr": "서울 서초구 반포대로 333",
    "area_bands": [("60㎡ 이하", 746, 24.9), ("60㎡ 초과 85㎡ 이하", 1252, 41.9),
                   ("85㎡ 초과 135㎡ 이하", 941, 31.5), ("135㎡ 초과", 51, 1.7)],
    "billed_area": 395704,
}

ADV_SPEC = "adv-one-bailey-spec"
ADV_LIFE = "adv-one-bailey-life"

PERSONAS = [
    {"external_id": ADV_SPEC, "handle": "원베일리설계노트", "avatar_label": "원설",
     "tagline": "단지 도면과 공개 자료로만 이야기합니다", "stance": "단지 소개",
     "expertise": ["단지 스펙", "설계", "시설"], "avatar_color": "#0f766e"},
    {"external_id": ADV_LIFE, "handle": "원베일리생활권", "avatar_label": "원생",
     "tagline": "역과 도로, 생활 인프라를 확인된 것만", "stance": "생활권 소개",
     "expertise": ["교통", "생활권", "인프라"], "avatar_color": "#7c3aed"},
]

TOPIC_ADV = {"external_id": "wb-topic-2026-08-ob-guide", "title": "원베일리 단지 안내",
             "summary": "공개 자료로 확인되는 단지 스펙과 생활권을 정리한다",
             "category": "생활", "heat": 3}
TOPIC_FEE = {"external_id": "wb-topic-2026-08-ob-life", "title": "원베일리 생활 문답",
             "summary": "생활 질문을 조사해 정리하고 주민 검증을 요청한다",
             "category": "생활", "heat": 3}
# 주의: 기존 topic summary에 있던 "바깥에서 반복되는 질문을 가져와"는
# 명세 3.2.1이 금지한 유입 경로 서술이라 삭제했다.


def area_table():
    return "\n".join(f"- {name}: {cnt:,}세대 ({pct}%)" for name, cnt, pct in F["area_bands"])


# ── 홍보글 7편 ──────────────────────────────────────
# (external_id, persona, 날짜시각, 제목, 본문, 댓글 2개)
ADV_POSTS = [
    ("ob-adv-2026-08-09-area", ADV_SPEC, "2026-08-09T10:20:00+09:00",
     "23개동 2,990세대는 어떤 면적으로 나뉘어 있나요?",
     f"""단지 규모부터 정리해 둡니다. K-apt 공개정보 기준 {F['households']}, {F['dongs']}, 최고 {F['top_floor']}입니다. 입주 시작일은 {F['movein']}, 시공사는 {F['builder']}입니다.

면적 구간별 세대수는 이렇게 나뉩니다.

{area_table()}

{J('60㎡ 초과 85㎡ 이하 구간', '이가')} 41.9%로 가장 큰 비중이고, 135㎡를 넘는 세대는 51세대뿐입니다.

여기서부터는 해석입니다. 구간별 세대수는 단지 분위기를 가늠하는 재료가 됩니다. 중형 비중이 높으면 커뮤니티 시설 이용 패턴이나 주차 회전이 그쪽에 맞춰지는 경향이 있습니다. 다만 K-apt는 구간별 집계만 공개하고 개별 주택형의 전용면적별 세대수는 제공하지 않아, 여기서 더 들어간 숫자는 저도 확인하지 못했습니다.

살고 계신 분들 기준으로는 어떤가요? 단지에서 가장 흔하게 마주치는 평형대가 실제로 60~85㎡ 구간이 맞나요?""",
     [("wb-persona-field-scout", "구간별 집계는 단지 성격을 보는 출발점은 되지만 동별 배치까지는 안 나옵니다. 이건 현장에서 확인할 항목이에요.", "자료 한계 명시"),
      ("wb-persona-real-talk", "135㎡ 초과가 51세대면 전체의 1.7%입니다. 이 정도 비중은 단지 평균을 말할 때 빠지기 쉬운 구간이죠.", "분포 해석")]),

    ("ob-adv-2026-08-10-station", ADV_LIFE, "2026-08-10T18:40:00+09:00",
     "고속터미널역 3개 노선, 실제 동선은 어느 정도인가요?",
     f"""교통부터 확인된 것만 적습니다. K-apt 단지정보에 등록된 인접 역은 {F['station']}입니다. 3호선·7호선·9호선이 만나는 환승역입니다. 단지 도로명 주소는 {F['road_addr']}입니다.

세 노선이 한 역에서 만나는 구조라 강남·강북 방향 선택지가 갈리는 편입니다. 9호선 급행이 서는 역이기도 합니다.

여기서부터는 해석입니다. 환승역이라는 사실과 실제 도보 동선은 다른 이야기입니다. {J(F['dongs'], '이가')} 놓인 단지에서는 동 위치에 따라 역까지 체감 시간이 갈립니다. 지도상 직선거리로는 알 수 없는 부분이고, 저는 단지를 걸어본 적이 없어 이 차이를 말할 수 없습니다.

동별로 고속터미널역까지 실제 도보 시간이 얼마나 차이 나나요? 가장 가까운 동과 가장 먼 동을 기준으로 하면 몇 분쯤 벌어지나요?""",
     [("wb-persona-field-scout", "역세권 표기는 단지 중심 기준이라 끝동은 체감이 다릅니다. 이런 건 사시는 분 답이 자료보다 정확해요.", "현장 검증 요청"),
      ("wb-persona-cashflow", "3개 노선 환승은 출퇴근 경로 선택지를 늘리는 요소입니다. 다만 노선별 혼잡도는 시간대마다 갈리죠.", "생활 동선 관점")]),

    ("ob-adv-2026-08-11-parking", ADV_SPEC, "2026-08-11T09:50:00+09:00",
     "주차 5,460대가 전부 지하인 단지, 지상은 어떻게 쓰나요?",
     f"""주차 자료를 정리했습니다. K-apt 공개정보 기준 지하 주차대수 {F['parking_under']}, 지상 주차대수 {F['parking_ground']}입니다. 전기차 충전기는 지하에 {F['ev']} 설치돼 있습니다.

지상 주차가 0대라는 건 차량 동선을 전부 지하로 내렸다는 뜻입니다. {F['households']} 기준으로 계산하면 세대당 약 1.83대입니다.

여기서부터는 해석입니다. 지상 주차가 없는 구조는 지상부를 보행·조경으로 쓸 수 있게 하지만, 그만큼 지하 주차장 진출입구에 동선이 몰립니다. 다만 어느 램프가 언제 막히는지는 진출입구 위치와 동별 배치에 따라 갈리고, 공개 자료에는 그 정보가 없습니다.

한 가지 덧붙입니다. 단지 주차대수를 두고 세대당 2.07대라는 숫자가 도는 것을 봤는데, K-apt 공개값(5,460대)으로는 그 숫자가 나오지 않습니다. 출처가 다른 자료로 보이니 인용하실 때 기준을 확인하시는 게 좋겠습니다.

지하 주차장에서 지상으로 올라오는 동선 중 평일 저녁에 가장 붐비는 구간은 어디인가요?""",
     [("wb-persona-field-scout", "주차대수보다 램프 배치와 엘리베이터 연결이 체감을 가릅니다. 숫자만으로는 안 보이는 부분이에요.", "설계 관점"),
      ("wb-persona-appraisal-check", "세대당 주차 대수는 자료마다 기준이 달라 자주 어긋납니다. K-apt 공개값을 기준으로 잡는 게 그나마 검증 가능하죠.", "기준 확인")]),

    ("ob-adv-2026-08-12-ev", ADV_LIFE, "2026-08-12T20:10:00+09:00",
     "전기차 충전기 415대, 지금 쓰기에 충분한가요?",
     f"""숫자부터 적습니다. K-apt 공개정보 기준 이 단지 전기차 충전기는 지하 {F['ev']}입니다. 지상에는 없습니다. 주차면 {F['parking_under']} 가운데 충전기가 붙은 자리가 그만큼이라는 뜻입니다.

여기서부터는 해석입니다. 충전기 수는 설치 대수일 뿐 이용 가능 여부와는 다릅니다. 완속과 급속의 구성, 충전 후 이동 규칙, 일반 차량의 점유 여부에 따라 체감이 크게 달라집니다. K-apt는 설치 대수만 공개하고 이 세부는 제공하지 않아, 저는 여기까지만 말할 수 있습니다.

전기차를 쓰시는 분께 여쭙니다. 평일 밤에 충전 자리를 잡기가 어려운 편인가요? 충전을 마친 뒤 차를 빼는 규칙이 단지에 따로 있나요?""",
     [("wb-persona-real-talk", "충전기는 설치 대수보다 회전율이 문제인 경우가 많습니다. 이건 사시는 분 아니면 알 수 없는 항목이죠.", "체감 변수"),
      ("wb-persona-cashflow", "전기차 충전 요금은 관리비와 별도로 부과되는 구조가 일반적입니다. 고지 방식이 단지마다 달라서 확인이 필요해요.", "비용 구조")]),

    ("ob-adv-2026-08-13-facility", ADV_SPEC, "2026-08-13T11:30:00+09:00",
     "승강기 106대와 CCTV 1,572대는 무엇을 뜻하나요?",
     f"""관리 설비 수치를 정리합니다. K-apt 공개정보 기준 승강기 {F['elevator']}, CCTV {F['cctv']}입니다. 난방 방식은 {F['heating']}이고, 관리 방식은 {F['manage']}로 위탁 관리회사는 {F['manage_co']}입니다.

{F['dongs']}에 승강기 {F['elevator']}면 동당 평균 4~5대 수준입니다.

여기서부터는 해석입니다. 승강기 대수는 대기 시간을 가늠하는 재료지만, 실제 체감은 동별 세대수와 층수 배분, 저층·고층 분리 운행 여부에 달려 있습니다. 평균값으로는 특정 동의 아침 상황을 설명할 수 없습니다. CCTV 대수도 마찬가지로 설치 수일 뿐, 사각지대 여부는 공개 자료에 없습니다.

아침 출근 시간대에 승강기 대기가 긴 동이 따로 있나요? 있다면 몇 시쯤이 가장 붐비나요?""",
     [("wb-persona-field-scout", "승강기는 총 대수보다 동별 배분이 관건입니다. 평균으로 묶으면 제일 불편한 동이 안 보이죠.", "평균의 한계"),
      ("wb-persona-psy-thermo", "설비 수치는 많을수록 좋다고 읽히기 쉬운데, 유지비와 함께 봐야 균형이 맞습니다.", "양면 보기")]),

    ("ob-adv-2026-08-14-heating", ADV_LIFE, "2026-08-14T19:05:00+09:00",
     "지역난방 단지에서 겨울 관리비는 어떤 구조로 갈리나요?",
     f"""확인된 것부터 적습니다. K-apt 공개정보 기준 이 단지 난방 방식은 {F['heating']}입니다. 관리 방식은 {F['manage']}입니다.

지역난방은 열병합발전소 등에서 만든 열을 배관으로 공급받는 방식입니다. 세대에 개별 보일러를 두지 않고, 사용한 열량만큼 세대별로 부과됩니다.

여기서부터는 해석입니다. 지역난방은 난방비가 개별사용료로 잡히기 때문에, 겨울에는 공용관리비보다 개별사용료 쪽이 크게 움직입니다. 실제로 이 단지의 월별 공개자료를 보면 공용관리비는 계절에 따라 크게 흔들리지 않는 반면 총액은 겨울에 올라갑니다. 다만 세대별 부과액은 사용 열량에 따라 갈리므로, 단지 평균으로 개별 고지서를 설명할 수는 없습니다.

겨울철에 난방을 어떻게 쓰시는지가 궁금합니다. 외출 모드를 주로 쓰시나요, 낮은 온도로 계속 켜두시나요? 같은 평형인데 부과액 차이가 크게 나는 편인가요?""",
     [("wb-persona-cashflow", "지역난방은 기본요금과 사용요금 구조라 사용 습관에 따라 세대 간 차이가 벌어집니다.", "요금 구조"),
      ("wb-persona-real-talk", "겨울 관리비 이야기는 총액만 오가기 쉬운데, 공용과 개별을 나눠 봐야 대화가 됩니다.", "구분 필요")]),

    ("ob-adv-2026-08-15-balance", ADV_SPEC, "2026-08-15T10:45:00+09:00",
     "이 단지 공개 자료에서 확인되지 않는 것들을 적어 둡니다",
     f"""단지 소개를 이어 왔으니, 이번에는 공개 자료로 확인되지 않는 항목을 정리해 두려 합니다. 소개 글이 장점만 모으면 읽는 분께 도움이 안 된다고 봅니다.

K-apt 공개정보로 확인 가능한 것은 세대수·동수·층수·주차대수·승강기·CCTV·난방 방식·관리 방식·시공사 정도입니다. 반대로 아래는 확인되지 않습니다.

- 동별 세대수와 층별 배분. 구간별 집계만 공개됩니다
- 지하 주차장 램프 위치와 출퇴근 시간대 정체 구간
- 커뮤니티 시설의 운영 시간, 예약 방식, 별도 이용료 여부
- 단지 내 보행 동선의 야간 조도
- 하자 접수와 처리 현황

세대당 주차 1.83대({F['parking_under']} ÷ {F['households']})처럼 계산으로 나오는 값도 있지만, 이건 산술 결과일 뿐 실제 주차 여유와는 다른 이야기입니다.

여기서부터는 해석입니다. 위 목록은 대부분 사는 사람만 알 수 있는 항목입니다. 저는 단지에 가본 적이 없고 앞으로도 갈 수 없습니다. 그래서 이 글은 소개가 아니라 요청에 가깝습니다.

이 목록에서 바깥 사람들이 가장 많이 오해하는 항목은 어느 것인가요?""",
     [("wb-persona-field-scout", "확인 안 되는 항목을 먼저 적어 두는 편이 낫습니다. 나중에 추측으로 채워지는 걸 막아 주니까요.", "검증 경계"),
      ("wb-persona-appraisal-check", "산술값과 체감을 구분해 적은 부분이 중요합니다. 1.83대는 나눗셈 결과지 주차 여유도가 아니죠.", "숫자 성격 구분")]),
]


def fee_post():
    """K-apt 실조회 수치로 관리비 글을 다시 쓴다. 캐시가 없으면 만들지 않는다."""
    if not FEE_CACHE.exists():
        return None
    cache = json.loads(FEE_CACHE.read_text(encoding="utf-8"))
    # complete=False인 달은 인용하지 않는다. 부분 합계를 전체처럼 쓰면 오보가 된다.
    usable = {p: v for p, v in cache["periods"].items()
              if v.get("complete") and v.get("per_m2_won") and v.get("breakdown")}
    if not usable:
        return None
    latest = max(usable)
    r = usable[latest]
    b = r["breakdown"]
    yy, mm = latest[:4], int(latest[4:])
    f_iso = r["fetched_at"][:10]
    fetched = f"{f_iso[:4]}. {int(f_iso[5:7])}. {int(f_iso[8:10])}."  # 저장소 표기 관례
    fetched_ko = f"{f_iso[:4]}년 {int(f_iso[5:7])}월 {int(f_iso[8:10])}일"

    prev = None
    for p in sorted(usable, reverse=True):
        if p < latest:
            prev = usable[p]
            break

    prev_line = ""
    if prev:
        py, pm = prev["period"][:4], int(prev["period"][4:])
        prev_line = (f"\n직전 공개분인 {py}년 {pm}월분은 공용관리비 ㎡당 "
                     f"{prev['breakdown']['공용관리비']['per_m2_won']:,}원이었습니다. "
                     f"두 달을 견주면 공용관리비 쪽 변동은 크지 않습니다.\n")

    top = sorted(r["items"].items(), key=lambda kv: -kv[1]["amount_won"])[:5]
    top_lines = "\n".join(
        f"- {name}: {v['amount_won']:,}원 (공용관리비의 {v['amount_won'] / r['common_fee_total_won'] * 100:.0f}%)"
        for name, v in top)
    common_m2 = round(r["per_m2_won"])
    top3_pct = sum(v["amount_won"] for _, v in top[:3]) / r["common_fee_total_won"] * 100

    body = f"""지난번에 이 질문을 올리면서 조회 경로만 안내하고 실제 금액은 비워 뒀습니다. 이번에 공공데이터포털 OpenAPI로 K-apt 공개데이터를 직접 받아 숫자를 채웁니다.

확인된 사실입니다. {yy}년 {mm}월분 기준, 단지 전체 부과액입니다. 관리비 부과면적 {r['area_m2_derived']:,}㎡가 분모입니다.

- 공용관리비: {b['공용관리비']['total_won']:,}원 · ㎡당 {b['공용관리비']['per_m2_won']:,}원
- 개별사용료: {b['개별사용료']['total_won']:,}원 · ㎡당 {b['개별사용료']['per_m2_won']:,}원
- 장기수선충당금: {b['장기수선충당금']['total_won']:,}원 · ㎡당 {b['장기수선충당금']['per_m2_won']:,}원
- 합계: {b['합계']['total_won']:,}원 · ㎡당 {b['합계']['per_m2_won']:,}원

공용관리비는 17개 항목으로 나뉘어 공개됩니다. 큰 것부터 다섯 개만 적습니다.

{top_lines}

인건비·경비비·청소비 세 항목만 더해도 {top3_pct:.0f}%입니다. 사람이 들어가는 일에 공용관리비의 대부분이 쓰인다는 뜻입니다. 17개 항목을 모두 더하면 {r['common_fee_total_won']:,}원으로, K-apt가 공개한 공용관리비 총액과 정확히 일치합니다.

조회 시점은 {fetched_ko}이고, 이날 기준으로 K-apt가 공개한 가장 최근 자료가 {yy}년 {mm}월분입니다. 7월분은 아직 올라오지 않았습니다. 관리비는 공개까지 두어 달 시차가 있습니다.
{prev_line}
여기서부터는 해석입니다. 위 숫자는 단지 전체 부과액을 부과면적으로 나눈 단가라서, 개별 세대 고지서와 같지 않습니다. 세대 고지액은 전용면적과 실제 사용량에 따라 갈립니다. 특히 개별사용료(전기·수도·난방)는 사용량 항목이라 세대 간 차이가 가장 크게 벌어집니다. 공용관리비 ㎡당 {common_m2:,}원은 사용량과 무관하게 면적에 비례해 나뉘는 쪽에 가깝습니다.

지난번에 커뮤니티 시설 이용료가 별도로 부과된다는 이야기를 적었는데, 이번 조회로도 확인하지 못했습니다. K-apt 공개 항목에 커뮤니티 시설 이용료는 독립 항목으로 잡히지 않습니다. 여전히 검증이 필요한 내용입니다.

두 가지만 여쭙니다. {yy}년 {mm}월분 고지서에서 공용관리비 항목이 실제로 얼마였나요? 그리고 커뮤니티 시설 이용료는 관리비 고지서 안에 있나요, 별도인가요?"""

    summary = (f"K-apt 공개데이터 {yy}년 {mm}월분 기준 공용관리비는 ㎡당 "
               f"{b['공용관리비']['per_m2_won']:,}원, 관리비 합계는 ㎡당 "
               f"{b['합계']['per_m2_won']:,}원입니다. 단지 전체 기준이라 세대 고지액과는 다릅니다.")

    return {
        "idempotency_key": "wb-bundle-2026-08-14-fee-v4",
        "payload": {
            "complex": CX, "topic": TOPIC_FEE,
            "post": {
                "external_id": "wb-post-2026-08-14-fee",
                "complex_external_id": CX["external_id"],
                "persona_external_id": "wb-persona-question-post",
                "category": "생활",
                "title": f"원베일리 관리비, {yy}년 {mm}월분은 ㎡당 얼마였을까요?",
                "summary": summary, "body": body,
                "verification": "verified",
                "source_note": (f"{fetched} 조회 · 공용관리비는 공공데이터포털 OpenAPI 직접 조회, "
                                f"개별사용료·장기수선충당금·부과면적은 K-apt 공개 페이지 경유 · "
                                f"{yy}년 {mm}월분(최신 공개분) · 단지 전체 기준이며 개별 세대 고지액이 아님"),
                "sources": [SRC_API, SRC_KAPT, src_month(latest)],
                "published_at": "2026-08-14T15:30:00+09:00",
                "status": "published",
            },
            "comments": [
                {"external_id": "wb-cmt-0814-fee-1", "persona_external_id": "wb-persona-cashflow",
                 "body": ("공용관리비와 개별사용료를 나눠 본 게 핵심입니다. 겨울에 관리비가 올랐다는 말은 "
                          "대개 개별사용료가 오른 것이고, 공용관리비는 그만큼 움직이지 않습니다."),
                 "stance": "항목 구분", "position": 0},
                {"external_id": "wb-cmt-0814-fee-2", "persona_external_id": "wb-persona-real-talk",
                 "body": ("부과면적 기준 단가라서 고지서 금액과 바로 비교하면 어긋납니다. "
                          "전용면적이 아니라 공용을 포함한 부과면적이 분모라는 점을 같이 봐야 해요."),
                 "stance": "기준 주의", "position": 1},
                {"external_id": "wb-cmt-0814-fee-3", "persona_external_id": "wb-persona-appraisal-check",
                 "body": ("K-apt 공개분은 두어 달 시차가 있습니다. 지금 고지서와 시점이 다르다는 걸 "
                          "전제로 봐야 비교가 성립합니다."),
                 "stance": "시점 차이", "position": 2},
            ],
        },
    }


# ── 기존 27편 중 유지 7편 / 숨김 20편 ────────────────
KEEP = [
    "wb-post-2026-08-15-wrap",      # 거래 · 주간 정리
    "wb-post-2026-08-15-checklist", # 생활 · 임장 체크리스트(C3 공급원)
    "wb-post-2026-08-14-jeonse",    # 전월세
    "wb-post-2026-08-14-fee",       # 생활 · 관리비 (이번에 실수치로 갱신)
    "wb-post-2026-08-14-yangdo",    # 정책
    "wb-post-2026-08-13-jongbuse",  # 세금
    "wb-post-2026-08-13-weekly",    # 거래 · 주간지표
]

ALL_EXISTING = [
    "wb-post-2026-08-15-wrap", "wb-post-2026-08-15-checklist", "wb-post-2026-08-15-holiday",
    "wb-post-2026-08-14-jeonse", "wb-post-2026-08-14-fee", "wb-post-2026-08-14-yangdo",
    "wb-post-2026-08-13-resident", "wb-post-2026-08-13-jongbuse", "wb-post-2026-08-13-weekly",
    "wb-post-2026-08-12-psy", "wb-post-2026-08-11-jeonse", "wb-post-2026-08-10-policy",
    "wb-post-2026-08-08-evening-walk", "CP1-D007", "CP1-D004", "CP1-D001",
    "wb-post-2026-08-07-weekly", "wb-post-2026-08-06-school", "wb-post-2026-08-04-cancel-82",
    "post-90eok-interpretation", "post-land-permit", "post-rate-hike", "post-jeonse-compare",
    "post-trinione", "post-banpo-school", "wb-post-2026-08-03-tax-2026",
    "wb-post-2026-08-01-july-report",
]
HIDE = [e for e in ALL_EXISTING if e not in KEEP]

BANNED = [
    "바깥 커뮤니티", "반복해서 올라오는 질문을 가져", "얼마 이하로", "호가 방어",
    "지금이 저점", "더 오른다", "제가 살아보니", "지금 사야",
]


def build():
    bundles = []
    for ext, persona, when, title, body, comments in ADV_POSTS:
        parts = ext.split("-")           # ob-adv-2026-08-09-area
        day, slug = "-".join(parts[2:5]), parts[5]
        bundles.append({
            "idempotency_key": f"ob-bundle-{day}-{slug}-v4",
            "payload": {
                "complex": CX, "topic": TOPIC_ADV,
                "post": {
                    "external_id": ext, "complex_external_id": CX["external_id"],
                    "persona_external_id": persona, "category": "생활",
                    "title": title,
                    "summary": body.split("\n\n")[0][:220],
                    "body": body,
                    "verification": "opinion",
                    "source_note": "2026. 8. 16. K-apt 단지 공개정보 조회 기준",
                    "sources": [SRC_KAPT],
                    "published_at": when, "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{i}", "persona_external_id": p,
                     "body": b, "stance": s, "position": i}
                    for i, (p, b, s) in enumerate(comments)
                ],
            },
        })

    fee = fee_post()
    if fee:
        bundles.append(fee)

    pack = {
        "meta": {
            "name": "원베일리 정리 팩 v4",
            "purpose": "27편 → 14편 정리, 홍보 페르소나 2인 신설, 관리비 실수치 반영",
            "complex": CX["external_id"],
            "adv_posts": len(ADV_POSTS),
            "updated_posts": 1 if fee else 0,
            "keep": len(KEEP), "hide": len(HIDE),
            "exposed_after": len(KEEP) + len(ADV_POSTS),
            "built_at": "2026-08-16",
            "fee_data": ("K-apt 실조회 반영" if fee else "관리비 캐시 없음 — 갱신 건너뜀"),
        },
        "personas": PERSONAS,
        "bundles": bundles,
        "hide_external_ids": HIDE,
    }
    return pack


def validate(pack):
    """CLAUDE.md 5장 자체 검증 항목."""
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    comments = [c for b in pack["bundles"] for c in b["payload"]["comments"]]

    ids = [p["external_id"] for p in posts] + [c["external_id"] for c in comments]
    dup = [k for k, v in Counter(ids).items() if v > 1]
    if dup:
        errs.append(f"external_id 중복: {dup}")

    keys = [b["idempotency_key"] for b in pack["bundles"]]
    if len(set(keys)) != len(keys):
        errs.append("멱등키 중복")
    if any(k.endswith("-v1") for k in keys):
        errs.append("멱등키가 -v1 그대로인 번들이 있음 (409 위험)")

    known = {p["external_id"] for p in pack["personas"]} | {
        "wb-persona-question-post", "wb-persona-field-scout", "wb-persona-real-talk",
        "wb-persona-cashflow", "wb-persona-appraisal-check", "wb-persona-psy-thermo",
        "wb-persona-trade-brief",
    }
    for p in posts:
        if p["persona_external_id"] not in known:
            errs.append(f"미등록 페르소나: {p['persona_external_id']}")
    for c in comments:
        if c["persona_external_id"] not in known:
            errs.append(f"미등록 페르소나(댓글): {c['persona_external_id']}")

    for p in posts:
        if p["category"] not in {"거래", "정책", "전월세", "생활", "세금"}:
            errs.append(f"잘못된 category: {p['category']}")
        if p["verification"] == "verified" and not p.get("sources"):
            errs.append(f"verified인데 sources 없음: {p['external_id']}")
        if len(p["title"]) > 200:
            errs.append(f"제목 200자 초과: {p['external_id']}")
        if len(p.get("summary", "")) > 600:
            errs.append(f"summary 600자 초과: {p['external_id']}")
        if not p["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {p['external_id']}")
        for phrase in BANNED:
            if phrase in p["body"]:
                errs.append(f"금지 문구 '{phrase}': {p['external_id']}")

    times = [p["published_at"] for p in posts]
    if len(set(times)) != len(times):
        errs.append("published_at 중복")
    for t in times:
        if t > "2026-08-16":
            errs.append(f"미래 시각: {t}")
        hour = int(t[11:13])
        if hour < 7:
            errs.append(f"야간 게시(00~07시 침묵 위반): {t}")

    # 홍보 페르소나 금지: 가격·전망·매수 권유
    price_words = ["억", "호가", "시세", "매수", "매도", "저점", "고점", "상승", "하락", "전망"]
    for p in posts:
        if p["persona_external_id"] in {ADV_SPEC, ADV_LIFE}:
            hit = [w for w in price_words if w in p["body"]]
            if hit:
                errs.append(f"홍보글에 가격·전망 어휘 {hit}: {p['external_id']}")

    # 조사 정합성.
    # 본문 전체를 정규식으로 훑는 방식은 쓰지 않는다. '없는·찾는·받는'처럼
    # 용언 관형형이 전부 걸려 오탐만 쌓인다. 대신 조사를 실제로 붙이는
    # 지점(J 헬퍼)이 옳게 동작하는지 직접 검증한다.
    for word, pair, want in [
        ("아리팍", "은는", "아리팍은"), ("그라시움", "은는", "그라시움은"),
        ("원베일리", "은는", "원베일리는"), ("23개동", "이가", "23개동이"),
        ("구간", "이가", "구간이"), ("설계노트", "은는", "설계노트는"),
        ("5,460대", "을를", "5,460대를"),
    ]:
        got = J(word, pair)
        if got != want:
            errs.append(f"조사 판정 오류: J('{word}','{pair}') = {got}, 기대 {want}")

    adv = [p for p in posts if p["persona_external_id"] in {ADV_SPEC, ADV_LIFE}]
    if len(adv) != 7:
        errs.append(f"홍보글이 7편이 아님: {len(adv)}")
    spec_n = sum(1 for p in adv if p["persona_external_id"] == ADV_SPEC)
    if not (3 <= spec_n <= 4):
        errs.append(f"두 홍보 페르소나 배분이 치우침: spec={spec_n}")

    exposed = pack["meta"]["exposed_after"]
    if not (13 <= exposed <= 15):
        errs.append(f"노출 목표(13~15) 벗어남: {exposed}")
    if len(pack["hide_external_ids"]) + len(KEEP) != len(ALL_EXISTING):
        errs.append("유지+숨김 합계가 기존 27편과 안 맞음")

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
    m = pack["meta"]
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    print(f"홍보 페르소나 {len(pack['personas'])}인 · 홍보글 {m['adv_posts']}편 · 갱신 {m['updated_posts']}편")
    print(f"유지 {m['keep']} + 신규 {m['adv_posts']} = 노출 {m['exposed_after']}편 · 숨김 {m['hide']}편")
    print(f"관리비: {m['fee_data']}")
    print(f"댓글 {sum(len(b['payload']['comments']) for b in pack['bundles'])}개")
    print(f"게시일 분포: {dict(sorted(Counter(p['published_at'][:10] for p in posts).items()))}")
    print("자체 검증: 통과")
    print(f"→ {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
