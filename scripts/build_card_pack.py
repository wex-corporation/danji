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
  그래서 카드도 단지마다 다른 지표 + 다른 뼈대를 쓴다.

라운드
  1라운드 6장(파일럿 6곳) · 2라운드 11장(K-apt 정보가 있는 전 단지).
  라운드마다 지표 풀과 뼈대를 통째로 바꾼다. 같은 단지에 같은 지표가 두 번
  가지 않도록 USED 에 이전 배정을 적어 두고 검증에서 막는다.

서모스탯 (명세 6.3)
  기본은 단지당 하루 2편이고, 넘치는 단지는 배치에서 빼고 그 사실을 보고한다.
  `--ignore-cap` 을 주면 빼지 않고 경고만 남긴다(운영자 지시로 한도를 푼 경우).
  단, 출고 검사(명세 8.3)는 어떤 경우에도 풀지 않는다.

실행
  python3 scripts/build_card_pack.py --round 2
  python3 scripts/build_card_pack.py --round 2 --ignore-cap
"""

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INFO_DIR = REPO / "data" / "complex-info"
FEE_DIR = REPO / "data" / "mgmt-fees"
BASE = os.environ.get("BASE_URL", "https://danji.life")

# 단지 디렉터리 slug → (인제스트 external_id, 피드 slug)
# 디에이치 퍼스티어는 셋이 전부 다르다. 지어내면 422 unknown_complex 가 난다.
CX = {
    "olympic-park-foreon": ("cx-olympic-park-foreon", "olympic-park-foreon"),
    "eunma": ("cx-eunma", "eunma"),
    "helio-city": ("cx-helio-city", "helio-city"),
    "parkrio": ("cx-parkrio", "parkrio"),
    "ricents": ("cx-ricents", "ricents"),
    "one-bailey": ("cx-one-bailey", "one-bailey"),
    "acro-river-park": ("cx-acro-river-park", "acro-river-park"),
    "dh-firstier": ("cx-dh-firstier", "dh-firstier-ipark"),
    "godeok-gracium": ("cx-godeok-gracium", "godeok-gracium"),
    "jamsil-els": ("cx-jamsil-els", "jamsil-els"),
    "mapo-raemian-prugio": ("cx-mapo-raemian-prugio", "mapo-raemian-prugio"),
}

PERSONA = {
    "external_id": "wb-persona-num-compare",
    "handle": "숫자비교표",
    "avatar_label": "표",
    "tagline": "같은 잣대로 재지 않으면 비교가 아닙니다",
    "stance": "기준 통일",
    "expertise": ["공개 자료", "단지 비교"],
    "avatar_color": "#7c3aed",
}

SRC_INFO = {"label": "공동주택 기본 정보제공 서비스(K-apt) OpenAPI",
            "url": "https://www.data.go.kr/data/15058453/openapi.do", "publisher": "국토교통부"}
SRC_FEE = {"label": "공동주택 관리비 서비스(K-apt) OpenAPI",
           "url": "https://www.data.go.kr/data/15058566/openapi.do", "publisher": "국토교통부"}

TOPIC = {"external_id": "wb-topic-2026-08-card", "title": "우리 단지는 얼마인가",
         "summary": "같은 잣대로 잰 값 하나를 짧게 놓는다. 판단은 사는 사람이 한다",
         "category": "생활", "heat": 3}

BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "뒤처", "부럽", "명문", "상위권",
             "가장 좋", "가장 나쁜", "최고의", "최하"]
BAN_COMPARE = ["보다 낫", "보다 좋", "보다 우수", "보다 편리"]
BAN_PRICE = ["억", "호가", "시세", "매수", "매도", "전망", "집값"]
BAN_VAGUE = ["인터넷에서", "알려져 있", "라고 한다", "찾아보니"]
BAD_RO = ["명로", "층로", "원로", "동로", "분로"]

MAX_BODY = 480   # 카드다. 길어지면 카드가 아니다
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


def fee(slug, period="202605"):
    d = json.loads((FEE_DIR / f"{slug}.json").read_text(encoding="utf-8"))
    p = d["periods"][period]
    if not p.get("complete") or not p.get("per_m2_available"):
        raise KeyError(f"{slug} {period} 관리비가 불완전하다")
    return p


def published_today(feed_slug, day):
    """그날 이미 게시된 편수를 서버에서 센다. 팩 안에서만 세면 팩 사이 초과를 못 잡는다."""
    try:
        req = urllib.request.Request(f"{BASE}/api/v1/posts?complex={feed_slug}&limit=100",
                                     headers={"User-Agent": "danji-content-agent/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            items = json.load(r)["items"]
    except Exception as exc:  # noqa: BLE001
        print(f"[중단] 피드 조회 실패로 서모스탯을 확인할 수 없습니다: {exc}", file=sys.stderr)
        raise SystemExit(1)
    return sum(1 for i in items if (i.get("published_at") or "").startswith(day))


# ── 1라운드 뼈대 6종 ───────────────────────────────────────────
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


# ── 2라운드 뼈대 11종 ──────────────────────────────────────────
# 11곳 전체를 비교군으로 쓴다. 뼈대는 1라운드 것과도, 서로와도 겹치지 않게 짠다.

def SETN(peers):
    """비교군 이름. 항목마다 공개된 단지 수가 다르다 — 경비 인원은 올림픽파크
    포레온이 비어 있어 10곳이다. 11로 박아 두면 없는 단지를 세는 셈이 된다."""
    return f"K-apt에 같은 항목이 공개된 서울 {len(peers)}개 단지"


def r_cctv(name, i, peers):
    v = round(i["cctv_count"] / i["household_count"], 2)
    others = sorted(x for x in peers.values() if x != v)
    return (f"""CCTV {i['cctv_count']:,}대. 세대는 {i['household_count']:,}입니다. 나누면 세대당 {v}대.

{SETN(peers)} 중 세대당 1대를 넘는 곳은 여기뿐입니다. 나머지는 {others[0]}대에서 {others[-1]}대 사이에 있고요.

대수는 성능이 아닙니다. 어디를 비추는지, 녹화가 며칠 남는지는 공개값에 없습니다. 관리사무소에 영상을 요청해 보신 적 있나요?""")


def r_ev(name, i, peers):
    ev = i["ev_underground"] + i["ev_ground"]
    v = round(ev / i["household_count"] * 100, 1)
    others = sorted(x for x in peers.values() if x != v)
    return (f"""세 집 걸러 한 자리. 전기차 충전기 {ev:,}대를 {i['household_count']:,}세대로 나누면 {v}%입니다.

{SETN(peers)} 중 그다음으로 많은 곳이 {others[-1]}%예요. 자릿수가 다릅니다.

많다고 자리가 남는다는 뜻은 아닙니다. 완속인지 급속인지도 공개값에 없고요. 대기 없이 꽂고 계신가요?""")


def r_park(name, i, peers):
    v = i["parking_per_household"]
    others = sorted(x for x in peers.values() if x != v)
    return (f"""주차 자리가 세대 수보다 적으면 어떻게 될까요. 등록 주차 {i['parking_total']:,}대, {i['household_count']:,}세대. 세대당 {v}대입니다.

{SETN(peers)} 중 1대에 못 미치는 곳은 여기 하나입니다. 나머지는 {others[0]}대에서 {others[-1]}대 사이.

등록된 {i['parking_total']:,}대는 전부 지상입니다. 지하 주차장은 K-apt 공개값에 {i['parking_underground']}대로 돼 있어요. 밤에 대실 자리를 어떻게 찾으시나요?""")


def r_sec(name, i, peers):
    v = round(i["household_count"] / i["staff_security"], 1)
    lo, hi = min(peers.values()), max(peers.values())
    return (f"""경비 {i['staff_security']}명이 {i['household_count']:,}세대를 맡습니다. 1명당 {v}세대.

같은 방식으로 잰 {len(peers)}곳은 {lo}세대에서 {hi}세대 사이입니다. 여기는 위쪽에 있어요.

숫자가 크다고 근무가 부실하다는 뜻은 아닙니다. 순찰 동선과 근무 편성에 따라 체감이 갈리니까요. 야간에 사람을 마주치시나요?""")


def r_fee(name, i, peers):
    v = peers[i["slug"]]
    lo, hi = min(peers.values()), max(peers.values())
    return (f"""2026년 5월 공용관리비를 관리비 부과면적으로 나누면 ㎡당 {v:,}원입니다. 부과면적 84㎡라면 한 달 {round(v * 84 / 1000) * 1000:,}원꼴이고요.

{SETN(peers)}는 ㎡당 {lo:,}원에서 {hi:,}원 사이에 있습니다.

개별사용료와 장기수선충당금은 빠진 값입니다. 고지서 총액과는 다릅니다. 이번 달 고지서의 공용관리비 항목, 얼마 찍혀 있나요?""")


def r_ground(name, i, peers):
    g, u = i["parking_ground"], i["parking_underground"]
    zero = sum(1 for x in peers.values() if x == 0)
    return (f"""지상 주차 {g}대. 지하 {u:,}대.

{i['household_count']:,}세대 단지에서 지상에 남은 자리가 {g}대라는 뜻입니다. {SETN(peers)} 가운데 지상 자리가 아예 없는 곳이 {zero}곳, 반대로 전량 지상인 곳도 한 곳 있습니다.

지상이 비면 걷기는 편하고 짐 옮기기는 번거로워집니다. 이사나 장 볼 때는 어디에 대시나요?""")


def r_heat(name, i, peers):
    same = sum(1 for x in peers.values() if x == "지역난방")
    return (f"""{SETN(peers)} 가운데 {same}곳이 지역난방입니다. 여기만 개별난방이고요.

지역난방은 열병합발전소에서 만든 열을 받아 쓰고, 개별난방은 집집마다 보일러를 돌립니다. 요금 체계도, 고장 났을 때 부르는 곳도 다릅니다.

보일러 교체 주기가 돌아오면 그 비용은 세대 몫이 됩니다. 지금 쓰시는 보일러는 몇 년 되셨나요?""")


def r_clean(name, i, peers):
    v = round(i["household_count"] / i["staff_clean"], 1)
    lo, hi = min(peers.values()), max(peers.values())
    return (f"""미화 {i['staff_clean']}명. {i['household_count']:,}세대. 1명이 {v}세대를 맡는 계산입니다.

{len(peers)}곳은 {lo}세대에서 {hi}세대 사이입니다.

같은 인원이라도 동이 흩어져 있으면 이동에만 시간이 갑니다. 여기는 {i['dong_count']}개동이고요. 계단이나 복도 청소 주기가 어떻게 느껴지시나요?""")


def r_size(name, i, peers):
    v = i["household_count"]
    ordered = sorted(peers.values())
    rank = ordered.index(v) + 1
    return (f"""{v:,}세대. {SETN(peers)}를 세대수로 줄 세우면 작은 쪽에서 {rank}번째입니다.

큰 쪽 끝이 {ordered[-1]:,}세대, 작은 쪽 끝이 {ordered[0]:,}세대예요.

세대가 적으면 공용 비용을 나눠 낼 머릿수도 적습니다. 시설 하나 고칠 때 세대당 부담이 달라지죠. 관리비 부과 안건이 올라오면 챙겨 보시는 편인가요?""")


def r_perdong(name, i, peers):
    v = round(i["household_count"] / i["dong_count"], 1)
    lo, hi = min(peers.values()), max(peers.values())
    return (f"""{i['dong_count']}개동, {i['household_count']:,}세대. 한 동에 평균 {v}세대입니다.

{len(peers)}곳은 {lo}세대에서 {hi}세대 사이예요. 여기는 가운데쯤입니다.

한 동에 많이 담으면 승강기 앞이 붐비고, 적게 담으면 동 사이를 더 걷습니다. 어느 쪽이 더 크게 느껴지는지는 사는 사람만 알죠. 옆 동 이웃과는 마주치는 편이신가요?""")


def r_elev(name, i, peers):
    v = round(i["household_count"] / i["elevator_count"], 1)
    lo, hi = min(peers.values()), max(peers.values())
    return (f"""승강기 {i['elevator_count']}대가 {i['household_count']:,}세대를 나눠 맡습니다. 1대당 {v}세대.

{len(peers)}곳은 {lo}세대에서 {hi}세대 사이입니다.

이건 단지 전체를 합쳐 나눈 값입니다. 동마다 다르고, 출근 시간에는 같은 대수라도 체감이 달라집니다. 아침에 몇 대를 보내고 타시나요?""")


# (지표 키, 값 함수, 뼈대, 제목)
METRICS_R1 = {
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

METRICS_R2 = {
    "세대당 CCTV(전체)": (lambda i: round(i["cctv_count"] / i["household_count"], 2), r_cctv,
                          lambda i, v: f"세대당 CCTV {v}대. 11곳 중 여기만 1대를 넘습니다"),
    "EV 충전기 비율": (lambda i: round((i["ev_underground"] + i["ev_ground"]) / i["household_count"] * 100, 1), r_ev,
                       lambda i, v: f"충전기 {i['ev_underground'] + i['ev_ground']:,}대. 세 집 걸러 한 자리"),
    "세대당 주차": (lambda i: i["parking_per_household"], r_park,
                    lambda i, v: f"세대당 주차 {v}대. 밤에 어디에 대시나요?"),
    "경비1인당 세대": (lambda i: round(i["household_count"] / i["staff_security"], 1), r_sec,
                      lambda i, v: f"경비 1명이 {v:.0f}세대. 야간에 마주치시나요?"),
    "㎡당 공용관리비": (None, r_fee,
                       lambda i, v: f"㎡당 {v:,}원. 84㎡면 한 달 {round(v * 84 / 10000):,}만원꼴"),
    "지상 주차 대수": (lambda i: i["parking_ground"], r_ground,
                       lambda i, v: f"지상 주차 {v}대. 나머지 {i['parking_underground']:,}대는 지하"),
    "난방방식": (lambda i: i["heating"], r_heat,
                 lambda i, v: f"11곳 중 열 곳이 지역난방. 여기만 {v}"),
    "청소1인당 세대": (lambda i: round(i["household_count"] / i["staff_clean"], 1), r_clean,
                      lambda i, v: f"미화 1명이 {v:.0f}세대. 청소 주기 어떠신가요?"),
    "세대수": (lambda i: i["household_count"], r_size,
               lambda i, v: f"{v:,}세대. 11곳 중 작은 쪽에서 두 번째"),
    "동당 세대": (lambda i: round(i["household_count"] / i["dong_count"], 1), r_perdong,
                  lambda i, v: f"한 동에 {v:.0f}세대. {i['dong_count']}개동이 그렇습니다"),
    "승강기당 세대": (lambda i: round(i["household_count"] / i["elevator_count"], 1), r_elev,
                     lambda i, v: f"승강기 1대에 {v:.0f}세대. 몇 대 보내고 타시나요?"),
}

# 이 배치의 배정. 단지마다 지표가 달라야 마스킹 후에도 서로 다른 글이 된다.
ASSIGN_R1 = [
    ("olympic-park-foreon", "동수"),
    ("eunma", "준공연도"),
    ("helio-city", "세대당 CCTV"),
    ("parkrio", "최고층"),
    ("ricents", "부과면적 비율"),
    ("one-bailey", "관리인력1인당 세대"),
]

ASSIGN_R2 = [
    ("acro-river-park", "세대당 CCTV(전체)"),
    ("dh-firstier", "EV 충전기 비율"),
    ("eunma", "세대당 주차"),
    ("godeok-gracium", "경비1인당 세대"),
    ("helio-city", "㎡당 공용관리비"),
    ("jamsil-els", "지상 주차 대수"),
    ("mapo-raemian-prugio", "난방방식"),
    ("olympic-park-foreon", "청소1인당 세대"),
    ("one-bailey", "세대수"),
    ("parkrio", "동당 세대"),
    ("ricents", "승강기당 세대"),
]

# 단지가 이전 라운드(특이값·주변·카드)에서 이미 쓴 지표. 같은 지표가 두 번 가면
# 마스킹 후 유사도가 올라간다. validate() 가 이 표로 막는다.
USED = {
    "olympic-park-foreon": {"EV 충전기 비율", "세대당 CCTV", "전월세 회전율", "동수"},
    "helio-city": {"경비1인당 세대", "승강기당 세대", "전세 비중", "세대당 CCTV"},
    "ricents": {"세대수", "동당 세대", "저층 계약 비중", "부과면적 비율"},
    "parkrio": {"㎡당 공용관리비", "세대당 주차", "갱신요구권 사용률", "최고층", "자치관리"},
    "eunma": {"최고층", "지상주차 비율", "60㎡이하 계약 비중", "준공연도", "복도식"},
    "one-bailey": {"청소1인당 세대", "갱신계약 비율", "관리인력1인당 세대", "쓰레기수거"},
}

TIMES = ["T08:10:00+09:00", "T09:20:00+09:00", "T10:30:00+09:00", "T11:30:00+09:00",
         "T12:40:00+09:00", "T13:50:00+09:00", "T14:40:00+09:00", "T15:30:00+09:00",
         "T16:20:00+09:00", "T17:10:00+09:00", "T18:00:00+09:00", "T18:50:00+09:00"]

COMMENTS = [
    ("wb-persona-appraisal-check", "같은 항목을 같은 기준으로 재야 비교가 됩니다. 이 표는 그것만 맞춰 둔 값이에요.", "기준 통일"),
    ("wb-persona-field-scout", "숫자가 생활에서 어떻게 나타나는지는 사시는 분만 압니다. 그 대목이 비어 있어요.", "현장 검증 요청"),
]

ROUNDS = {
    1: {"assign": ASSIGN_R1, "metrics": METRICS_R1, "out": "card-w1.json",
        "prefix": "card-2026-08-", "idem": "v1", "now": "2026-08-21T17:20:00+09:00",
        "note": "파일럿 6곳. 비교군도 6곳"},
    2: {"assign": ASSIGN_R2, "metrics": METRICS_R2, "out": "card-w2.json",
        "prefix": "card2-2026-08-", "idem": "v1", "now": "2026-08-21T19:30:00+09:00",
        "note": "K-apt 정보가 있는 11곳 전체. 비교군도 11곳"},
}


def build(rn, ignore_cap):
    cfg = ROUNDS[rn]
    day = cfg["now"][:10]
    slugs = [s for s, _ in cfg["assign"]]
    rows = {s: info(s) for s in (CX if rn == 2 else slugs)}
    fees = {}
    if rn == 2:
        for s in rows:
            try:
                fees[s] = round(fee(s)["per_m2_won"])
            except (KeyError, OSError):
                pass          # 불완전한 달은 뺀다. 0원이라는 가짜 수치를 만들지 않는다

    bundles, skipped, over = [], [], []
    idx = 0
    for slug, key in cfg["assign"]:
        ext_id, feed_slug = CX[slug]
        live = published_today(feed_slug, day)
        if live >= 2:
            if ignore_cap:
                over.append((slug, live))
            else:
                skipped.append((slug, live))
                continue
        getter, frame, title_fn = cfg["metrics"][key]
        if getter is None:                      # 관리비처럼 별도 캐시에서 오는 지표
            peers, v = dict(fees), fees[slug]
        else:
            peers = {}
            for s, i2 in rows.items():
                try:
                    peers[s] = getter(i2)
                except (KeyError, TypeError, ZeroDivisionError):
                    continue   # 값이 없는 단지는 비교군에서 뺀다. 지어내지 않는다
            v = peers[slug]
        i = rows[slug]
        body = frame(i["complex_name"], i, peers)
        src = [SRC_FEE, SRC_INFO] if getter is None else [SRC_INFO]
        note = ("2026년 5월분 · K-apt 공용관리비를 관리비 부과면적으로 나눈 값 · "
                f"같은 방식으로 잰 {len(peers)}개 단지와 비교") if getter is None else (
            f"2026. 8. 16. 조회 · K-apt 공개정보 기준 · 같은 항목이 공개된 {len(peers)}개 단지와 비교")
        ext = f"{cfg['prefix']}{slug}"
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-{cfg['idem']}",
            "payload": {
                "complex_external_id": ext_id, "topic": TOPIC,
                "post": {
                    "external_id": ext, "complex_external_id": ext_id,
                    "persona_external_id": PERSONA["external_id"], "category": "생활",
                    "title": title_fn(i, v), "summary": body.split("\n\n")[0][:220],
                    "body": body, "verification": "verified",
                    "source_note": note, "sources": src,
                    "published_at": day + TIMES[idx], "status": "published",
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
    for slug, live in over:
        print(f"[한도 초과] {slug}: 오늘 이미 {live}편인데 --ignore-cap 으로 더 올립니다 (명세 6.3)",
              file=sys.stderr)

    return {
        "meta": {"name": f"짧은 카드 팩 (w{rn})", "round": rn, "posts": len(bundles),
                 "built_at": day, "assigned": dict(cfg["assign"]),
                 "skipped": [{"slug": s, "already": n} for s, n in skipped],
                 "over_cap": [{"slug": s, "already": n} for s, n in over],
                 "purpose": "공유 카드에 캡처되는 짧은 형식. 제목이 곧 캡처물이다",
                 "note": cfg["note"]},
        "personas": [PERSONA],
        "bundles": bundles,
    }


def validate(pack, rn):
    cfg = ROUNDS[rn]
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    comments = [c for b in pack["bundles"] for c in b["payload"]["comments"]]
    reg = {PERSONA["external_id"], "wb-persona-appraisal-check", "wb-persona-field-scout"}
    now = cfg["now"]

    ids = [p["external_id"] for p in posts] + [c["external_id"] for c in comments]
    if len(set(ids)) != len(ids):
        errs.append("external_id 중복")
    if len({p["published_at"] for p in posts}) != len(posts):
        errs.append("published_at 중복")

    keys = [pack["meta"]["assigned"][p["external_id"].rsplit(cfg["prefix"], 1)[-1]] for p in posts]
    if len(set(keys)) != len(keys):
        errs.append(f"배치 안에서 지표가 겹친다 — 마스킹하면 같은 글이 된다: {Counter(keys)}")
    if rn > 1:
        # USED 는 2라운드 시점의 기록이다. 1라운드 배정 자체가 여기 들어 있으므로
        # 1라운드를 재생성할 때 걸면 자기 자신을 반려하게 된다.
        for slug, key in cfg["assign"]:
            base = key.split("(")[0]
            if base in USED.get(slug, ()):
                errs.append(f"{slug}: '{base}' 는 이전 라운드에서 이미 썼다")

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
        if p["published_at"] > now:
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
    ap = argparse.ArgumentParser(description="짧은 카드 생성기")
    ap.add_argument("--round", type=int, default=2, choices=sorted(ROUNDS))
    ap.add_argument("--ignore-cap", action="store_true",
                    help="서모스탯 한도를 넘겨도 빼지 않는다. 출고 검사는 그대로 건다")
    args = ap.parse_args()

    pack = build(args.round, args.ignore_cap)
    if not pack["bundles"]:
        print("만들 카드가 없습니다. 서모스탯 여유가 있는 단지가 없습니다.", file=sys.stderr)
        return 1
    errs = validate(pack, args.round)
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    out = REPO / "content" / ROUNDS[args.round]["out"]
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pre = ROUNDS[args.round]["prefix"]
    print(f"  {'단지':22}{'지표':18}{'제목':>4}{'본문':>6}  제목")
    for b in pack["bundles"]:
        p = b["payload"]["post"]
        slug = p["external_id"].rsplit(pre, 1)[-1]
        print(f"  {slug:20}{pack['meta']['assigned'][slug]:18}{len(p['title']):>4}{len(p['body']):>6}  {p['title']}")
    print(f"\n카드 {len(pack['bundles'])}장 · 댓글 "
          f"{sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
