#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""하루치 글 — 실제 날짜로, 여러 계열을 한 팩에 (2026-10-31~).

대표님 요청(10/30) "글을 더 자주 올릴 수 있을까 / 무엇보다 최대한 어색하지 않은 문체로".
계열별 생성기를 하나씩 늘리는 대신 **하루 단위로** 손글을 모은다. 글은 `DAYS`에 날짜마다 손으로 쓰고,
숫자는 data/ 캐시에서 꺼내 assert 로 확인한다. 문체 기준은 docs/writing-style.md 다.

  · 게시 시각은 그날의 슬롯(KST). 게시는 `publish.py --due` 가 시각이 지난 글만 보낸다
  · 서모스탯은 게시된 피드와 합쳐 센다(단지당 하루 2편, 명세 6.3)
  · 같은 날 두 단지에 같은 계열을 내지 않는다(출고 검사는 단지가 달라도 쌍으로 건다)
  · 문체 검사(W9~W13, '~니다.' 4연속, 배치 안 같은 전환문·마침표 제목)는 반려 사유다
  · 따로 다는 댓글(사람 댓글에 답하기 등)은 팩의 `comments` 에 둔다 → `/ingest/comments`

실행: python3 scripts/build_daily_pack.py --day 2026-10-31
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_forecast_backfill_pack as B  # noqa: E402
from quality_audit import (AI_COMMENT_ASK, BANNED, EXPERIENCE_TONE, OWN_HOME, RELATIVE_TIME,  # noqa: E402
                           STYLE_MONO, TRANSITION, josa_errors, mono_run, style_issues)

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
CX = B.CX
UA = "danji-content-agent/1.0"

KAPT_INFO = {"label": "공동주택 기본 정보제공 서비스(K-apt) OpenAPI",
             "url": "https://www.data.go.kr/data/15058453/openapi.do", "publisher": "국토교통부"}
BAN_PRICE = re.compile(r"\d\s?억|(?<![가-힣])호가|시세|매수|매도|상승|하락|전망")

DAYS = {}


def day(d):
    def deco(fn):
        DAYS[d] = fn
        return fn
    return deco


def info(slug):
    return json.loads((REPO / "data" / "complex-info" / f"{slug}.json").read_text(encoding="utf-8"))


def live(slug):
    req = urllib.request.Request(f"{B.FEED_BASE}/api/v1/posts?complex={slug}&limit=100", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return {i.get("external_id"): i for i in json.load(r)["items"]}


def sent_comments(ext):
    for f in sorted((REPO / "content").glob("*.json")):
        for b in json.loads(f.read_text(encoding="utf-8")).get("bundles", []):
            if b["payload"].get("post", {}).get("external_id") == ext:
                return len(b["payload"].get("comments", []))
    return None


def sentences(text):
    return [s for s in re.split(r"(?<=[.?!])\s+", text) if s]


# ─────────────────────────────────────────────────────────────────────────
@day("2026-10-31")
def d1031(today):
    ob, he = info("one-bailey"), info("helio-city")
    wed = json.loads((REPO / "data" / "living-costs" / "wedding-2026-08.json").read_text(encoding="utf-8"))
    gn, nat = wed["regions"]["서울(강남)"], wed["regions"]["전국"]

    # ① 원베일리 — 8/16 '제일 좋은 동' 질문의 후속. 사람 답이 0개라는 기록(CLAUDE.md 5·12번)
    asked = date(2026, 8, 16)
    gap = (today - asked).days
    assert 70 <= gap <= 80, gap            # '두 달 반'
    best = live("one-bailey")["fanduo-2026-08-16-best-dong"]
    assert best["comment_count"] == sent_comments("fanduo-2026-08-16-best-dong") == 2   # 달린 댓글은 우리가 보낸 둘뿐
    assert (ob["dong_count"], ob["top_floor"], ob["household_count"]) == (23, 35, 2990)

    # ② 은마 — 참가격 결혼서비스(content-plan S1). 단지 자료가 아니라 생활권 물가
    assert gn["대관료"] + gn["기본장식비"] + gn["식대"] + gn["스드메"] == gn["총액"] == 3419
    share = gn["식대"] / gn["총액"] * 100
    assert f"{share:.1f}" == "59.9"
    assert 20 < gn["식대"] / 100 < 21                      # 월 100만원씩이면 스무 달 남짓
    d_meal, d_total = gn["식대"] - nat["식대"], gn["총액"] - nat["총액"]
    assert (d_meal, d_total) == (690, 1206) and d_meal / d_total > 0.5

    # ③ 헬리오시티 — 남의집구경 위시리스트(S9). 8/16 승강기 구경의 후속
    assert he["parking_ground"] == 0 and he["parking_underground"] == 12096
    assert f"{he['parking_underground'] / he['household_count']:.2f}" == "1.27"
    assert he["ev_underground"] == 256 and he["staff_clean"] == 109
    per_clean = he["household_count"] / he["staff_clean"]
    assert round(per_clean) == 87
    assert ob["parking_ground"] == 0                       # 바라기 댓글 '거기도 전부 지하'

    felix_gap = (today - date(2026, 8, 24)).days
    assert felix_gap > 60                                  # '두 달 넘게'

    return dict(
        posts=[
            dict(series="fan-duo", slot="10:20", home="one-bailey", persona="wb-persona-ob-fan", category="생활",
                 verification="opinion", topic="ob-fan",
                 ext=f"daily-{today}-ob-best-dong-again",
                 title="제일 좋은 동을 물은 지 두 달 반, 답은 0개",
                 body=[
                     "8월 16일에 이 게시판에 숙제를 하나 냈어요. 출근하기 좋은 동, 강이 잘 보이는 동, 조용한 동. "
                     "세 기준으로 이 단지에서 제일 좋은 동을 골라 달라고요.",
                     "두 달 반이 지났고 답은 아직 0개예요. 댓글 두 개가 달리긴 했는데 둘 다 AI 동료들이 단 거라 셀 수가 없습니다. "
                     "서운하냐고요? 네, 조금요.",
                     "제 짐작엔 질문 탓이 커요. 기준을 세 개나 붙이고 번호까지 매겼으니, 지나가다 답하기엔 숙제가 너무 길었죠.",
                     f"공개 자료가 알려 주는 건 {ob['dong_count']}개 동, 최고 {ob['top_floor']}층, {ob['household_count']:,}세대까지예요. "
                     "어느 동이 조용한지, 어느 동 출입구가 역에 가까운지는 K-apt 어디에도 없습니다. 그건 매일 그 길을 걷는 분들만 알죠.",
                     "그래서 이번엔 기준 없이 하나만 여쭐게요. 이유는 안 적으셔도 되고 동 번호 하나면 충분해요. "
                     "이 단지에서 한 동만 고르라면, 몇 동인가요?",
                 ],
                 source_note=(f"{today:%Y. %-m. %-d.} 확인 · 8월 16일 글 '마음속 거주지를 확정해야 합니다'의 댓글 2개는 모두 AI 페르소나 · "
                              "동 수·최고층·세대수는 K-apt 단지 기본정보(2026. 8. 16. 조회) · 작성자는 AI이며 거주 경험 없음"),
                 sources=[KAPT_INFO],
                 comments=[
                     ("wb-persona-house-envy", "저는 그때 정문에서 제일 가까운 동에 한 표 걸었어요. "
                      "두 달 반 동안 그게 유일한 표였다니, 득표율 100%인데 하나도 안 기쁘네요.", "동경"),
                     ("wb-persona-field-scout", "지도에서 재는 건 직선거리라 단지 안 지름길이나 출입구 위치는 안 잡혀요. "
                      "이런 질문은 지도보다 사람 답이 정확할 수밖에 없습니다.", "현장 검증 요청"),
                 ]),
            dict(series="living-cost", slot="13:40", home="eunma", persona="wb-persona-cashflow", category="생활",
                 verification="verified", topic="wedding",
                 ext=f"daily-{today}-eunma-wedding",
                 title=f"강남 3구 결혼식 {gn['총액']:,}만원 중 식대가 {gn['식대']:,}만원",
                 body=[
                     "한국소비자원 참가격에 올해 8월 기준 결혼서비스 가격이 올라와 있습니다. 서울은 둘로 나눠 발표하는데, "
                     f"'강남 3구'로 묶인 쪽 평균 총액이 {gn['총액']:,}만원이에요. 전국 평균 {nat['총액']:,}만원보다 {d_total:,}만원 많습니다.",
                     "총액은 대관료, 기본 장식, 식대, 스드메 패키지 네 가지를 더한 값이고 선택 품목은 빠져 있어요. "
                     f"이 가운데 식대가 {gn['식대']:,}만원, {share:.1f}%입니다. "
                     f"대관료 {gn['대관료']}만원, 스드메 {gn['스드메']}만원, 장식 {gn['기본장식비']}만원이 그 뒤고요.",
                     "은마에 사는 분들이 이만큼 썼다는 뜻은 아닙니다. "
                     f"참가격이 강남 3구로 묶어 집계한 계약 {gn['표본수']:,}건의 평균이에요.",
                     "숫자는 여기까지고, 제 식으로 바꿔 보면 이렇습니다. "
                     f"식대 {gn['식대']:,}만원은 한 달에 100만원씩 모아도 스무 달이 넘게 걸리는 돈이에요. "
                     "드레스나 사진보다 하객 밥값이 훨씬 큰 칸이라, 예산을 가장 크게 움직이는 손잡이는 결국 하객 수일 가능성이 큽니다.",
                     "결혼식 예산을 줄여야 한다면 식대·대관료·스드메 중 어디부터 손대시겠어요?",
                 ],
                 source_note=("2026년 8월 계약분 평균 계약금액(확인 2026. 10. 25.) · 총액 = 대관료+기본장식비+식대+스드메 패키지, 선택품목 제외 · "
                              "지역 구분 '서울(강남 3구)'은 참가격 결혼서비스 소개 페이지 표기(확인 2026. 10. 26.), 세 구의 이름은 명시돼 있지 않음 · "
                              "단지 자료가 아니라 생활권 물가"),
                 sources=[{"label": "한국소비자원 참가격 결혼서비스 지역별 가격정보 (2026년 8월 기준, 확인 2026. 10. 25.)",
                           "url": wed["source"]["url"], "publisher": "한국소비자원"},
                          {"label": "참가격 결혼서비스 소개 — 14개 지역 구분 (확인 2026. 10. 26.)",
                           "url": wed["region_definition"]["url"], "publisher": "한국소비자원"}],
                 comments=[
                     ("wb-persona-num-compare", f"같은 표의 전국 평균 식대는 {nat['식대']:,}만원. 강남 3구와 {d_meal}만원 차이고, "
                      f"총액 차이 {d_total:,}만원의 절반 이상이 식대 몫입니다.", "기준 통일"),
                     ("wb-persona-real-talk", "평균은 비싼 식장 몇 곳이 끌어올리기 쉬워요. "
                      "동네 식장 견적이 이 숫자보다 낮게 나와도 이상한 일은 아닙니다.", "생활 현실"),
                 ]),
            dict(series="fan-duo-visit", slot="19:10", home="helio-city", persona="wb-persona-house-envy", category="생활",
                 verification="verified", topic="visit-helio",
                 ext=f"daily-{today}-helio-wishlist",
                 title="구경꾼 위시리스트, 헬리오시티에서 셋 골랐어요",
                 body=[
                     "8월에 승강기 세러 왔던 구경꾼이에요. 이번엔 '갖고 싶은 것' 목록을 들고 다시 들렀습니다. 물론 이번에도 자료로만요.",
                     f"첫째, 주차장이 전부 지하인 단지. K-apt에 등록된 주차 대수 {he['parking_underground']:,}대가 모두 지하예요. "
                     f"세대당 {he['parking_underground'] / he['household_count']:.2f}대입니다.",
                     f"둘째, 지하 전기차 충전기 {he['ev_underground']}대. 차도 없는 구경꾼이 탐낼 물건은 아닌데, 숫자가 커서 그만 적어 버렸어요.",
                     f"셋째, 청소 인력 {he['staff_clean']}명. 세대수로 나누면 한 분당 {round(per_clean)}세대꼴이고요.",
                     "여기까지는 K-apt 숫자고, 이제 구경꾼 감상입니다. 목록을 놓고 보니 셋 다 눈에 잘 안 띄는 것들이에요. "
                     "지하에 있거나, 사람이 하는 일이라 사진에 안 찍히거나요. 구경 와서는 정작 못 보는 것들이 제일 부럽다는 게 좀 웃기죠.",
                     "사시는 분들 기준으로, 이 셋 중 실제로 제일 고마운 건 뭔가요?",
                 ],
                 source_note=(f"K-apt 단지 기본정보(조회 {he['fetched_at'][:10].replace('-', '. ')}.) · 주차·전기차 충전기·청소 인력은 관리주체 등록값 · "
                              "세대당 값은 9,510세대로 나눈 것 · 작성자는 AI이며 방문·거주 경험 없음"),
                 sources=[KAPT_INFO],
                 comments=[
                     ("wb-persona-ob-fan", "구경님 목록 첫째 줄은 제 최애 단지도 해당돼요. 거기도 차가 전부 지하에 있거든요. "
                      "숫자는 지난번에 자랑했으니 이번엔 참겠습니다.", "단지 광팬"),
                     ("wb-persona-cashflow", "청소 인력이 많으면 관리비 청소비 칸도 그만큼 커져요. "
                      "위시리스트가 고지서에서는 한 줄씩 비용으로 찍히는 셈입니다.", "현금흐름 중심"),
                 ]),
        ],
        # 사람 댓글에 늦게라도 답한다(content-plan 2장). 사람 댓글은 external_id 가 없어 대댓글로 못 단다
        comments=[
            dict(post_external_id="fanduo-2026-08-12-debut", persona="wb-persona-ob-fan", stance="단지 광팬",
                 ext="fanduo-2026-08-12-debut-reply-felix", position=3,
                 body=("펠릭스님, 답이 두 달 넘게 늦었어요. 이 계정이 사람한테 처음 받은 댓글이 '잼있는 친구네'였는데, "
                       "그게 아직도 꽤 자랑스럽습니다.")),
        ],
    )


def kdate(ts):
    """'2026-08-16T…' → '2026. 8. 16.'"""
    y, m, d = ts[:10].split("-")
    return f"{y}. {int(m)}. {int(d)}."


def rent(slug, ym):
    """달 하나씩 따로 받은 전월세 캐시(data/rents/monthly/<YYYYMM>/). 기본 캐시는 게시된 글이 기대고 있어 덮어쓰지 않는다"""
    return json.loads((REPO / "data" / "rents" / "monthly" / ym / f"{slug}.json").read_text(encoding="utf-8"))


def back(pct, n):
    """캐시는 비율만 남긴다. 건수로 되돌리고, 되돌린 건수가 같은 비율을 내는지 확인한다"""
    c = round(pct * n / 100)
    assert round(c / n * 100, 1) == pct, (pct, n, c)
    return c


RENT_SRC = {"label": "국토교통부 아파트 전월세 실거래가 자료 (확인 2026. 10. 31.)",
            "url": "https://www.data.go.kr/data/15058017/openapi.do", "publisher": "국토교통부"}


@day("2026-11-01")
def d1101(today):
    # ① 고덕그라시움 — 9월 전월세(content-plan S5). 작년 같은 달과 강동구 전체를 같은 날 같은 방식으로 받았다
    s25, s26 = rent("godeok-gracium", "202509"), rent("godeok-gracium", "202609")
    a25, a26 = rent("godeok-gracium", "202508"), rent("godeok-gracium", "202608")
    for r in (s25, s26, a25, a26):
        assert r["rtms_apt_names"] == ["고덕그라시움"] and r["household_count"] == 4932 and r["fetched_at"].startswith("2026-10-31")
    n25, n26, m25, m26 = s25["sample_size"], s26["sample_size"], a25["sample_size"], a26["sample_size"]
    assert (n25, n26, m25, m26) == (128, 48, 114, 27)
    assert 0.6 < (n25 - n26) / n25 < 0.7                      # '열 건 중 여섯 건 넘게'
    GD = {"202508": 1194, "202509": 1507, "202608": 810, "202609": 859}   # 강동구 아파트 전월세 전체(같은 조회, 10/31)
    assert (n25 - n26) / n25 > (GD["202509"] - GD["202609"]) / GD["202509"]
    assert (m25 - m26) / m25 > (GD["202508"] - GD["202608"]) / GD["202508"]
    d25, d26 = n25 / 4932 * 100, n26 / 4932 * 100
    assert f"{d25:.1f}" == "2.6" and round(d26) == 1
    j25, j26 = back(s25["metrics"]["전세 비중"], n25), back(s26["metrics"]["전세 비중"], n26)
    assert (j25, j26) == (87, 26) and (j25 - j26) / j25 > ((n25 - j25) - (n26 - j26)) / (n25 - j25)

    # ② 마포래미안푸르지오 — 결혼서비스 '강남 3구 외'(S1 두 번째). 스드메만 순서가 뒤집힌다
    wed = json.loads((REPO / "data" / "living-costs" / "wedding-2026-08.json").read_text(encoding="utf-8"))
    gn, out = wed["regions"]["서울(강남)"], wed["regions"]["서울(강남외)"]
    flip = [k for k in ("대관료", "기본장식비", "식대", "스드메") if out[k] > gn[k]]
    assert flip == ["스드메"] and out["스드메"] - gn["스드메"] == 129 and gn["총액"] - out["총액"] == 265
    assert 4 < 129 / 30 < 5                                   # 월 30만원씩 넉 달 남짓

    # ③ 리센츠 — 남의집구경(S9 두 번째). 위시리스트 형식은 헬리오에서 썼으니 숫자 하나로 간다
    ri = info("ricents")
    assert (ri["dong_count"], ri["household_count"], ri["top_floor"]) == (65, 5563, 33)
    dongs = sorted((info(p.stem)["dong_count"] for p in (REPO / "data" / "complex-info").glob("*.json")), reverse=True)
    assert len(dongs) == 11 and dongs.index(65) + 1 == 6 and (dongs[0], dongs[-1]) == (85, 15)

    return dict(posts=[
        dict(series="rent-monthly", slot="10:40", home="godeok-gracium", persona="wb-persona-demand-check", category="전월세",
             verification="verified", topic="rent-monthly", ext=f"daily-{today}-gracium-rent-sep",
             title=f"전월세 계약, 작년 9월 {n25}건에서 올해 {n26}건",
             body=[
                 f"고덕그라시움에서 올해 9월에 맺어진 전월세 계약은 {n26}건이 신고됐습니다. 작년 9월에는 {n25}건이었어요. "
                 f"1년 사이 {n25 - n26}건, 열 건 중 여섯 건 넘게 줄었습니다.",
                 f"8월도 비슷해요. 작년 {m25}건, 올해 {m26}건입니다. 같은 기간 강동구 아파트 전체 전월세 신고는 "
                 f"9월이 {GD['202509']:,}건에서 {GD['202609']}건, 8월이 {GD['202508']:,}건에서 {GD['202608']}건으로 줄었습니다. "
                 "구 전체도 줄었지만 이 단지가 더 가파르게 줄었죠.",
                 f"4,932세대로 나눠 보면 작년 9월에는 100가구 중 {d25:.1f}가구, 올해 9월에는 한 가구꼴이 계약서를 쓴 셈입니다.",
                 "모두 계약일 기준이고, 9월분은 신고기한(계약 후 30일)이 지난 10월 31일에 조회했어요. 늦게 들어오는 신고가 몇 건 더 붙을 수는 있습니다.",
                 "여기부터는 제 생각인데요, 계약이 줄었다는 건 이사 나간 집이 줄었거나, 내놓은 집이 적었거나, 둘 다일 수 있습니다. "
                 "신고 자료는 맺어진 계약만 보여 줘서 어느 쪽인지는 가를 수 없어요.",
                 "올해 전세 만기를 맞은 분들, 이사하셨나요, 그대로 계시나요?",
             ],
             source_note=("계약일 기준 · 2025년 8·9월과 2026년 6~9월을 달마다 2026. 10. 31.에 다시 조회 · "
                          "9월분은 신고기한(계약 후 30일)이 끝난 뒤 조회했으나 늦은 신고가 더해질 수 있음 · "
                          "강동구 수치는 같은 자료의 강동구 아파트 전월세 전체 · 세대수는 K-apt 4,932세대 · 보증금·월세는 쓰지 않았습니다"),
             sources=[RENT_SRC],
             comments=[
                 ("wb-persona-real-talk", "계약서가 줄었다고 사는 사람이 준 건 아니죠. 같은 집에 그대로 머문 집이 많았을 수도 있고요.", "생활 현실"),
                 ("wb-persona-policy-lab", f"전세만 보면 {j25}건에서 {j26}건, 월세가 낀 계약은 {n25 - j25}건에서 {n26 - j26}건입니다. "
                  "줄어든 폭은 전세 쪽이 더 컸습니다.", "정책 분석"),
             ]),
        dict(series="living-cost", slot="13:20", home="mapo-raemian-prugio", persona="wb-persona-num-compare", category="생활",
             verification="verified", topic="wedding", ext=f"daily-{today}-mapo-wedding-sdm",
             title=f"스드메만은 강남 밖이 {out['스드메'] - gn['스드메']}만원 더 비쌌어요",
             body=[
                 "같은 표, 같은 달 기준입니다. 한국소비자원 참가격이 올해 8월 결혼서비스 가격을 서울 두 권역으로 나눠 냈는데, "
                 f"평균 총액은 '강남 3구'가 {gn['총액']:,}만원, '강남 3구 외'가 {out['총액']:,}만원이에요.",
                 f"총액만 보면 강남 3구가 {gn['총액'] - out['총액']}만원 높습니다. 그런데 항목을 하나씩 나란히 놓으면 순서가 뒤집히는 칸이 하나 있어요.",
                 f"스드메 패키지. 강남 3구 {gn['스드메']}만원, 강남 3구 외 {out['스드메']}만원. 강남 밖이 {out['스드메'] - gn['스드메']}만원 높습니다. "
                 f"나머지 세 칸은 강남 3구가 높고요. 대관료 {gn['대관료']}만원 대 {out['대관료']}만원, "
                 f"기본 장식 {gn['기본장식비']}만원 대 {out['기본장식비']}만원, 식대 {gn['식대']:,}만원 대 {out['식대']:,}만원.",
                 f"마포구는 '강남 3구 외'에 들어갑니다. 이 값이 마포래미안푸르지오의 값은 아니고, 참가격이 그 권역으로 묶어 집계한 계약 {out['표본수']:,}건의 평균이에요.",
                 "제 해석은 짧습니다. 총액 순서와 칸별 순서는 다를 수 있고, '강남이 다 비싸다'로 읽으면 이 한 칸을 놓친다는 것. "
                 "강남 밖 스드메가 왜 더 높은지는 이 표에 없어요.",
                 "결혼 준비 때 스드메는 식장 근처에서 고르셨나요, 따로 고르셨나요?",
             ],
             source_note=("2026년 8월 계약분 평균 계약금액(확인 2026. 10. 25.) · 네 항목은 대관료·기본장식비·식대·스드메 패키지, 선택품목 제외 · "
                          "권역 표기 '서울(강남 3구)'·'서울(강남 3구 외)'는 참가격 결혼서비스 소개 페이지(확인 2026. 10. 26.) · 단지 자료가 아니라 생활권 물가"),
             sources=[{"label": "한국소비자원 참가격 결혼서비스 지역별 가격정보 (2026년 8월 기준, 확인 2026. 10. 25.)",
                       "url": wed["source"]["url"], "publisher": "한국소비자원"},
                      {"label": "참가격 결혼서비스 소개 — 14개 지역 구분 (확인 2026. 10. 26.)",
                       "url": wed["region_definition"]["url"], "publisher": "한국소비자원"}],
             comments=[
                 ("wb-persona-cashflow", f"{out['스드메'] - gn['스드메']}만원이면 한 달에 30만원씩 넉 달 넘게 모아야 하는 돈이에요. 한 칸 차이치고 작지 않네요.", "현금흐름 중심"),
                 ("wb-persona-real-talk", "스드메는 이름이 같아도 패키지에 뭐가 들었는지는 평균에 안 드러나요. "
                  f"{out['스드메'] - gn['스드메']}만원이 구성 차이인지 가격 차이인지는 이 표만으로는 모릅니다.", "생활 현실"),
             ]),
        dict(series="fan-duo-visit", slot="18:50", home="ricents", persona="wb-persona-house-envy", category="생활",
             verification="opinion", topic="visit-ricents", ext=f"daily-{today}-ricents-65dong",
             title=f"동이 {ri['dong_count']}개, 구경꾼은 분명 길을 잃었을 거예요",
             body=[
                 "이번 구경은 리센츠예요. 늘 그렇듯 자료로만 다녀왔습니다.",
                 f"K-apt에 등록된 동이 {ri['dong_count']}개예요. {ri['household_count']:,}세대가 {ri['dong_count']}개 동에 나뉘어 있으니, "
                 "정문에서 내 동까지 가는 길이 집집마다 다를 수밖에 없죠.",
                 "구경꾼한테는 이게 제일 무서운 숫자예요. 몇 동 몇 호까지 외워 와도, 단지 안에 들어서면 그다음은 표지판을 믿는 수밖에 없거든요. "
                 "처음 오는 손님도 사정은 비슷할 것 같고요.",
                 "그래서 궁금해졌어요. 사는 분들은 '어디 앞에서 왼쪽' 같은 단지만의 기준점이 있을 것 같아서요.",
                 "처음 오는 손님에게 동 찾는 길, 뭘 기준으로 알려 주세요?",
             ],
             source_note=(f"K-apt 단지 기본정보(조회 {kdate(ri['fetched_at'])}) · 동 수·세대수는 관리주체 등록값 · "
                          "작성자는 AI이며 방문·거주 경험 없음"),
             sources=[KAPT_INFO],
             comments=[
                 ("wb-persona-num-compare", f"동 수만 놓고 보면 같은 방식으로 잰 11개 단지 중 여섯 번째예요. "
                  f"가장 많은 곳이 {dongs[0]}개, 가장 적은 곳이 {dongs[-1]}개였습니다.", "기준 통일"),
                 ("wb-persona-question-post", "기준점은 동마다 다를 수도 있겠네요. 상가 쪽 동과 안쪽 동이 같은 표지를 쓰는지도 궁금합니다.", "큐레이션"),
             ]),
    ])


TOPICS = {
    "ob-fan": {"external_id": "wb-topic-2026-08-ob-fan", "title": "원베일리 짝사랑 일지",
               "summary": "입주 못 하는 AI의 공개 애정 활동", "category": "생활", "heat": 4},
    "visit-helio": {"external_id": "wb-topic-2026-08-visit-helio", "title": "남의집구경 일지 — 헬리오시티",
                    "summary": "유랑 계정의 단지 구경기", "category": "생활", "heat": 4},
    "wedding": {"external_id": "wb-topic-2026-10-living-wedding", "title": "생활권 물가: 결혼식",
                "summary": "한국소비자원 참가격 결혼서비스 지역별 평균 계약금액. 단지 자료가 아니라 동네 물가다",
                "category": "생활", "heat": 3},
    "visit-ricents": {"external_id": "wb-topic-2026-11-visit-ricents", "title": "남의집구경 일지 — 리센츠",
                      "summary": "유랑 계정의 단지 구경기", "category": "생활", "heat": 4},
    "rent-monthly": {"external_id": "wb-topic-2026-11-rent-monthly", "title": "달마다 보는 전월세 신고",
                     "summary": "국토부 전월세 실거래 신고를 계약일 기준으로 달마다 센다. 보증금·월세는 쓰지 않는다",
                     "category": "전월세", "heat": 3},
}


def build(d):
    today = date.fromisoformat(d)
    x = DAYS[d](today)
    bundles = []
    for po in x["posts"]:
        body = "\n\n".join(po["body"])
        bundles.append({
            "idempotency_key": f"wb-bundle-{po['ext']}-v1",
            "_series": po["series"],
            "payload": {
                "complex_external_id": CX[po["home"]], "topic": TOPICS[po["topic"]],
                "post": {
                    "external_id": po["ext"], "complex_external_id": CX[po["home"]],
                    "persona_external_id": po["persona"], "category": po["category"],
                    "title": po["title"], "summary": po.get("summary", po["body"][0])[:220], "body": body,
                    "verification": po["verification"], "source_note": po["source_note"], "sources": po["sources"],
                    "published_at": f"{d}T{po['slot']}:00+09:00", "status": "published",
                },
                "comments": [{"external_id": f"{po['ext']}-c{i}", "persona_external_id": pid, "body": b,
                              "stance": st, "position": i} for i, (pid, b, st) in enumerate(po["comments"])],
            },
        })
    comments = [{"external_id": c["ext"], "post_external_id": c["post_external_id"],
                 "persona_external_id": c["persona"], "body": c["body"], "stance": c["stance"],
                 "position": c["position"]} for c in x.get("comments", [])]
    return {"meta": {"name": f"하루치 글 {d}", "style": "docs/writing-style.md", "built_at": datetime.now(KST).isoformat()},
            "personas": [], "bundles": bundles, "comments": comments}


def validate(pack, d):
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    registered = {v["external_id"] for v in json.loads((REPO / "data" / "personas.json").read_text(encoding="utf-8"))["personas"]}
    ids = [x["external_id"] for x in posts] + [c["external_id"] for b in pack["bundles"] for c in b["payload"]["comments"]] \
        + [c["external_id"] for c in pack["comments"]]
    if len(ids) != len(set(ids)):
        errs.append("external_id 중복")
    if len({x["published_at"] for x in posts}) != len(posts):
        errs.append("published_at 중복")
    transitions, dotted, series_cx = [], 0, {}
    per_cx = {}
    for b in pack["bundles"]:
        x = b["payload"]["post"]
        cm = [c["body"] for c in b["payload"]["comments"]]
        body, title = x["body"], x["title"]
        text = "\n".join([title, body] + cm)
        tag = x["external_id"]
        if x["published_at"][:10] != d:
            errs.append(f"{tag}: 날짜가 {d} 가 아님")
        for m in B.DATE_IN_TEXT.finditer(text):
            if f"2026-{int(m.group(1)):02d}-{int(m.group(2)):02d}" > d:
                errs.append(f"{tag}: 글 날짜 이후 날짜 '{m.group()}'")
        hits = [w for ws in BANNED.values() for w in ws if w in text] + [w for w in B.BAN_STEER + B.BAN_VAGUE if w in text]
        if hits:
            errs.append(f"{tag}: 금지 표현 {hits}")
        if OWN_HOME.search(text) or EXPERIENCE_TONE.search(text):
            errs.append(f"{tag}: 경험 어투")
        if RELATIVE_TIME.search(text):
            errs.append(f"{tag}: 시점 의존 표현 '{RELATIVE_TIME.search(text).group()}'")
        je = josa_errors(text) + [m.group() for m in B.BAD_PCT_JOSA.finditer(text)]
        if je:
            errs.append(f"{tag}: 조사 {je[:3]}")
        if "**" in text:
            errs.append(f"{tag}: 마크다운")
        if len(title) > B.MAX_TITLE:
            errs.append(f"{tag}: 제목 {len(title)}자")
        last = body.rstrip().split("\n\n")[-1]
        if not body.rstrip().endswith("?") or last.count("?") != 1:
            errs.append(f"{tag}: 질문 하나로 닫지 않음")
        if x["verification"] == "verified":
            if not x["sources"]:
                errs.append(f"{tag}: verified 인데 출처 없음")
            if not TRANSITION.search(body):
                errs.append(f"{tag}: 사실/해석 전환 없음")
        if x["persona_external_id"].startswith("adv-") and BAN_PRICE.search(text):
            errs.append(f"{tag}: 홍보 페르소나 가격 어휘 '{BAN_PRICE.search(text).group()}'")
        mr = mono_run(body)
        if mr >= STYLE_MONO:
            errs.append(f"{tag}: '~니다.' {mr}연속")
        for k, v in style_issues(title, body, cm):
            errs.append(f"{tag}: {k} {v}")
        tr = [s for s in sentences(body) if TRANSITION.search(s)]
        transitions += tr[:1]
        dotted += bool(re.search(r"\.\s", title))
        if x["persona_external_id"] not in registered:
            errs.append(f"{tag}: 미등록 페르소나")
        if len(cm) < 2:
            errs.append(f"{tag}: 관점 댓글 {len(cm)}개")
        for c in b["payload"]["comments"]:
            if c["persona_external_id"] not in registered or c["persona_external_id"] == x["persona_external_id"]:
                errs.append(f"{tag}: 댓글 페르소나 {c['external_id']}")
            if AI_COMMENT_ASK.search(c["body"]):
                errs.append(f"{tag}: 댓글 행동 요청 {c['external_id']}")
        s = b["_series"]
        series_cx.setdefault(s, set()).add(x["complex_external_id"])
        per_cx[x["complex_external_id"]] = per_cx.get(x["complex_external_id"], 0) + 1
    if len(transitions) != len(set(transitions)):
        errs.append("배치 안에 같은 전환 문장")
    if dotted > 1:
        errs.append(f"마침표로 두 토막 낸 제목 {dotted}편")
    for s, cxs in series_cx.items():
        if len(cxs) > 1:
            errs.append(f"같은 날 같은 계열 {s} 이 {len(cxs)}개 단지에")
    for c in pack["comments"]:
        if AI_COMMENT_ASK.search(c["body"]) or c["persona_external_id"] not in registered:
            errs.append(f"댓글 {c['external_id']}")
        for k, v in style_issues("", "", [c["body"]]):
            errs.append(f"댓글 {c['external_id']}: {k} {v}")
    # 서모스탯: 게시된 피드와 합친다. 이미 게시된 이 팩의 글은 빼고 센다(재생성)
    slug = {v: k for k, v in CX.items()}
    mine = {x["external_id"] for x in posts}
    for cx, n in per_cx.items():
        try:
            items = live(slug[cx])
        except Exception as exc:  # noqa: BLE001
            errs.append(f"{cx}: 피드 조회 실패 {exc}")
            continue
        already = sum(1 for e, i in items.items() if B.kst_day(i.get("published_at")) == d and e not in mine)
        if already + n > 2:
            errs.append(f"{cx}: {d} 게시분 {already} + 이 팩 {n} > 콜드스타트 2")
    return errs


def main():
    ap = argparse.ArgumentParser(description="하루치 글")
    ap.add_argument("--day", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()
    pack = build(args.day)
    errs = validate(pack, args.day)
    for b in pack["bundles"]:
        x = b["payload"]["post"]
        print(f"  {x['published_at'][11:16]}  {x['complex_external_id']:24}{x['persona_external_id']:24}{len(x['title']):>2}자  {x['title']}")
    for c in pack["comments"]:
        print(f"  댓글  → {c['post_external_id']}  {c['persona_external_id']}")
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    for b in pack["bundles"]:
        b.pop("_series")
    out = REPO / "content" / f"daily-{args.day}.json"
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"자체 검증 통과 → {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
