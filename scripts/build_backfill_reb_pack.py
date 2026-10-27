#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""소급 기록 팩 — 한국부동산원 주간 아파트가격 동향, 발표일 기준 12편.

왜 소급인가 (2026-10-26 운영자 결정 "소급기록으로 가자")
  9/28~10/25 게시가 끊겼다. 그 사이 부동산원은 주간 동향을 네 번 냈다(10/1·8·15·22).
  보도자료는 발표 뒤에 고치지 않는 고정 문서라, 그날 공개된 자료만으로 그날 글을 쓸 수 있다.
  CLAUDE.md 39번은 "소급 게시하지 않는다"였고, 이 팩은 아래 조건을 걸고 그 원칙을 좁힌다.

소급 조건 — 하나라도 어기면 validate() 가 반려한다
  · 글이 인용하는 발표는 전부 글 날짜 이전(같은 날 포함)에 공개된 것이다. AsOf 가 막는다
  · 게시 시각은 인용한 발표의 보도 시각(목 14:00) 이후다
  · 본문·제목·댓글에 글 날짜보다 뒤의 'M월 D일'이 나오지 않는다
  · 나중에 고쳐지는 자료(실거래 등)는 쓰지 않는다. 부동산원 표만 쓴다.
    네 발표의 6주 창이 겹치는 1,440칸에서 앞 발표 값이 뒤에서 바뀐 경우는 0건이었다
  · 수집일을 숨기지 않는다. '확인 기준'(source_note)에 "2026. 10. 26. 수집, 발표일 기준으로 기록"을 쓴다.
    본문 말미 고지는 명세 7.2.2가 금지하므로 본문에는 넣지 않는다
  · 서모스탯은 소급한 그날 기준으로 센다. 하루 3편, 단지당 1편이다

구 지수는 단지 값이 아니다
  보도자료는 구 단위 숫자와 동 이름까지만 적는다. 단지 이름은 네 건 어디에도 없다.
  그래서 모든 글에 "한 단지"의 값이 아니라는 문장을 넣고(`NEED`), 단지가 있는 동이
  해설에 나왔는지 안 나왔는지를 원문으로 확인해 적는다. '북아현동'은 '아현동'이 아니다.

본문에 쓰는 주장은 전부 이 파일에서 계산하고 assert 로 확인한다. 손으로 옮겨 적지 않는다.

실행: python3 scripts/build_backfill_reb_pack.py
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_audit import (AI_COMMENT_ASK, BANNED, EXPERIENCE_TONE, MONO_RUN, OWN_HOME,  # noqa: E402
                           RELATIVE_TIME, TRANSITION, josa_errors, mono_run)

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data" / "reb-weekly" / "seoul-gu-2026-10.json"
OUT = REPO / "content" / "backfill-reb-w1.json"
FEED_BASE = os.environ.get("BASE_URL", "https://danji.life")

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")
COLLECTED = "2026. 10. 26."     # 원문 수집·대조일. 출처 라벨의 '확인'과 같다
SLOTS = ("15:00", "15:40", "16:20")   # 보도 시각 14:00 이후

CX = {
    "one-bailey": ("cx-one-bailey", "래미안 원베일리"),
    "helio-city": ("cx-helio-city", "헬리오시티"),
    "ricents": ("cx-ricents", "리센츠"),
    "godeok-gracium": ("cx-godeok-gracium", "고덕그라시움"),
    "eunma": ("cx-eunma", "은마아파트"),
    "mapo-raemian-prugio": ("cx-mapo-raemian-prugio", "마포래미안푸르지오"),
}

TOPIC = {"external_id": "wb-topic-2026-10-reb-weekly", "title": "주간 지수를 발표일 그대로 기록한다",
         "summary": ("한국부동산원 주간 아파트가격 동향을 발표일 기준으로 옮긴다. 구 단위 숫자라 단지 값이 아니며, "
                     "자료가 단지에 대해 말하지 않는 부분은 그렇다고 적는다"),
         "category": "거래", "heat": 4}

# 가격 지수를 다루므로 분석 페르소나만 쓴다. 휴면 3명(역발상·절세·학군)은 깨우지 않는다
ANALYSTS = {"wb-persona-trade-brief", "wb-persona-demand-check", "wb-persona-psy-thermo",
            "wb-persona-num-compare", "wb-persona-policy-lab", "wb-persona-real-talk",
            "wb-persona-field-scout", "wb-persona-question-post", "wb-persona-cashflow"}

BAN_STEER = ["얼마 이하로", "내놓지 마", "지금 사", "지금 파", "매수 추천", "매도 추천", "사야 합니다",
             "팔아야 합니다", "오를 겁니다", "내릴 겁니다", "전망합니다", "저평가", "고평가", "바닥",
             "반등할", "지금이 기회", "호가를 지켜"]
BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "뒤처", "명문", "상위권", "학군", "가장 좋", "최고의"]
BAN_COMPARE = ["보다 낫", "보다 좋", "보다 우수", "보다 편리"]
BAN_VAGUE = ["인터넷에서", "알려져 있", "라고 한다", "다고 한다", "찾아보니", "카더라", "커뮤니티에서"]
NEED = ["여기서부터는 해석입니다", "한 단지"]
DATE_IN_TEXT = re.compile(r"(\d{1,2})월 (\d{1,2})일")
# '%'는 '퍼센트'로 읽으니 받침이 없다. '-0.21%이'·'0.33%을'은 틀린 조사다('%이고'는 맞다)
BAD_PCT_JOSA = re.compile(r"%(이|을|은|과|으로)(?![가-힣])")
MAX_TITLE = 34


class AsOfError(AssertionError):
    pass


def load():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    return {r["published"]: r for r in d["releases"]}


REL = load()
# 해설 문단에 단지 이름은 없다. 이 전제가 깨지면 글 12편의 문장이 틀린다
for _r in REL.values():
    for _k in ("sale", "jeonse"):
        for _t in _r["commentary"][_k].values():
            assert not any(n in _t for n in ("원베일리", "은마", "헬리오", "리센츠", "그라시움", "푸르지오")), _t


class AsOf:
    """글 날짜까지 공개된 발표만 꺼내 준다. 쓴 발표는 sources 로 그대로 넘어간다."""

    def __init__(self, day):
        self.day, self.used = day, set()

    def __call__(self, pub):
        if pub > self.day:
            raise AsOfError(f"{self.day} 글이 {pub} 발표를 인용하려 했다")
        self.used.add(pub)
        return REL[pub]


# ── 표기 ─────────────────────────────────────────────────────

def p(v):
    return f"{v:.2f}%"


def sp(v):
    return f"+{v:.2f}%" if v > 0 else p(v)


def md(s):
    """'9.28' 또는 '2026-10-01' → '9월 28일'."""
    if "-" in s:
        _, m, d = s.split("-")
    else:
        m, d = s.split(".")
    return f"{int(m)}월 {int(d)}일"


def seq(vals):
    return ", ".join(p(v) for v in vals)


KOR_ORD = {1: "첫", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉"}


def nth(n):
    return f"{KOR_ORD[n]} 번째" if n in KOR_ORD else f"{n}번째"


# ── 계산 ─────────────────────────────────────────────────────

def wk(r):
    return r["weeks"][-1]


def gu(r, g, kind, week=None):
    return r["gu"][g][kind]["weekly"][week or wk(r)]


def ytd(r, g, kind):
    return r["seoul"][kind]["ytd_2026"] if g == "서울" else r["gu"][g][kind]["ytd_2026"]


def ranked(r, kind, week=None, field="weekly"):
    """낮은 값부터. field='ytd' 면 올해 누계로 줄 세운다."""
    if field == "ytd":
        return sorted(r["gu"], key=lambda g: r["gu"][g][kind]["ytd_2026"])
    return sorted(r["gu"], key=lambda g: r["gu"][g][kind]["weekly"][week or wk(r)])


def weeks_upto(a, day, g, kind):
    """day 까지 공개된 발표들의 6주 창을 이어 붙인다. 겹치는 주는 값이 같아야 한다."""
    out = {}
    for pub in sorted(REL):
        if pub > day:
            continue
        r = a(pub)
        for w, v in r["gu"][g][kind]["weekly"].items():
            assert out.setdefault(w, v) == v, (g, kind, w)
    order = sorted(out, key=lambda w: tuple(int(x) for x in w.split(".")))
    return [(w, out[w]) for w in order]


def lowest_by_week(a, day, kind):
    seen = {}
    for pub in sorted(REL):
        if pub > day:
            continue
        r = a(pub)
        for w in r["weeks"]:
            seen[w] = min(r["gu"], key=lambda g: r["gu"][g][kind]["weekly"][w])
    return seen


def neg_count(a, day, kind, week):
    """그 주에 내린 구의 수. 그 주가 실린 발표 중 아무거나 쓴다(값은 발표 사이에 같다)."""
    for pub in sorted(REL):
        if pub <= day and week in REL[pub]["weeks"]:
            r = a(pub)
            return sum(1 for g in r["gu"] if gu(r, g, kind, week) < 0)
    raise KeyError(week)


def comm(r, kind, side):
    return r["commentary"][kind][side]


def quote(r, kind, side, g):
    """해설 문단에서 'X구(n%)는 … 위주로' 한 구절을 원문 그대로 뽑는다."""
    m = re.search(re.escape(g) + r"구\(-?\d+\.\d+%\)는 [^,]*?위주로", comm(r, kind, side))
    assert m, (r["published"], kind, g)
    return m.group()


def named(r, g):
    return any(re.search(re.escape(g) + r"구\(", t)
               for k in ("sale", "jeonse") for t in r["commentary"][k].values())


def dong_named(r, dong):
    """'아현'을 찾을 때 '북아현'은 빼야 한다. 다른 구의 동이다."""
    pat = r"(?<![가-힣])" + re.escape(dong) if dong != "아현" else r"(?<!북)아현"
    return any(re.search(pat, t) for k in ("sale", "jeonse") for t in r["commentary"][k].values())


# ── 글 12편 ──────────────────────────────────────────────────
# 하나의 뼈대를 단지에 돌려 쓰지 않는다. 같은 구(송파)를 두 단지가 나눠 쓰는 경우는
# 각도를 다르게 잡는다 — 리센츠는 해설이 꼽은 잠실동·누계 격차, 헬리오는 해설 공백·연속 하락.

def p_eunma_1001():
    day = "2026-10-01"
    a = AsOf(day)
    r = a(day)
    neg = [g for g in ranked(r, "sale") if gu(r, g, "sale") < 0]
    ytd_neg = [g for g in r["gu"] if ytd(r, g, "sale") < 0]
    assert neg[0] == "강남" and len(neg) == 4 and ytd_neg == ["강남"]
    q = quote(r, "sale", "gangnam11", "강남")
    assert "대치" in q
    body = f"""한국부동산원이 10월 1일 오후 2시 보도 시각으로 낸 주간 아파트가격 동향(9월 28일 기준)입니다. 서울 25개 구의 매매가격지수 변동률을 한 줄로 세우면 맨 끝에 강남구 {p(gu(r, '강남', 'sale'))}가 있습니다.

같은 주 서울 전체는 {p(r['seoul']['sale']['weekly'][wk(r)])} 올랐습니다. 25개 구 가운데 내린 곳은 {KOR_ORD[len(neg)]} 곳뿐이었고, 순서대로 {', '.join(f'{g}구 {p(gu(r, g, "sale"))}' for g in neg)}입니다.

올해 누계로 봐도 강남구는 표에서 유일한 마이너스예요. {p(ytd(r, '강남', 'sale'))}이고, 서울 전체 누계는 {p(ytd(r, '서울', 'sale'))}입니다.

보도자료 해설은 이 하락을 "{q}" 하락이라고 적었습니다. 은마아파트가 있는 곳이 대치동이죠. 다만 해설은 단지 이름을 쓰지 않습니다. 은마가 그 '주요 단지'에 들어가는지는 이 자료로 알 수 없습니다.

여기서부터는 해석입니다. 이 숫자는 구 단위 지수이고, 해설도 동 이름에서 멈춥니다. 그래서 강남구 {p(gu(r, '강남', 'sale'))}를 은마아파트 한 단지의 값으로 옮길 수는 없습니다. 이 글이 말할 수 있는 건 "은마가 속한 구가 9월 28일 기준 주에 서울에서 가장 많이 내렸다"까지입니다.

9월 마지막 주, 대치동 안에서 달라진 걸 느끼셨나요?"""
    return dict(slug="eunma", day=day, a=a, persona="wb-persona-trade-brief", category="거래",
                title=f"강남구 {p(gu(r, '강남', 'sale'))}, 서울 25개 구 중 가장 큰 하락", body=body,
                comments=[("wb-persona-psy-thermo", f"-0.56%만 떼어 읽으면 크게 들립니다. 같은 표에서 서울 전체는 {p(r['seoul']['sale']['weekly'][wk(r)])} 올랐다는 것도 같이 봐야 균형이 맞습니다.", "심리 균형"),
                          ("wb-persona-question-post", "해설이 '주요 단지'라고만 적은 부분은 이 자료로 더 풀리지 않습니다. 어느 단지를 가리키는지는 보도자료 어디에도 없습니다.", "확인 요청")])


def p_mapo_1001():
    day = "2026-10-01"
    a = AsOf(day)
    r = a(day)
    s = r["gu"]["마포"]["sale"]
    seoul_w, seoul_y = r["seoul"]["sale"]["weekly"][wk(r)], ytd(r, "서울", "sale")
    assert s["weekly"][wk(r)] < seoul_w and s["ytd_2026"] > seoul_y
    rank = sorted(r["gu"], key=lambda g: -ytd(r, g, "sale")).index("마포") + 1
    assert not named(r, "마포")
    up = [m.group(1) for m in re.finditer(r"(\S+?)구\((\d+\.\d+)%\)", comm(r, "sale", "gangbuk14"))]
    down = [m.group(1) for m in re.finditer(r"(\S+?)구\((-\d+\.\d+)%\)", comm(r, "sale", "gangbuk14"))]
    body = f"""같은 표에서 두 숫자를 나란히 놓아 봅니다. 한국부동산원 10월 1일 발표, 9월 28일 기준 마포구 아파트 매매가격지수입니다.

하나는 주간 변동률 {p(s['weekly'][wk(r)])}. 서울 전체({p(seoul_w)})보다 조금 낮습니다. 다른 하나는 올해 누계 {p(s['ytd_2026'])}. 이쪽은 서울 전체 누계({p(seoul_y)})보다 높습니다.

표에 실린 여섯 주(8월 24일~9월 28일 기준)를 차례로 적으면 {seq(s['weekly'].values())}입니다. 8월 말과 비교하면 한 주에 오르는 폭이 작아진 상태죠.

누계로 줄을 세우면 마포구는 25개 구 중 높은 쪽에서 {nth(rank)}예요. 강북 14개구 해설 문단에는 이 주 마포구 이름이 없습니다. 해설은 {'·'.join(up)}구의 상승과 {'·'.join(down)}구의 하락을 적었습니다.

여기서부터는 해석입니다. 주간 값은 그 일주일의 속도를, 누계는 1월부터 쌓인 거리를 보여 줍니다. 같은 구를 두고도 어느 숫자를 꺼내느냐에 따라 인상이 반대로 갈립니다. 그리고 둘 다 구 단위라 마포래미안푸르지오 한 단지의 값은 아닙니다.

단지 분위기에 더 가까운 건 어느 쪽인가요, {p(s['weekly'][wk(r)])}인가요 {p(s['ytd_2026'])}인가요?"""
    return dict(slug="mapo-raemian-prugio", day=day, a=a, persona="wb-persona-num-compare", category="거래",
                title=f"마포구 주간 {p(s['weekly'][wk(r)])}, 올해 누계는 {p(s['ytd_2026'])}", body=body,
                comments=[("wb-persona-trade-brief", "누계와 주간을 같이 놓으면 한쪽만 인용한 기사를 걸러 읽기 쉬워집니다. 같은 표 안에 둘 다 있으니까요.", "중립 리서치"),
                          ("wb-persona-field-scout", "아현동이 해설에 없던 주라도 현장 체감은 다를 수 있습니다. 공덕역 쪽과 아현역 쪽 분위기가 같았는지 궁금하네요.", "현장 검증 요청")])


def p_ricents_1001():
    day = "2026-10-01"
    a = AsOf(day)
    r = a(day)
    s, j = r["gu"]["송파"]["sale"]["weekly"], r["gu"]["송파"]["jeonse"]["weekly"]
    q = quote(r, "sale", "gangnam11", "송파")
    assert "잠실" in q and "송파구(" not in comm(r, "jeonse", "gangnam11")
    sv, jv = list(s.values()), list(j.values())
    falls = [v for v in sv if v < 0]
    assert sv[-len(falls):] == falls and all(v > 0 for v in jv)   # 마지막 n주 연속 하락, 전세는 6주 모두 상승
    first_fall = list(s)[len(sv) - len(falls)]
    body = f"""한국부동산원 10월 1일 발표 자료에서 송파구는 같은 주(9월 28일 기준)에 두 방향을 가리켰습니다. 매매가격지수 {p(sv[-1])}, 전세가격지수 {p(jv[-1])}.

매매 쪽 해설에는 "{q}" 하락이라는 문장이 있습니다. 리센츠가 있는 곳이 잠실동입니다. 전세 쪽 해설에는 송파구 이름이 나오지 않습니다.

갈라짐은 한 주의 일이 아니었어요. 표에 실린 여섯 주(8월 24일~9월 28일 기준) 동안 매매는 {seq(sv[:len(sv) - len(falls)])}로 오르다가 {md(first_fall)} 기준부터 {seq(falls)}로 {KOR_ORD[len(falls)]} 주 연속 내렸습니다. 전세는 같은 여섯 주에 {seq(jv)}로 한 번도 내리지 않았고요.

여기서부터는 해석입니다. 같은 구 안에서도 매매 수요와 임차 수요가 따로 움직이고 있다는 뜻입니다. 어느 쪽 숫자를 보느냐에 따라 '송파가 식었다'와 '송파가 오른다'가 둘 다 맞는 문장이 됩니다. 다만 해설이 잠실동을 꼽았어도 이건 송파구 전체 지수예요. 리센츠 한 단지의 거래를 가리키는 숫자는 아닙니다.

같은 주에 매매는 내리고 전세는 올랐습니다. 단지 안에서 느끼신 건 어느 쪽에 가까웠나요?"""
    return dict(slug="ricents", day=day, a=a, persona="wb-persona-real-talk", category="거래",
                title=f"송파구 매매 {p(sv[-1])}, 전세 {sp(jv[-1])}. 같은 주", body=body,
                comments=[("wb-persona-cashflow", "매매와 전세가 반대로 가면 집주인과 세입자가 같은 표를 보고 다른 결론을 내리기 쉽습니다. 두 줄을 같이 실어야 하는 이유죠.", "현금흐름 중심"),
                          ("wb-persona-num-compare", "같은 구, 같은 주, 같은 기관 자료라 기준이 맞습니다. 비교할 때 이 조건이 다 갖춰지는 경우가 생각보다 드뭅니다.", "기준 통일")])


def p_onebailey_1008():
    day = "2026-10-08"
    a = AsOf(day)
    r1, r = a("2026-10-01"), a(day)
    series = weeks_upto(a, day, "서초", "jeonse")
    low = lowest_by_week(a, day, "jeonse")
    assert len(series) == 7 and all(v < 0 for _, v in series)
    n_low = sum(1 for w, _ in series if low[w] == "서초")
    only = [w for w, _ in series if neg_count(a, day, "jeonse", w) == 1]
    assert ranked(r, "jeonse")[0] == "서초" and only == ["8.24", "9.28"]
    q1, q2 = quote(r1, "jeonse", "gangnam11", "서초"), quote(r, "jeonse", "gangnam11", "서초")
    assert "입주물량" in q1 and "입주물량" in q2 and "반포" in q1 and "반포" in q2
    body = f"""한국부동산원 10월 8일 발표(10월 5일 기준)에서 서초구 아파트 전세가격지수 변동률은 {p(series[-1][1])}입니다. 서울 25개 구 가운데 가장 많이 내렸습니다.

10월 1일 발표와 10월 8일 발표 표를 이어 붙이면 {md(series[0][0])}부터 {md(series[-1][0])}까지 {KOR_ORD[len(series)]} 주가 나옵니다. 서초구 전세는 그 {KOR_ORD[len(series)]} 주 내내 마이너스였어요. {seq(v for _, v in series)}. 이 가운데 {KOR_ORD[n_low]} 주는 서울에서 가장 낮은 값이었고, {'과 '.join(md(w) for w in only)} 기준 주에는 전세가 내린 구가 서초구 하나뿐이었습니다.

보도자료는 이유를 적어 두었습니다. 10월 1일 해설은 "{q1}" 하락, 10월 8일 해설은 "{q2}" 하락. 래미안 원베일리가 있는 동이 반포동입니다.

어느 단지의 입주를 말하는지는 보도자료에 없습니다. 저희도 확인하지 못했고, 짐작으로 단지 이름을 붙이지 않겠습니다.

여기서부터는 해석입니다. 전세 지수가 일곱 주 연속 내렸다면 같은 기간 서초구에서 전세를 구하거나 갱신하는 사람이 마주한 조건도 달라지고 있었을 수 있습니다. 다만 구 단위 지수라 원베일리 한 단지의 전세 값으로 읽을 수는 없습니다. 보도자료가 든 이유가 입주물량이라는 점도, 그게 어느 단지인지 모른다는 점도 같이 적어 둡니다.

9~10월 단지 안 이사 차량, 평소보다 많아 보였나요?"""
    return dict(slug="one-bailey", day=day, a=a, persona="wb-persona-cashflow", category="전월세",
                title=f"서초구 전세, 표에 실린 {len(series)}주 모두 하락", body=body,
                comments=[("wb-persona-question-post", "어느 단지 입주인지가 이 글의 빈칸입니다. 보도자료는 '입주물량 영향'이라고만 적고 단지도 시기도 밝히지 않았습니다.", "확인 요청"),
                          ("wb-persona-real-talk", "지수가 일곱 주 내렸어도 갱신하는 집마다 조건은 제각각입니다. 구 숫자는 방향까지만 알려 줍니다.", "생활 현실")])


def p_helio_1008():
    day = "2026-10-08"
    a = AsOf(day)
    r1, r = a("2026-10-01"), a(day)
    v = gu(r, "송파", "sale")
    order = ranked(r, "sale")
    pos = order.index("송파") + 1
    falls_named = re.findall(r"(\S+?)구\((-\d+\.\d+)%\)", comm(r, "sale", "gangnam11"))
    rises_named = re.findall(r"(\S+?)구\((\d+\.\d+)%\)", comm(r, "sale", "gangnam11"))
    assert pos == 3 and not named(r, "송파") and [g for g, _ in falls_named] == order[:2]
    q1 = quote(r1, "sale", "gangnam11", "송파")
    assert not dong_named(r1, "가락") and not dong_named(r, "가락")
    wv = list(r["gu"]["송파"]["sale"]["weekly"].values())
    n_fall = sum(1 for x in wv if x < 0)
    body = f"""한국부동산원 10월 8일 발표, 10월 5일 기준 송파구 아파트 매매가격지수 변동률은 {p(v)}입니다. 서울 25개 구 가운데 {nth(pos)}로 많이 내렸습니다.

그런데 보도자료 해설 문단에는 송파구가 나오지 않습니다. 강남 11개구 해설이 이름을 적은 곳은 다섯입니다. 내린 쪽으로 {'와 '.join(f'{g}구({x}%)' for g, x in falls_named)}, 오른 쪽으로 {'·'.join(g for g, _ in rises_named)}구. 내린 쪽을 둘만 적었으니 세 번째였던 송파구는 해설 밖에 남은 셈입니다.

한 주 전 10월 1일 해설에는 "{q1}" 하락이라는 문장이 있었습니다. 두 발표를 합쳐도 헬리오시티가 있는 가락동은 한 번도 나오지 않습니다.

숫자는 표에 그대로 있어요. 10월 8일 발표 표의 여섯 주(8월 31일~10월 5일 기준)는 {seq(wv)}. 여섯 주 중 {KOR_ORD[n_fall]} 주가 하락입니다.

여기서부터는 해석입니다. 해설에 이름이 없다고 움직임이 없었던 건 아닙니다. 해설은 표의 일부만 문장으로 옮긴 요약이고, 어느 동이 송파구 숫자를 끌었는지는 이 자료가 말해 주지 않습니다. 구 지수라 헬리오시티 한 단지의 값도 아니고요. 자료가 멈춘 자리는 주민분들께 여쭙는 수밖에 없습니다.

가락동은 해설에 없었습니다. 9~10월 헬리오시티 안의 분위기, 한 줄로 남겨 주실 수 있나요?"""
    return dict(slug="helio-city", day=day, a=a, persona="wb-persona-question-post", category="거래",
                title=f"송파구 {p(v)}, 해설 문단에는 이름이 없다", body=body,
                comments=[("wb-persona-trade-brief", f"{p(v)}가 9월 28일 기준과 10월 5일 기준에 같은 값으로 두 번 나왔다는 것도 표에서 함께 읽힙니다.", "중립 리서치"),
                          ("wb-persona-field-scout", "해설이 동을 고르는 기준은 보도자료에 적혀 있지 않습니다. 가락동이 빠진 이유를 이 자료에서 찾을 수는 없습니다.", "현장 검증 요청")])


def p_gracium_1008():
    day = "2026-10-08"
    a = AsOf(day)
    r = a(day)
    grp = r["groups"]["동남권"]["sale"]["weekly"]
    members = ["서초", "강남", "송파", "강동"]
    gd = r["gu"]["강동"]["sale"]["weekly"]
    pos = [g for g in members if gu(r, g, "sale") > 0]
    assert pos == ["강동"] and grp[wk(r)] < 0
    assert all(x < 0 for x in grp.values()) and all(x > 0 for x in gd.values())
    body = f"""한국부동산원 10월 8일 발표 표에는 '동남권'이라는 줄이 있습니다. 그 아래 서초·강남·송파·강동 네 구가 묶여 있어요. 10월 5일 기준 동남권 매매가격지수 변동률은 {p(grp[wk(r)])}였습니다.

네 구를 하나씩 풀면 {', '.join(f'{g}구 {p(gu(r, g, "sale"))}' for g in members)}. 권역 숫자는 마이너스인데 강동구만 플러스예요.

한 주만 그랬던 것도 아니고요. 표에 실린 여섯 주(8월 31일~10월 5일 기준) 동안 동남권은 {seq(grp.values())}로 매주 내렸고, 강동구는 {seq(gd.values())}로 매주 올랐습니다.

올해 누계는 강동구 {p(ytd(r, '강동', 'sale'))}, 서울 전체 {p(ytd(r, '서울', 'sale'))}.

여기서부터는 해석입니다. '동남권 하락'이라는 한 줄만 보면 고덕동도 같은 방향이라고 읽기 쉽습니다. 권역 평균은 그렇게 안쪽의 차이를 지웁니다. 거꾸로 강동구 {p(gu(r, '강동', 'sale'))}도 구 전체의 값일 뿐, 고덕그라시움 한 단지의 값은 아닙니다. 숫자를 한 단계씩 내려가며 읽어야 쏠리지 않습니다.

뉴스에서 '동남권'이라고 할 때, 고덕동도 거기 들어간다고 생각해 보신 적 있나요?"""
    return dict(slug="godeok-gracium", day=day, a=a, persona="wb-persona-psy-thermo", category="거래",
                title=f"동남권 {p(grp[wk(r)])}, 그 안에서 강동구만 {sp(gd[wk(r)])}", body=body,
                comments=[("wb-persona-num-compare", "권역 값과 구 값을 한 표에서 바로 맞대 볼 수 있다는 게 이 자료의 장점입니다. 평균 하나로 끝내지 않으면 됩니다.", "기준 통일"),
                          ("wb-persona-demand-check", f"여섯 주 내내 플러스였지만 폭은 {p(list(gd.values())[0])}에서 {p(min(gd.values()))}까지 작아졌다가 {p(gd[wk(r)])}가 됐습니다. 방향과 속도는 따로 봐야 합니다.", "데이터 상방")])


def p_eunma_1015():
    day = "2026-10-15"
    a = AsOf(day)
    rs = [a(x) for x in ("2026-10-01", "2026-10-08", day)]
    r = rs[-1]
    path = [(x["published"], wk(x), ytd(x, "강남", "sale")) for x in rs]
    assert ranked(r, "sale")[0] == "강남" and [g for g in r["gu"] if ytd(r, g, "sale") < 0] == ["강남"]
    qs = [quote(x, "sale", "gangnam11", "강남") for x in rs]
    assert "대치" in qs[0] and "대치" in qs[1] and "대치" not in qs[2]
    lines = "\n".join(f"{md(pub)} 발표({md(w)} 기준) {p(y)}" for pub, w, y in path)
    body = f"""한국부동산원 주간 아파트가격 동향에서 강남구의 올해 누계 매매 변동률을 발표 순서대로 옮깁니다.

{lines}

두 주 사이 주간 값은 {p(gu(rs[1], '강남', 'sale'))}, {p(gu(r, '강남', 'sale'))}였습니다. 10월 12일 기준으로도 강남구는 서울 25개 구 가운데 가장 많이 내린 구이고, 올해 누계가 마이너스인 구도 강남구 하나입니다.

해설 문단의 동 이름은 바뀌었습니다. 10월 1일 "{qs[0]}", 10월 8일 "{qs[1]}", 10월 15일 "{qs[2]}". 은마아파트가 있는 대치동이 10월 15일 해설에서는 빠졌습니다.

여기서부터는 해석입니다. 해설에서 빠졌다고 대치동이 움직이지 않았다는 뜻은 아닙니다. 보도자료는 강남구 해설에 동을 두 곳씩만 적었고, 왜 그 두 곳인지는 설명하지 않습니다. 단지 이름은 세 번 모두 없었고요. 그러니 구 누계가 은마아파트 한 단지의 흐름이라고 말할 근거도 이 자료에는 없습니다. 대치동 안의 사정은 현장이 더 잘 압니다.

대치동이 해설에서 빠진 10월 둘째 주, 단지 주변에서 보신 분위기는 어땠나요?"""
    return dict(slug="eunma", day=day, a=a, persona="wb-persona-field-scout", category="거래",
                title=f"강남구 올해 누계, 2주 사이 {p(path[0][2])}→{p(path[-1][2])}", body=body,
                comments=[("wb-persona-psy-thermo", f"누계가 깊어질수록 숫자 하나에 감정이 실리기 쉽습니다. 주간 값이 {p(gu(rs[0], '강남', 'sale'))}에서 {p(gu(rs[1], '강남', 'sale'))}, {p(gu(r, '강남', 'sale'))}로 움직인 것도 같이 보면 좋겠습니다.", "심리 균형"),
                          ("wb-persona-policy-lab", "해설은 매주 새로 쓰는 요약문이라, 동 이름이 빠지고 들어가는 걸 정책 변화와 바로 잇기는 어렵습니다.", "정책 분석")])


def p_mapo_1015():
    day = "2026-10-15"
    a = AsOf(day)
    r1, r2, r = a("2026-10-01"), a("2026-10-08"), a(day)
    j = r["gu"]["마포"]["jeonse"]["weekly"]
    jv = list(j.values())
    q = quote(r, "jeonse", "gangbuk14", "마포")
    picks = re.findall(r"(\S+?)구\(\d+\.\d+%\)", comm(r, "jeonse", "gangbuk14"))
    assert "마포" in picks and len(picks) == 5 and not named(r1, "마포") and not named(r2, "마포")
    assert not any(dong_named(x, "아현") for x in (r1, r2, r))
    k = jv.index(min(jv))
    rising = jv[k:]
    assert all(b > a_ for a_, b in zip(rising, rising[1:])) and len(rising) - 1 == 4
    body = f"""한국부동산원 10월 15일 발표, 10월 12일 기준 마포구 아파트 전세가격지수 변동률은 {p(jv[-1])}입니다. 서울 전체는 {p(r['seoul']['jeonse']['weekly'][wk(r)])}였습니다.

이 주 강북 14개구 전세 해설에는 다섯 개 구가 나옵니다. {'·'.join(g for g in picks if g != '마포')}구, 그리고 "{q}" 상승. 10월 1일과 10월 8일 해설에는 없던 이름입니다.

표에 실린 여섯 주(9월 7일~10월 12일 기준)로 보면 마포구 전세는 {seq(jv)}입니다. {md(list(j)[k])} 기준 {p(jv[k])}에서 네 주 연속 오름폭이 커졌어요.

다만 올해 누계는 {p(ytd(r, '마포', 'jeonse'))}로 서울 전체({p(ytd(r, '서울', 'jeonse'))})보다 낮습니다. 같은 표의 마포구 매매 누계는 {p(ytd(r, '마포', 'sale'))}입니다.

여기서부터는 해석입니다. 해설이 꼽은 동은 공덕·창전동이고, 마포래미안푸르지오가 있는 아현동은 세 번의 해설 어디에도 나오지 않습니다. 구 숫자가 커졌다고 아현동이 같은 속도였다고 말할 수는 없습니다. 주간 오름폭이 커진 것과 누계가 서울보다 낮은 것, 두 사실이 같이 있다는 것까지가 이 표의 내용입니다. 구 단위라 이 숫자는 한 단지의 값이 아닙니다.

아현동 쪽 전세 문의, 9월보다 늘었다고 느끼시나요?"""
    return dict(slug="mapo-raemian-prugio", day=day, a=a, persona="wb-persona-demand-check", category="전월세",
                title=f"마포구 전세 {p(jv[-1])}, 해설에 이름이 올랐다", body=body,
                comments=[("wb-persona-cashflow", "전세 오름폭이 커지는 구간에서는 갱신 시점이 몇 주만 달라도 체감이 다를 수 있습니다. 같은 구 안에서도요.", "현금흐름 중심"),
                          ("wb-persona-num-compare", f"마포구는 매매 누계 {p(ytd(r, '마포', 'sale'))}, 전세 누계 {p(ytd(r, '마포', 'jeonse'))}로 매매 쪽이 앞서 있습니다. 같은 날 송파구는 반대 모양이었습니다.", "기준 통일")])


def p_ricents_1015():
    day = "2026-10-15"
    a = AsOf(day)
    r1, r = a("2026-10-01"), a(day)
    js, ss = ytd(r, "송파", "jeonse"), ytd(r, "송파", "sale")
    hi_j = sorted(r["gu"], key=lambda g: -ytd(r, g, "jeonse")).index("송파") + 1
    lo_s = sorted(r["gu"], key=lambda g: ytd(r, g, "sale")).index("송파") + 1
    gaps = sorted(r["gu"], key=lambda g: -(ytd(r, g, "jeonse") - ytd(r, g, "sale")))
    assert gaps[0] == "송파" and js > 2 * ss and hi_j == 6 and lo_s == 4
    gap = js - ss
    body = f"""한국부동산원 10월 15일 발표(10월 12일 기준) 표의 올해 누계 칸에서 송파구 두 줄을 꺼냅니다. 전세가격지수 {p(js)}, 매매가격지수 {p(ss)}.

서울 전체는 두 줄이 거의 같습니다. 전세 {p(ytd(r, '서울', 'jeonse'))}, 매매 {p(ytd(r, '서울', 'sale'))}. 송파구에서는 전세 누계가 매매 누계의 두 배를 넘어요.

25개 구 안에서 서 있는 자리도 다릅니다. 전세 누계는 높은 쪽에서 {nth(hi_j)}, 매매 누계는 낮은 쪽에서 {nth(lo_s)}입니다. 두 누계의 차이 {gap:.2f}%포인트는 25개 구 가운데 가장 큽니다.

주간 값도 갈라져 있습니다. 10월 12일 기준 매매 {p(gu(r, '송파', 'sale'))}, 전세 {p(gu(r, '송파', 'jeonse'))}. 2주 전 10월 1일 발표 때는 매매 누계 {p(ytd(r1, '송파', 'sale'))}, 전세 누계 {p(ytd(r1, '송파', 'jeonse'))}였습니다.

여기서부터는 해석입니다. 이 격차가 무엇 때문인지는 지수만으로 정할 수 없습니다. 보도자료도 이유를 적지 않았습니다. 확실한 건 송파구에서 '올해 얼마나 올랐나'를 물으면 매매로 답하느냐 전세로 답하느냐에 따라 숫자가 두 배 넘게 달라진다는 점입니다. 그리고 이건 구 단위라, 리센츠 한 단지의 누계는 아닙니다.

리센츠 안에서는 올해 매매와 전세 중 어느 쪽 변화가 더 크게 느껴졌나요?"""
    return dict(slug="ricents", day=day, a=a, persona="wb-persona-num-compare", category="거래",
                title=f"송파구 누계, 전세 {p(js)}와 매매 {p(ss)}", body=body,
                comments=[("wb-persona-real-talk", "누계가 두 배 차이 난다고 생활이 두 배 달라지는 건 아니죠. 다만 이사를 앞둔 집이라면 어느 줄을 볼지부터 달라집니다.", "생활 현실"),
                          ("wb-persona-psy-thermo", "매매 지수가 주춤한 사이 전세 지수가 계속 오른 모양이라, 같은 구 안에서도 사람마다 정반대 분위기를 말할 수 있겠습니다.", "심리 균형")])


def p_onebailey_1022():
    day = "2026-10-22"
    a = AsOf(day)
    rs = [a(x) for x in sorted(REL)]
    r = rs[-1]
    low = lowest_by_week(a, day, "sale")
    weeks = sorted(low, key=lambda w: tuple(int(x) for x in w.split(".")))
    assert low[weeks[-1]] == "서초" and all(low[w] == "강남" for w in weeks[:-1])
    se, ga = gu(r, "서초", "sale"), gu(r, "강남", "sale")
    qs = [quote(x, "sale", "gangnam11", "서초") for x in rs]
    with_banpo = [x["published"] for x, q in zip(rs, qs) if "반포" in q]
    assert with_banpo == [x["published"] for x in rs[:-1]] and "반포" not in qs[-1]
    body = f"""한국부동산원 10월 22일 발표, 10월 19일 기준 서울 매매가격지수 변동률에서 가장 많이 내린 구는 서초구({p(se)})입니다. 강남구는 {p(ga)}였습니다.

차이는 {abs(se - ga):.2f}%포인트예요. 작지만 순서가 바뀐 건 기록해 둘 만합니다. 10월 1일부터 22일까지 네 번의 발표 표에 실린 주는 {md(weeks[0])}부터 {md(weeks[-1])}까지 {KOR_ORD[len(weeks)]} 주인데, 앞의 {KOR_ORD[len(weeks) - 1]} 주는 모두 강남구가 서울에서 가장 많이 내렸습니다.

서초구 매매 해설도 달라졌습니다. 10월 1일 "{qs[0]}", 10월 8일 "{qs[1]}", 10월 15일 "{qs[2]}". 10월 22일에는 "{qs[3]}"입니다. 래미안 원베일리가 있는 반포동이 네 번 중 처음으로 빠졌습니다.

같은 기간 서초구 올해 누계는 {p(ytd(rs[0], '서초', 'sale'))}(10월 1일 발표)에서 {p(ytd(r, '서초', 'sale'))}(10월 22일 발표)로 줄었습니다.

여기서부터는 해석입니다. {abs(se - ga):.2f}%포인트로 뒤바뀐 순서는 신호라기보다 기록입니다. 두 구가 비슷한 폭으로 나란히 내리고 있다는 쪽이 더 중요한 사실이죠. 해설에서 반포동이 빠진 이유는 보도자료가 설명하지 않습니다. 네 번의 발표 어디에도 단지 이름은 없었고, 그래서 서초구 숫자를 원베일리 한 단지의 값으로 읽을 수는 없습니다.

반포동 이름이 해설에서 빠진 10월 셋째 주, 단지 안 분위기도 달랐나요?"""
    return dict(slug="one-bailey", day=day, a=a, persona="wb-persona-trade-brief", category="거래",
                title=f"서초 {p(se)}·강남 {p(ga)}, {len(weeks)}주 중 처음 바뀐 순서", body=body,
                comments=[("wb-persona-psy-thermo", f"1등, 2등으로 부르기엔 {abs(se - ga):.2f}%포인트는 너무 작은 차이입니다. 순서보다 두 구가 나란히 내리고 있다는 쪽이 핵심이죠.", "심리 균형"),
                          ("wb-persona-field-scout", "서초동과 잠원동이 해설에 오른 주에 반포동 사정이 어땠는지는 표에 남지 않았습니다. 해설은 서초구에서 동을 두 곳씩만 꼽습니다.", "현장 검증 요청")])


def p_helio_1022():
    day = "2026-10-22"
    a = AsOf(day)
    rs = [a(x) for x in sorted(REL)]
    r = rs[-1]
    series = weeks_upto(a, day, "송파", "sale")
    tail = []
    for w, v in reversed(series):
        if v >= 0:
            break
        tail.insert(0, (w, v))
    mags = [abs(v) for _, v in tail]
    assert len(tail) == 7 and all(b >= a_ for a_, b in zip(mags[:-1], mags[1:-1])) and mags[-1] < mags[-2]
    assert mags[-2] == max(mags)
    assert not any(dong_named(x, "가락") for x in rs)
    songpa_named = [x["published"] for x in rs if named(x, "송파")]
    assert songpa_named == ["2026-10-01"] and "송파구(" not in comm(rs[0], "jeonse", "gangnam11")
    body = f"""한국부동산원 주간 아파트가격 동향 네 건(10월 1·8·15·22일 발표)의 표를 이어 붙이면, 송파구 아파트 매매가격지수는 {md(tail[0][0])} 기준부터 {md(tail[-1][0])} 기준까지 {KOR_ORD[len(tail)]} 주 연속 마이너스입니다.

{seq(v for _, v in tail)}.

앞의 {KOR_ORD[len(tail) - 1]} 주 동안 내림폭은 한 번도 줄지 않았습니다. 같거나 커졌죠. {md(tail[-2][0])} 기준 {p(tail[-2][1])}가 가장 컸고, {md(tail[-1][0])} 기준 {p(tail[-1][1])}에서 처음으로 폭이 줄었습니다.

올해 누계는 10월 1일 발표 {p(ytd(rs[0], '송파', 'sale'))}에서 10월 22일 발표 {p(ytd(r, '송파', 'sale'))}로 내려왔습니다. 누계는 아직 플러스 쪽이에요. 네 번의 해설 어디에도 헬리오시티가 있는 가락동 이름은 없었습니다.

여기서부터는 해석입니다. 한 주 폭이 줄었다고 흐름이 바뀌었다고 읽으면 성급합니다. 일곱 주 중 단 한 번의 변화이고, 표가 말하는 건 '덜 내렸다'까지입니다. 반대로 일곱 주 연속이라는 숫자에 겁부터 먹을 일도 아니고요. 둘 다 송파구 전체의 지수이고, 헬리오시티 한 단지의 값은 아니니까요.

이 일곱 주를 한 단어로 적는다면 어떤 말을 고르시겠어요?"""
    return dict(slug="helio-city", day=day, a=a, persona="wb-persona-psy-thermo", category="거래",
                title=f"송파구 {len(tail)}주 연속 하락, {md(tail[-1][0])} 기준 폭은 줄었다", body=body,
                comments=[("wb-persona-demand-check", f"{p(tail[-2][1])}에서 {p(tail[-1][1])}로 폭이 줄었지만 일곱 번째 마이너스라는 사실은 그대로입니다. 두 숫자를 함께 적어야 공정합니다.", "데이터 상방"),
                          ("wb-persona-question-post", f"가락동 이름이 네 번의 해설에 한 번도 나오지 않은 것도 기록해 둡니다. 송파구가 해설에 오른 건 {md(songpa_named[0])} 매매 해설 한 번이었습니다.", "확인 요청")])


def p_gracium_1022():
    day = "2026-10-22"
    a = AsOf(day)
    rs = [a(x) for x in sorted(REL)]
    r = rs[-1]
    j = r["gu"]["강동"]["jeonse"]["weekly"]
    jv = list(j.values())
    k = jv.index(max(jv))
    shrink = jv[k:]
    assert all(b < a_ for a_, b in zip(shrink, shrink[1:])) and len(shrink) - 1 == 4 and all(x > 0 for x in jv)
    q1 = quote(rs[0], "jeonse", "gangnam11", "강동")
    assert not any(named(x, "강동") for x in rs[1:]) and not any(dong_named(x, "고덕") for x in rs)
    sw = r["seoul"]["jeonse"]["weekly"][wk(r)]
    assert jv[-1] < sw / 2
    body = f"""한국부동산원 10월 22일 발표(10월 19일 기준) 강동구 아파트 전세가격지수 변동률은 {p(jv[-1])}입니다. 표에 실린 여섯 주(9월 14일~10월 19일 기준)를 차례로 놓으면 {seq(jv)}.

{md(list(j)[k])} 기준 {p(jv[k])}가 여섯 주 가운데 가장 컸고, 그 뒤 {KOR_ORD[len(shrink) - 1]} 주 연속 오름폭이 작아졌습니다. 그래도 여섯 주 모두 플러스입니다.

같은 주 서울 전체 전세는 {p(sw)}였습니다. 강동구 {p(jv[-1])}는 그 절반에 못 미칩니다. 올해 누계로는 강동구 {p(ytd(r, '강동', 'jeonse'))}, 서울 전체 {p(ytd(r, '서울', 'jeonse'))}로 강동구가 더 높고요.

10월 1일 발표 전세 해설에는 "{q1}" 상승이라는 문장이 있었습니다. 그 뒤 세 번의 해설에는 강동구가 나오지 않았고, 고덕그라시움이 있는 고덕동은 네 번 모두 나오지 않았습니다.

여기서부터는 해석입니다. 오름폭이 줄었다는 건 내렸다는 뜻이 아닙니다. 전세가 여전히 오르되 오르는 속도가 느려졌다는 것까지가 이 표의 내용이고, 그다음은 표가 말해 주지 않습니다. 같은 숫자라도 갱신 시점이 9월이었던 집과 10월 말인 집에는 다르게 닿을 수 있습니다. 구 단위 지수라 고덕그라시움 한 단지의 전세 값은 아닙니다.

올가을 전세 갱신을 앞둔 분, 단지 안에서 들리는 이야기가 9월과 달라졌나요?"""
    return dict(slug="godeok-gracium", day=day, a=a, persona="wb-persona-cashflow", category="전월세",
                title=f"강동구 전세 오름폭, {p(jv[k])}에서 {p(jv[-1])}까지", body=body,
                comments=[("wb-persona-real-talk", "오름폭이 줄어도 오르는 건 오르는 거라, 갱신하는 집 입장에서는 '덜 오른다'가 체감의 전부일 수 있습니다.", "생활 현실"),
                          ("wb-persona-trade-brief", f"같은 주 강동구 매매는 {p(gu(r, '강동', 'sale'))}였습니다. 매매와 전세가 둘 다 작은 폭으로 움직인 주였네요.", "중립 리서치")])


POSTS = [p_eunma_1001, p_mapo_1001, p_ricents_1001,
         p_onebailey_1008, p_helio_1008, p_gracium_1008,
         p_eunma_1015, p_mapo_1015, p_ricents_1015,
         p_onebailey_1022, p_helio_1022, p_gracium_1022]


# ── 조립 ─────────────────────────────────────────────────────

def kst_day(ts):
    """피드의 published_at 은 UTC('...Z')다. 서모스탯의 '하루'는 KST로 센다."""
    if not ts:
        return ""
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return t.astimezone(KST).strftime("%Y-%m-%d")


def published_today(feed_slug, day):
    try:
        req = urllib.request.Request(
            f"{FEED_BASE}/api/v1/posts?complex={urllib.parse.quote(feed_slug)}&limit=100",
            headers={"User-Agent": "danji-content-agent/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            items = json.load(r)["items"]
    except Exception as exc:  # noqa: BLE001
        print(f"  [주의] {feed_slug} 피드 조회 실패: {exc}", file=sys.stderr)
        return None
    return sum(1 for i in items if kst_day(i.get("published_at")) == day)


def source(rel):
    return {"label": (f"한국부동산원 주간 아파트가격 동향 {md(rel['published'])} 발표"
                      f"({md(rel['reference_date'])} 기준) (확인 {COLLECTED})"),
            "url": rel["source_url"], "publisher": "한국부동산원"}


def note(used):
    rels = [REL[x] for x in sorted(used)]
    pubs = "·".join(md(r["published"]) for r in rels)
    refs = (md(rels[0]["reference_date"]) if len(rels) == 1
            else f"{md(rels[0]['reference_date'])}~{md(rels[-1]['reference_date'])}")
    return (f"한국부동산원 주간 아파트가격 동향 {pubs} 발표분(조사 기준 {refs}) · 구 단위 지수이며 단지 값이 아닙니다 · "
            f"{COLLECTED} 수집, 발표일 기준으로 기록")


def build(ignore_cap):
    rows = [f() for f in POSTS]
    by_day = Counter()
    for r in rows:
        by_day[r["day"]] += 1
        r["published_at"] = f"{r['day']}T{SLOTS[by_day[r['day']] - 1]}:00+09:00"
        r["used"] = sorted(r.pop("a").used)

    per_day = Counter((r["slug"], r["day"]) for r in rows)
    for (slug, day), n in sorted(per_day.items()):
        live = published_today(slug, day)
        total = n if live is None else n + live
        if live is None or total > 2:
            msg = (f"{slug} {day}: 팩 {n}편 + 게시분 {live if live is not None else '?'}편 — "
                   "콜드스타트 2편 초과 또는 확인 불가")
            if ignore_cap:
                print(f"  [한도 초과] {msg} (--ignore-cap)", file=sys.stderr)
            else:
                print(f"  [반려] {msg}", file=sys.stderr)
                raise SystemExit(1)

    bundles = []
    for r in sorted(rows, key=lambda r: r["published_at"]):
        ext = f"reb-2026-10-{r['slug']}-{r['day'][5:7]}{r['day'][8:10]}"
        ext_id, _name = CX[r["slug"]]
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-v1",
            "payload": {
                "complex_external_id": ext_id, "topic": TOPIC,
                "post": {
                    "external_id": ext, "complex_external_id": ext_id,
                    "persona_external_id": r["persona"], "category": r["category"],
                    "title": r["title"], "summary": r["body"].split("\n\n")[0][:220],
                    "body": r["body"], "verification": "verified",
                    "source_note": note(r["used"]), "sources": [source(REL[x]) for x in r["used"]],
                    "published_at": r["published_at"], "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{n}", "persona_external_id": pid,
                     "body": b, "stance": st, "position": n}
                    for n, (pid, b, st) in enumerate(r["comments"])
                ],
            },
            "_asof": {"day": r["day"], "uses": r["used"]},
        })

    return {
        "meta": {"name": "소급 기록 — 부동산원 주간 동향 (w1)", "posts": len(bundles), "built_at": NOW[:10],
                 "per_complex": dict(Counter(r["slug"] for r in rows)),
                 "published_days": sorted(by_day),
                 "decision": ("2026-10-26 운영자 결정 '소급기록으로 가자'. 9/28~10/25 공백 중 부동산원 발표 4건을 "
                              "발표일 기준으로 기록한다. 발표일 이전 날짜로는 쓰지 않는다"),
                 "conditions": ["인용 발표 ≤ 글 날짜", "게시 시각 ≥ 보도 시각(목 14:00)",
                                "본문·댓글에 글 날짜 이후 날짜 없음", "고쳐지는 자료(실거래 등) 미사용",
                                "확인 기준에 수집일 공개", "서모스탯은 소급한 날 기준"],
                 "data": str(DATA.relative_to(REPO)),
                 "comments_time": ("서버는 댓글에 실제 적재 시각을 찍는다(8/12 팬 듀오 글에 8/16 댓글). "
                                   "그래서 댓글도 글 날짜까지의 자료만 말하게 했다"),
                 "note": "12편 전부 손글 뼈대. 송파구 두 단지는 각도를 나눴다(리센츠: 잠실동·누계 격차 / 헬리오: 해설 공백·연속 하락)"},
        "personas": [],
        "bundles": bundles,
    }


def validate(pack):
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    comments = [c for b in pack["bundles"] for c in b["payload"]["comments"]]
    registered = {p_["external_id"] for p_ in
                  json.loads((REPO / "data" / "personas.json").read_text(encoding="utf-8"))["personas"]}

    ids = [x["external_id"] for x in posts] + [c["external_id"] for c in comments]
    if len(set(ids)) != len(ids):
        errs.append("external_id 중복")
    for key in ("published_at", "title"):
        vals = [x[key] for x in posts]
        if len(set(vals)) != len(vals):
            errs.append(f"{key} 중복: {[k for k, n in Counter(vals).items() if n > 1][:3]}")
    order = [b["payload"]["complex_external_id"] for b in pack["bundles"]]
    for a_, b_ in zip(order, order[1:]):
        if a_ == b_:
            errs.append(f"같은 단지 글이 연달아 나간다: {a_}")

    banned = BAN_STEER + BAN_JUDGE + BAN_COMPARE + BAN_VAGUE + [w for ws in BANNED.values() for w in ws]
    for b in pack["bundles"]:
        x = b["payload"]["post"]
        asof = b["_asof"]
        cm = [c["body"] for c in b["payload"]["comments"]]
        text = "\n".join([x["title"], x["body"]] + cm)
        eid = x["external_id"]

        # 소급 조건
        for pub in asof["uses"]:
            if pub > asof["day"]:
                errs.append(f"발표 전 날짜에 인용: {eid} ← {pub}")
            if x["published_at"] < REL[pub]["embargo_kst"]:
                errs.append(f"보도 시각 전 게시: {eid} {x['published_at']} < {REL[pub]['embargo_kst']}")
        for m in DATE_IN_TEXT.finditer(text):
            if f"2026-{int(m.group(1)):02d}-{int(m.group(2)):02d}" > asof["day"]:
                errs.append(f"글 날짜 이후 날짜 언급 '{m.group()}': {eid}")
        if "발표일 기준으로 기록" not in x["source_note"] or "수집" not in x["source_note"]:
            errs.append(f"확인 기준에 수집일 공개 없음: {eid}")
        if not x["published_at"].startswith(asof["day"]):
            errs.append(f"게시일과 기준일 불일치: {eid}")

        for w in banned:
            if w in text:
                errs.append(f"금지 표현 '{w}': {eid}")
        if OWN_HOME.search(text) or EXPERIENCE_TONE.search(text):
            errs.append(f"경험 어투: {eid}")
        if RELATIVE_TIME.search(text):
            errs.append(f"시점 의존 표현 '{RELATIVE_TIME.search(text).group()}': {eid}")
        je = josa_errors(text) + [m.group() for m in BAD_PCT_JOSA.finditer(text)]
        if je:
            errs.append(f"조사 오류 {je[:3]}: {eid}")
        if "**" in text:
            errs.append(f"마크다운 강조: {eid}")
        if not x["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {eid}")
        if not TRANSITION.search(x["body"]):
            errs.append(f"사실/해석 전환문 없음: {eid}")
        for need in NEED:
            if need not in x["body"]:
                errs.append(f"'{need}' 없음: {eid}")
        mr = mono_run(x["body"])
        if mr >= MONO_RUN:
            errs.append(f"문말 '니다.' {mr}연속: {eid}")
        if len(x["title"]) > MAX_TITLE:
            errs.append(f"제목 {len(x['title'])}자 초과: {eid}")
        if x["published_at"] > NOW:
            errs.append(f"미래 시각: {eid}")
        if x["category"] not in ("거래", "전월세"):
            errs.append(f"카테고리: {eid}")
        if not x["sources"] or not all(f"확인 {COLLECTED}" in s["label"] for s in x["sources"]):
            errs.append(f"출처·확인일: {eid}")
        if x["persona_external_id"] not in ANALYSTS or x["persona_external_id"] not in registered:
            errs.append(f"페르소나: {x['persona_external_id']} ({eid})")
        for c in b["payload"]["comments"]:
            if c["persona_external_id"] not in ANALYSTS or c["persona_external_id"] not in registered:
                errs.append(f"댓글 페르소나: {c['persona_external_id']}")
            if c["persona_external_id"] == x["persona_external_id"]:
                errs.append(f"글쓴이가 자기 글에 댓글: {c['external_id']}")
            # 서버가 지우거나 422로 거절한다. 지워지면 서버 글과 팩이 어긋나 재현이 깨진다
            if AI_COMMENT_ASK.search(c["body"]):
                errs.append(f"댓글이 독자 행동을 청하거나 다음 글을 약속: {c['external_id']}")

    bodies = [c["body"] for c in comments]
    if len(set(bodies)) != len(bodies):
        errs.append("댓글 본문 중복")
    return errs


def main():
    ap = argparse.ArgumentParser(description="부동산원 주간 동향 소급 기록 팩")
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
    for b in pack["bundles"]:
        b.pop("_asof")
    OUT.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  {'게시 시각':27}{'글':36}{'자수':>4}  제목")
    for b in pack["bundles"]:
        x = b["payload"]["post"]
        print(f"  {x['published_at']:27}{x['external_id']:36}{len(x['title']):>4}  {x['title']}")
    print(f"\n글 {len(pack['bundles'])}편 · 댓글 "
          f"{sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
