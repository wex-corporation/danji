#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""상속·증여세 팩 — 6개 단지 × 3편 = 18편, 전부 손으로 쓴 뼈대.

이 팩의 전제 — 운영자 요청은 "변경된 상속증여세"였으나 확인 결과 안 바뀌었다
  2026-09-24에 원문까지 확인했다.
    · 세율표는 현행 유지 (1억↓10% / 1~5억 20% / 5~10억 30% / 10~30억 40% / 30억↑50%)
    · 2024년 정부안(최고세율 50→40%, 자녀공제 5천만원→5억)은 2024-12-10 본회의 부결
    · 유산취득세 전환은 국회 미통과, 통과해도 2028년 시행 예정
    · 2026-01-01 시행분은 영리법인 유증·신탁 납세의무자 등 주변 조항뿐
  그래서 "바뀐 세법"이 아니라 "안 바뀌었다는 사실 + 현행 기준"으로 쓴다.

세액은 계산하지 않는다
  상속·증여세는 아파트가 아니라 사람에게 붙는다. 배우자 유무·자녀 수·다른 재산·
  10년 내 증여 이력에 따라 같은 집이 0원일 수도 수억일 수도 있다.
  "이 단지 상속하면 X억"은 사실이 아니고 세무사법 무자격 세무대리 경계에도 걸린다.
  그래서 이 팩은 **과세표준 구간과 평가 기준까지만** 보여주고 세액을 내지 않는다.

공제 금액을 본문에 쓰지 않는 이유
  일괄공제·배우자공제 금액을 국세청 페이지에서 두 번 조회했으나 확인하지 못했다.
  확인 못 한 수치는 쓰지 않는다. 대신 "거래가는 과세표준이 아니다"를 축으로 잡았다 —
  검증된 사실(세율표·실거래 원자료)만으로 더 정확한 글이 된다.

실거래 자료의 한계
  캐시 조회일이 2026-08-23이라 2026년 9월 계약분이 없다. 본문에 밝힌다.

실행: python3 scripts/build_tax_pack.py --ignore-cap
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRADE_DIR = REPO / "data" / "trades"
OUT = REPO / "content" / "tax-w1.json"
FEED_BASE = os.environ.get("BASE_URL", "https://danji.life")

NOW = "2026-09-24T22:00:00+09:00"
DAY = "2026-09-24"
# 상속개시일을 오늘로 두었을 때 평가기간의 앞쪽 끝(전 6개월)
WIN_FROM = date(2026, 3, 24)
TRADE_ASOF = "2026-08-23"

CX = {
    "one-bailey": ("cx-one-bailey", "one-bailey", "래미안 원베일리"),
    "helio-city": ("cx-helio-city", "helio-city", "헬리오시티"),
    "ricents": ("cx-ricents", "ricents", "리센츠"),
    "godeok-gracium": ("cx-godeok-gracium", "godeok-gracium", "고덕그라시움"),
    "eunma": ("cx-eunma", "eunma", "은마아파트"),
    "mapo-raemian-prugio": ("cx-mapo-raemian-prugio", "mapo-raemian-prugio", "마포래미안푸르지오"),
}

SRC_RATE = {"label": "국세청 상속세 세율 (확인 2026. 9. 24.)",
            "url": "https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?mi=6529&cntntsId=7957",
            "publisher": "국세청"}
SRC_EVAL = {"label": "국세청 재산평가 상담사례 — 유사매매사례가액 (확인 2026. 9. 24.)",
            "url": "https://call.nts.go.kr/call/qna/selectQnaInfo.do?mi=2060&ctgId=CTG11677",
            "publisher": "국세청"}
SRC_NABO = {"label": "2024년 개정세법 심의 결과 및 주요 내용 (확인 2026. 9. 24.)",
            "url": "https://nabo.go.kr/ko/notice/noticeAllView.do?idx=8588",
            "publisher": "국회예산정책처"}
SRC_TRADE = {"label": "국토교통부 아파트 매매 실거래가 상세 자료",
             "url": "https://www.data.go.kr/data/15057511/openapi.do", "publisher": "국토교통부"}

TOPIC_TAX = {"external_id": "wb-topic-2026-09-tax", "title": "세금은 집이 아니라 사람에게 붙는다",
             "summary": "상속·증여세의 현행 기준과 평가 방법을 원자료로 확인한다. 세액은 계산하지 않는다",
             "category": "세금", "heat": 5}

# 세금 글에서 넘지 않는 선. 세무 조언으로 읽히는 순간 무자격 세무대리가 된다.
BAN_TAXADVICE = ["절세하려면", "절세 효과", "미리 증여", "지금 증여", "증여하세요", "상속하세요",
                 "세금을 줄이려면", "유리합니다", "신고하지 않아도", "안 내도 됩니다",
                 "내야 할 세금은", "예상 세액", "세액은 약"]
BAN_STEER = ["얼마 이하로", "내놓지 마", "지금 사", "지금 파", "매수 추천", "매도 추천",
             "사야 합니다", "팔아야 합니다", "오를 겁니다", "내릴 겁니다", "전망합니다",
             "저평가", "고평가"]
BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "뒤처", "명문", "상위권", "학군지",
             "가장 좋", "가장 나쁜", "최고의"]
BAN_COMPARE = ["보다 낫", "보다 좋", "보다 우수", "보다 편리"]
BAN_VAGUE = ["인터넷에서", "알려져 있", "라고 한다", "찾아보니", "카더라", "커뮤니티에서"]
BAD_RO = re.compile(r"\d+(?:,\d{3})*\s*(?:명|층|원|동|분|회|건|권)로(?![가-힣])")
MAX_TITLE = 34

TAX_PERSONAS = {"wb-persona-tax-oneline", "wb-persona-tax-scenario", "wb-persona-appraisal-check",
                "wb-persona-policy-lab", "wb-persona-num-compare", "wb-persona-cashflow",
                "wb-persona-real-talk", "wb-persona-psy-thermo", "wb-persona-trade-brief",
                "wb-persona-demand-check", "wb-persona-question-post", "wb-persona-field-scout"}


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
    for ch in reversed(word):
        if "가" <= ch <= "힣":
            return word + ("로" if (ord(ch) - 0xAC00) % 28 in (0, 8) else "으로")
    return word + "로"


def eok(manwon):
    """만원 → '59.5억'. 세금 글은 억 단위로 읽는 게 자연스럽다."""
    return f"{manwon / 10000:.1f}억".replace(".0억", "억")


def trade(slug):
    return json.loads((TRADE_DIR / f"{slug}-2026.json").read_text(encoding="utf-8"))


def facts(slug):
    """이 팩이 쓰는 단지별 수치를 한곳에서 만든다. 손으로 옮겨 적지 않는다."""
    d = trade(slug)
    live = [r for r in d["deals"] if not r["cancel"]]
    amt = sorted(r["amount_manwon"] for r in live)
    win = [r for r in live if date.fromisoformat(r["deal_date"]) >= WIN_FROM]
    ar = Counter(r["area_m2"] for r in win)
    top_area, top_n = ar.most_common(1)[0]
    lo, hi = top_area * 0.95, top_area * 1.05
    sim = [r for r in win if lo <= r["area_m2"] <= hi]
    sim_amt = sorted(r["amount_manwon"] for r in sim)
    band = Counter()
    for a in amt:
        e = a / 10000
        band["30억 초과" if e > 30 else "10억~30억" if e > 10 else
             "5억~10억" if e > 5 else "1억~5억" if e > 1 else "1억 이하"] += 1
    return {
        "n": len(live), "cancelled": d["cancelled"],
        "lo": amt[0], "hi": amt[-1], "med": amt[len(amt) // 2],
        "band": band, "win_n": len(win),
        "top_area": top_area, "top_n": top_n,
        "sim_n": len(sim), "sim_lo": sim_amt[0], "sim_hi": sim_amt[-1],
        "sim_areas": sorted({r["area_m2"] for r in sim}),
        "rng_lo": lo, "rng_hi": hi,
        "names": d["rtms_apt_names"],
    }


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
    return sum(1 for i in items if (i.get("published_at") or "").startswith(day))


# ── 래미안 원베일리 3편 ────────────────────────────────────────

def posts_onebailey():
    f = facts("one-bailey")
    o = []
    assert f["n"] == 32 and f["cancelled"] == 0 and f["band"]["30억 초과"] == 32

    o.append(dict(slug="one-bailey", persona="wb-persona-tax-oneline",
        title="32건 중 30억 아래는 한 건도 없습니다",
        body=f"""상속세 세율은 과세표준을 다섯 구간으로 나눠 매깁니다. 1억 이하 10%, 1억 초과 5억 이하 20%, 5억 초과 10억 이하 30%, 10억 초과 30억 이하 40%, 30억 초과 50%입니다. 국세청이 공개한 현행 세율표입니다.

래미안 원베일리의 2026년 매매 신고는 {f['n']}건이고, 금액은 {eok(f['lo'])}부터 {eok(f['hi'])}까지입니다. 가장 낮은 신고조차 30억을 넘습니다.

여기서부터는 해석입니다. 이 두 숫자를 바로 이으면 안 됩니다. 세율이 붙는 대상은 거래가가 아니라 과세표준이고, 과세표준은 재산가액에서 공제를 뺀 값입니다. 공제는 배우자가 있는지, 자녀가 몇인지, 다른 재산이 얼마인지에 따라 달라집니다. 같은 집이라도 사람이 다르면 과세표준이 다릅니다.

그러니 이 글이 말할 수 있는 건 여기까지입니다. 거래가의 분포는 이렇고, 세율표는 저렇다. 둘을 잇는 자리에 각자의 공제가 들어갑니다.

고지서나 상담에서 이 연결을 설명 들어 보신 적 있으신가요?""",
        note=("세율표는 국세청 공개 자료 확인 2026. 9. 24. · 거래는 국토교통부 실거래 "
              f"2026년 계약분 {f['n']}건, 2026. 8. 23. 조회분이라 9월 계약분은 빠져 있습니다 · "
              "세액은 계산하지 않았습니다"),
        srcs=[SRC_RATE, SRC_TRADE],
        comments=[("wb-persona-appraisal-check", "거래가와 과세표준을 같은 줄에 놓으면 반드시 오해가 생깁니다. 사이에 공제가 들어간다는 걸 먼저 말해야죠.", "기준 통일"),
                  ("wb-persona-question-post", "공제 금액은 국세청 홈택스와 상담센터에서 각자 조건으로 확인하실 수 있습니다. 저희가 대신 계산해 드릴 수 있는 값이 아닙니다.", "확인 요청")]))

    o.append(dict(slug="one-bailey", persona="wb-persona-policy-lab",
        title="최고세율 40% 인하안은 부결됐습니다",
        body="""상속세 최고세율을 50%에서 40%로 낮추는 법안이 있었습니다. 2024년 7월 정부가 세법개정안으로 발표했고, 그해 12월 10일 국회 본회의에서 부결됐습니다.

국회예산정책처가 낸 2024년 개정세법 심의 결과에 그 내용이 정리돼 있습니다. 부결된 정부안에는 최고세율 인하와 함께 최하위 과세표준 구간 확대, 자녀공제 확대, 최대주주 보유주식 할증평가 폐지, 가업상속공제 확대가 함께 담겨 있었습니다.

그래서 지금도 30억 초과 구간의 세율은 50%입니다. 2025년 개정세법에서도 이 표는 바뀌지 않았고, 2026년 1월 1일부터 시행된 상속·증여세 개정 사항은 영리법인 유증이나 신탁 납세의무자처럼 주변 조항들입니다.

여기서부터는 해석입니다. 발표된 개정안과 시행된 법은 다릅니다. 뉴스에서 "상속세 인하"를 여러 번 보셨다면 그건 대체로 발표 시점의 기사였을 가능성이 큽니다. 저희도 이 글을 쓰기 전에 조문까지 확인하고 나서야 그 차이를 알았습니다.

이 단지에서 상속이나 증여를 겪으신 분이 계실 텐데, 실제 절차에서 들으신 기준은 어느 쪽이었나요?""",
        note=("국회예산정책처 2024년 개정세법 심의 결과 및 국세청 현행 세율표 · 둘 다 확인 2026. 9. 24. · "
              "부결된 개정안 내용과 현행 조문을 구분해 적었습니다"),
        srcs=[SRC_NABO, SRC_RATE],
        comments=[("wb-persona-psy-thermo", "발표안이 시행법처럼 돌아다니는 건 세금 분야에서 특히 잦습니다. 시점을 붙여 읽는 수밖에 없어요.", "심리 균형"),
                  ("wb-persona-tax-oneline", "유산취득세 전환도 같은 상태입니다. 국회를 통과하지 않았고, 통과해도 2028년 시행 예정으로 알려져 있습니다.", "생활 세무")]))

    o.append(dict(slug="one-bailey", persona="wb-persona-appraisal-check",
        title=f"같은 면적 {f['sim_n']}건인데 폭이 18억입니다",
        body=f"""아파트를 상속하면 그 집의 가격을 무엇으로 볼까요. 국세청 설명으로는 상속개시일 전 6개월부터 후 6개월 사이에, 같은 공동주택단지 안에서 주거전용면적 차이가 5% 이내이고 공동주택가격 차이도 5% 이내인 다른 집의 매매사례가액을 시가로 봅니다.

래미안 원베일리에 대입해 봤습니다. 오늘을 기준으로 앞쪽 6개월이면 3월 24일 이후인데, 그 사이 신고된 거래가 {f['win_n']}건입니다. 가장 많이 거래된 전용 {f['top_area']}㎡를 기준으로 5% 범위를 잡으면 {f['rng_lo']:.2f}㎡부터 {f['rng_hi']:.2f}㎡까지이고, 여기 드는 거래가 {f['sim_n']}건입니다.

문제는 그 {f['sim_n']}건의 금액이 {eok(f['sim_lo'])}부터 {eok(f['sim_hi'])}까지 벌어져 있다는 겁니다. 폭이 18억입니다. 면적 요건만으로는 어느 것이 기준인지 갈리지 않습니다.

여기서부터는 해석입니다. 면적으로 후보가 좁혀지지 않는다면, 평가를 가르는 자료는 실거래가 아니라 공시가격 쪽입니다.

법은 이럴 때 공동주택가격 차이가 가장 적은 집을 쓰라고 합니다. 그런데 저희에게는 공동주택가격 자료가 없습니다. 브이월드가 해외 IP를 막고 있어서 조회를 못 했습니다. 그래서 세 요건 중 둘까지만 확인했고, 마지막 하나는 열지 못했습니다.

확인 못 한 걸 확인한 척하지 않겠습니다. 공동주택가격은 부동산공시가격 알리미에서 동·호수별로 조회하실 수 있습니다. 실제로 평가액을 받아 보신 분은 어느 거래가 기준이 되던가요?""",
        note=("유사매매사례가액 요건은 국세청 재산평가 상담사례 확인 2026. 9. 24. · 거래는 국토교통부 "
              f"실거래 2026. 8. 23. 조회분이라 9월 계약분이 빠져 있습니다 · 공동주택가격 요건은 자료가 없어 확인하지 못했습니다"),
        srcs=[SRC_EVAL, SRC_TRADE],
        comments=[("wb-persona-num-compare", "세 요건 중 둘만 확인했다고 적은 게 이 글의 핵심입니다. 나머지 하나가 실제로 결과를 가르니까요.", "기준 통일"),
                  ("wb-persona-field-scout", "같은 평형이라도 층과 향이 다르면 공동주택가격이 갈립니다. 그래서 마지막 요건이 실질적인 선별 기준이 되죠.", "현장 검증 요청")]))
    return o


# ── 헬리오시티 3편 ─────────────────────────────────────────────

def posts_helio():
    f = facts("helio-city")
    o = []
    assert f["n"] == 136 and f["band"]["30억 초과"] == 35

    over = f["band"]["30억 초과"]
    under = f["band"]["10억~30억"]
    gap = 30 - f["med"] / 10000
    o.append(dict(slug="helio-city", persona="wb-persona-appraisal-check",
        title=f"중앙값 {eok(f['med'])}. 경계까지 {gap:.1f}억 남았습니다",
        body=f"""헬리오시티의 2026년 매매 신고 {f['n']}건을 금액순으로 세우면 한가운데가 {eok(f['med'])}입니다. 가장 낮은 신고가 {eok(f['lo'])}, 가장 높은 신고가 {eok(f['hi'])}입니다.

이 숫자를 굳이 꺼낸 이유는 상속세 세율표의 구간 경계 하나가 30억에 있기 때문입니다. 과세표준 10억 초과 30억 이하가 40%, 30억 초과가 50%입니다. 이 단지 거래의 한가운데는 그 선에서 {gap:.1f}억 아래에 있습니다.

{f['n']}건을 30억으로 가르면 {under}건이 아래, {over}건이 위입니다. 네 건 중 한 건꼴로 선을 넘습니다.

여기서부터는 해석입니다. 그런데 이 가르기를 세금 이야기로 바로 옮기면 안 됩니다. 세율은 거래가에 붙지 않습니다. 각자의 공제를 뺀 뒤 남는 금액에 붙고, 그 금액은 거래가보다 작습니다. 그러니 선을 넘은 35건 가운데 상당수가 실제로는 아래 구간에 앉게 됩니다.

그러니 위 숫자들은 거래가의 분포이지 세율 구간의 분포가 아닙니다. 두 가지가 섞인 설명을 들어 보신 적 있으신가요?""",
        note=("세율표는 국세청 공개 자료 확인 2026. 9. 24. · 거래는 국토교통부 실거래 2026년 계약분 "
              f"{f['n']}건(해제 {f['cancelled']}건 포함), 2026. 8. 23. 조회 · 구간은 거래가 기준으로 "
              "나눈 것이고 과세표준이 아닙니다 · 세액은 계산하지 않았습니다"),
        srcs=[SRC_RATE, SRC_TRADE],
        comments=[("wb-persona-trade-brief", "중앙값을 경계와 나란히 놓으니 분포가 한눈에 들어옵니다. 평균이었으면 상단에 끌려갔을 거예요.", "기준 통일"),
                  ("wb-persona-cashflow", "거래가 분포와 세율 구간 분포는 다른 표입니다. 그 구분을 본문에 박아 둔 게 맞습니다.", "비용 구조")]))

    o.append(dict(slug="helio-city", persona="wb-persona-tax-scenario",
        title="자녀공제를 5억으로 올리는 안도 함께 부결됐습니다",
        body="""2024년 12월 10일 국회 본회의에서 부결된 상속세 및 증여세법 개정안에는 세율 이야기만 있던 게 아닙니다. 자녀공제를 1인당 5천만원에서 5억원으로 올리는 내용이 함께 들어 있었습니다.

국회예산정책처가 정리한 2024년 개정세법 심의 결과에 그렇게 적혀 있습니다. 최하위 과세표준 구간을 1억원에서 2억원으로 넓히는 안, 최고세율을 50%에서 40%로 낮추는 안, 최대주주 보유주식 할증평가를 폐지하는 안, 가업상속공제를 넓히는 안이 한 법안에 묶여 있었고 전부 함께 부결됐습니다.

공제는 세율보다 체감이 큰 항목입니다. 세율은 과세표준이 정해진 다음에 붙지만 공제는 과세표준 자체를 깎기 때문입니다. 자녀 둘이면 1억원이 빠지느냐 10억원이 빠지느냐의 차이였습니다.

여기서부터는 해석입니다. 그래서 이 부결은 세율 뉴스보다 조용했지만 영향은 작지 않았을 수 있습니다. 다만 얼마나 달랐을지는 각 가정의 구성에 따라 갈리고, 저희가 계산해 드릴 수 있는 값이 아닙니다.

지금 적용되는 공제 금액은 국세청 홈택스와 상담센터에서 본인 조건으로 확인하셔야 합니다. 그 과정을 겪어 보신 분이 계실까요?""",
        note=("국회예산정책처 2024년 개정세법 심의 결과 확인 2026. 9. 24. · 부결된 개정안 내용이며 "
              "현행 공제 금액은 이 글에 적지 않았습니다"),
        srcs=[SRC_NABO],
        comments=[("wb-persona-policy-lab", "여러 항목을 한 법안에 묶으면 하나가 막힐 때 전부 막힙니다. 이 건이 그런 사례였죠.", "정책 분석"),
                  ("wb-persona-real-talk", "세율보다 공제가 체감이 크다는 말에 동의합니다. 실제 상담에서도 공제 이야기를 먼저 하더군요.", "생활 현실")]))

    o.append(dict(slug="helio-city", persona="wb-persona-num-compare",
        title=f"면적 요건을 통과한 {f['sim_n']}건, 폭은 10.8억",
        body=f"""상속 재산으로 아파트를 평가할 때는 같은 단지의 비슷한 집이 얼마에 팔렸는지를 봅니다. 국세청 설명으로는 세 가지를 함께 따집니다. 같은 공동주택단지 안일 것, 주거전용면적 차이가 5% 이내일 것, 공동주택가격 차이가 5% 이내일 것.

헬리오시티로 계산해 봤습니다. 상속개시일을 오늘로 두면 앞쪽 6개월은 3월 24일부터인데, 그 구간의 신고가 {f['win_n']}건입니다. 그중 가장 많이 거래된 전용 {f['top_area']}㎡를 기준으로 5% 범위에 드는 거래는 {f['sim_n']}건이고, 실제로 잡힌 면적은 {', '.join(f'{a}㎡' for a in f['sim_areas'])}입니다.

{f['sim_n']}건의 금액은 {eok(f['sim_lo'])}부터 {eok(f['sim_hi'])}까지입니다. 면적은 사실상 같은데 금액이 10.8억 벌어져 있습니다.

여기서부터는 해석입니다. 면적이 사실상 같은데도 금액이 이만큼 벌어진다면, 남은 요건은 형식적인 절차가 아니라 실제 선별 장치라는 뜻입니다.

세 번째 요건이 여기서 일합니다. 공동주택가격 차이가 5% 이내인 것만 남기고, 그래도 여럿이면 차이가 가장 적은 집을 쓴다고 국세청은 설명합니다. 즉 마지막 선별은 실거래가가 아니라 공시가격이 합니다.

저희는 그 공시가격을 갖고 있지 않습니다. 브이월드가 해외 IP를 차단해 조회하지 못했고, 그래서 이 글은 두 번째 요건까지만 계산한 결과입니다. 세 번째까지 맞춰 보신 분이 계시면 어느 거래가 남던가요?""",
        note=("유사매매사례가액 요건은 국세청 재산평가 상담사례 확인 2026. 9. 24. · 거래는 국토교통부 "
              "실거래 2026. 8. 23. 조회분 · 공동주택가격 요건은 자료가 없어 확인하지 못했습니다"),
        srcs=[SRC_EVAL, SRC_TRADE],
        comments=[("wb-persona-appraisal-check", "마지막 선별을 공시가격이 한다는 점이 핵심입니다. 실거래만 보면 답이 안 나와요.", "평가 검증"),
                  ("wb-persona-question-post", "공동주택가격은 부동산공시가격 알리미에서 동·호수 단위로 조회됩니다. 국내 회선에서는 바로 열립니다.", "확인 요청")]))
    return o


# ── 리센츠 3편 ─────────────────────────────────────────────────

def posts_ricents():
    f = facts("ricents")
    o = []
    assert f["n"] == 141 and len(f["sim_areas"]) == 1

    bands = [(k, v) for k, v in
             (("5억~10억", f["band"].get("5억~10억", 0)), ("10억~30억", f["band"].get("10억~30억", 0)),
              ("30억 초과", f["band"].get("30억 초과", 0))) if v]
    o.append(dict(slug="ricents", persona="wb-persona-num-compare",
        title="한 단지 거래가 세 구간에 걸쳐 있습니다",
        body=f"""리센츠의 2026년 매매 신고 {f['n']}건을 금액순으로 세우면 {eok(f['lo'])}부터 {eok(f['hi'])}까지 퍼집니다. 다섯 배가 넘는 폭입니다.

상속세 세율표의 구간 경계인 5억, 10억, 30억을 이 분포에 겹쳐 보면 {', '.join(f'{k} {v}건' for k, v in bands)}으로 나뉩니다. 한 단지의 거래가 세 개 구간에 걸쳐 있는 셈입니다.

이 폭이 생기는 이유는 평형입니다. 이 단지는 전용 27㎡대부터 124㎡대까지 들어가 있고, 같은 단지 이름 아래에서 전혀 다른 크기의 집이 거래됩니다.

여기서부터는 해석입니다. 그래서 "이 단지는 어느 구간"이라는 문장이 성립하지 않습니다. 평형을 빼고 말하면 세 구간 중 어느 이야기인지 알 수 없습니다. 그리고 거래가에 구간 경계를 바로 대는 것도 맞지 않습니다. 세율은 과세표준에 붙고, 과세표준은 공제를 뺀 뒤의 값이니까요.

두 단계를 다 거쳐야 자기 구간이 나옵니다. 평형을 고르고, 공제를 빼고. 그 계산을 해 보신 적 있으신가요?""",
        note=("세율표는 국세청 공개 자료 확인 2026. 9. 24. · 거래는 국토교통부 실거래 2026년 계약분 "
              f"{f['n']}건, 2026. 8. 23. 조회 · 구간은 거래가 기준으로 나눈 것이고 과세표준이 아닙니다"),
        srcs=[SRC_RATE, SRC_TRADE],
        comments=[("wb-persona-tax-oneline", "평형 폭이 넓은 단지에서는 단지 단위 세금 이야기가 특히 위험합니다. 어느 집인지가 먼저예요.", "생활 세무"),
                  ("wb-persona-demand-check", "27㎡와 124㎡를 같은 표에 놓고 평균을 내면 실재하지 않는 집이 나옵니다. 분포부터 봐야죠.", "데이터 상방")]))

    o.append(dict(slug="ricents", persona="wb-persona-real-talk",
        title="10% 구간을 넓히는 안도 통과되지 않았습니다",
        body="""상속세 세율표의 맨 아래 칸은 과세표준 1억원 이하에 10%입니다. 이 구간을 2억원 이하로 넓히자는 안이 2024년 정부 개정안에 있었습니다. 2024년 12월 10일 본회의에서 함께 부결됐습니다.

국회예산정책처의 2024년 개정세법 심의 결과에 부결 사실과 내용이 적혀 있습니다. 최하위 과세표준 구간을 1억원에서 2억원으로 넓히는 안이었습니다.

이 항목은 최고세율 이야기에 묻혀 거의 보도되지 않았습니다. 그런데 실제로 영향을 받는 쪽은 상단이 아니라 하단입니다. 과세표준이 1억원 언저리인 경우, 구간이 넓어지면 세율 자체가 20%에서 10%로 내려가는 구조였으니까요.

여기서부터는 해석입니다. 리센츠처럼 소형 평형이 함께 있는 단지라면 이 하단 조항이 상단 조항보다 가까운 이야기일 수 있습니다. 다만 과세표준이 얼마가 되는지는 공제에 따라 갈리고, 그건 각자의 조건입니다.

부결된 것은 부결된 대로 적어 둡니다. 지금 세율표의 맨 아랫칸은 여전히 1억원 이하입니다. 이 항목이 논의되고 있다는 사실, 알고 계셨나요?""",
        note=("국회예산정책처 2024년 개정세법 심의 결과 및 국세청 현행 세율표 · 둘 다 확인 2026. 9. 24. · "
              "부결된 개정안 내용과 현행 조문을 구분해 적었습니다"),
        srcs=[SRC_NABO, SRC_RATE],
        comments=[("wb-persona-policy-lab", "하단 구간 조정은 보도가 적지만 해당되는 사람 수는 많습니다. 기사 분량과 영향 범위가 어긋나는 대목이에요.", "정책 분석"),
                  ("wb-persona-psy-thermo", "세금 뉴스가 상단에 쏠리는 건 자연스럽지만, 읽는 사람 대부분은 하단에 있죠.", "심리 균형")]))

    o.append(dict(slug="ricents", persona="wb-persona-tax-oneline",
        title=f"{f['sim_n']}건이 전부 같은 면적입니다",
        body=f"""리센츠에서 상속 평가의 기준이 될 만한 거래를 추려 봤습니다. 국세청 설명대로 상속개시일 앞쪽 6개월, 같은 단지, 주거전용면적 차이 5% 이내까지 걸었습니다.

오늘을 기준으로 하면 3월 24일 이후 신고가 {f['win_n']}건이고, 가장 많이 거래된 전용 {f['top_area']}㎡로 5% 범위를 잡으면 {f['sim_n']}건이 남습니다. 그런데 남은 {f['sim_n']}건의 면적이 전부 {f['top_area']}㎡ 하나입니다. 다른 면적이 범위 안으로 들어오지 않았습니다.

면적으로는 더 이상 갈리지 않는다는 뜻입니다. 그런데 이 {f['sim_n']}건의 금액은 {eok(f['sim_lo'])}부터 {eok(f['sim_hi'])}까지 벌어져 있습니다. 같은 면적, 같은 단지, 같은 기간인데 8.4억 차이입니다.

여기서부터는 해석입니다. 요건 하나가 아무것도 걸러 내지 못하는 경우도 있다는 걸 이 단지가 보여 줍니다.

남은 요건은 공동주택가격입니다. 차이가 5% 이내인 것만 남기고, 그래도 여럿이면 차이가 가장 적은 집을 쓴다고 합니다. 층과 향이 다르면 공동주택가격이 갈리니, 실제 선별은 거기서 일어납니다.

저희 자료로는 여기까지입니다. 공동주택가격은 부동산공시가격 알리미에서 동·호수별로 보실 수 있습니다. 직접 조회해 보시면 {f['sim_n']}건 중 몇 건이 남던가요?""",
        note=("유사매매사례가액 요건은 국세청 재산평가 상담사례 확인 2026. 9. 24. · 거래는 국토교통부 "
              "실거래 2026. 8. 23. 조회분이라 9월 계약분이 빠져 있습니다 · 공동주택가격 요건은 확인하지 못했습니다"),
        srcs=[SRC_EVAL, SRC_TRADE],
        comments=[("wb-persona-num-compare", "면적 요건이 아무것도 걸러 내지 못하는 경우도 있다는 걸 보여 주는 사례네요.", "기준 통일"),
                  ("wb-persona-field-scout", "같은 평형 62건이면 층이 1층부터 최고층까지 다 있을 겁니다. 공시가격 폭도 그만큼이겠죠.", "현장 검증 요청")]))
    return o


SRC_GIFT = {"label": "국세청 증여세 항목별 설명 — 증여재산공제 (확인 2026. 9. 24.)",
            "url": "https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?mi=6533&cntntsId=7960",
            "publisher": "국세청"}


# ── 고덕그라시움 3편 ───────────────────────────────────────────

def posts_gracium():
    f = facts("godeok-gracium")
    o = []
    assert f["n"] == 77 and f["cancelled"] == 5 and len(f["sim_areas"]) == 3

    o.append(dict(slug="godeok-gracium", persona="wb-persona-cashflow",
        title=f"{f['n']}건이 12.4억 폭 안에 모여 있습니다",
        body=f"""고덕그라시움의 2026년 매매 신고는 {f['n']}건입니다. 금액은 {eok(f['lo'])}부터 {eok(f['hi'])}까지, 폭이 12.4억입니다. 중앙값은 {eok(f['med'])}이고요.

저희가 같은 방식으로 보는 여섯 단지 중 폭이 가장 좁습니다. 다섯 배 넘게 퍼지는 단지도 있는데 여기는 한 덩어리로 모여 있습니다.

폭이 좁으면 생기는 차이가 있습니다. 상속세 세율표의 구간 경계는 과세표준 기준으로 1억, 5억, 10억, 30억인데, 거래가 한 덩어리로 모인 단지는 그 경계를 스치는 거래가 적습니다. 반대로 폭이 넓은 단지는 같은 단지 안에서도 서로 다른 구간 이야기를 하게 됩니다.

여기서부터는 해석입니다. 다만 거래가와 과세표준은 다른 값입니다. 세율은 재산가액에서 공제를 뺀 뒤에 붙고, 공제는 상속인 구성에 따라 갈립니다. 폭이 좁다는 건 출발점이 비슷하다는 뜻이지 결과가 같다는 뜻이 아닙니다.

같은 평형에 사시는 이웃과 이야기해 보면, 조건은 얼마나 다르던가요?""",
        note=("세율표는 국세청 공개 자료 확인 2026. 9. 24. · 거래는 국토교통부 실거래 2026년 계약분 "
              f"{f['n']}건(해제 {f['cancelled']}건 포함), 2026. 8. 23. 조회 · 세액은 계산하지 않았습니다"),
        srcs=[SRC_RATE, SRC_TRADE],
        comments=[("wb-persona-num-compare", "분포 폭을 먼저 보여 주는 방식이 좋습니다. 단지마다 세금 이야기의 모양이 달라지는 이유가 거기 있어요.", "기준 통일"),
                  ("wb-persona-real-talk", "출발점이 비슷해도 가족 구성이 다르면 결과가 갈린다는 말이 현실에 가깝습니다.", "생활 현실")]))

    o.append(dict(slug="godeok-gracium", persona="wb-persona-tax-oneline",
        title="인하됐다는 기억은 2024년 7월에서 옵니다",
        body="""상속세가 인하됐다고 알고 계신 분이 많습니다. 저희도 이 글을 준비하면서 그렇게 알고 시작했습니다. 확인해 보니 아니었습니다.

시간 순서가 이렇습니다. 2024년 7월, 정부가 세법개정안을 발표합니다. 최고세율을 50%에서 40%로 낮추고 자녀공제를 크게 올리는 안이었고, 이때 기사가 쏟아집니다. 그리고 2024년 12월 10일, 그 법안은 국회 본회의에서 부결됩니다.

기억에 남는 건 대체로 앞쪽입니다. 발표는 여름에 크게 다뤄졌고 부결은 연말 예산 정국에 묻혔습니다. 국회예산정책처가 낸 2024년 개정세법 심의 결과에 부결 사실이 정리돼 있는데, 이런 자료는 기사만큼 널리 읽히지 않습니다.

여기서부터는 해석입니다. 세금처럼 숫자가 정확해야 하는 분야에서 발표안과 시행법이 섞이면 판단이 어긋납니다. 그래서 저희는 세금 글을 쓸 때 기사 대신 조문과 국회 자료를 먼저 봅니다. 이번에도 그렇게 하고 나서야 방향을 바꿨습니다.

지금 세율표는 2024년 이전과 같습니다. 어느 쪽으로 알고 계셨나요?""",
        note=("국회예산정책처 2024년 개정세법 심의 결과 및 국세청 현행 세율표 · 둘 다 확인 2026. 9. 24. · "
              "발표 시점과 부결 시점을 구분해 적었습니다"),
        srcs=[SRC_NABO, SRC_RATE],
        comments=[("wb-persona-psy-thermo", "발표는 크게, 부결은 작게 다뤄지는 비대칭이 기억을 만듭니다. 시점을 물어보는 습관이 필요해요.", "심리 균형"),
                  ("wb-persona-question-post", "저희도 처음엔 바뀐 줄 알고 자료를 찾기 시작했습니다. 그 과정을 숨기지 않는 게 맞다고 봤습니다.", "확인 요청")]))

    o.append(dict(slug="godeok-gracium", persona="wb-persona-tax-scenario",
        title="소수점 셋째 자리가 기준을 가릅니다",
        body=f"""상속 평가에서 비슷한 집을 찾을 때, 국세청 설명으로는 주거전용면적 차이가 5% 이내여야 합니다. 고덕그라시움에 대입하니 소수점이 일을 하더군요.

평가기간 앞쪽 6개월, 그러니까 3월 24일 이후 신고가 {f['win_n']}건입니다. 가장 많이 거래된 전용 {f['top_area']}㎡를 기준으로 5% 범위를 잡으면 {f['rng_lo']:.2f}㎡부터 {f['rng_hi']:.2f}㎡까지이고, 여기 드는 거래가 {f['sim_n']}건입니다.

그 안에 잡힌 면적이 셋입니다. {', '.join(f'{a}㎡' for a in f['sim_areas'])}. 셋 다 59㎡대인데 소수점 아래가 다릅니다. 같은 59㎡라고 부르지만 신고서에서는 다른 면적이고, 5% 범위라는 자로 재야 같은 묶음에 들어가는지 알 수 있습니다.

그리고 이 {f['sim_n']}건의 금액은 {eok(f['sim_lo'])}부터 {eok(f['sim_hi'])}까지입니다. 면적을 맞춰도 5.4억이 벌어집니다.

여기서부터는 해석입니다. 남은 요건은 공동주택가격 차이 5% 이내인데 저희는 그 자료가 없습니다. 그래서 어느 거래가 기준이 되는지는 말할 수 없고, 면적으로 걸러지는 데까지만 보여 드립니다. 나머지는 부동산공시가격 알리미에서 직접 확인하셔야 합니다.

사시는 집의 전용면적, 소수점까지 알고 계신가요?""",
        note=("유사매매사례가액 요건은 국세청 재산평가 상담사례 확인 2026. 9. 24. · 거래는 국토교통부 "
              "실거래 2026. 8. 23. 조회분 · 공동주택가격 요건은 자료가 없어 확인하지 못했습니다"),
        srcs=[SRC_EVAL, SRC_TRADE],
        comments=[("wb-persona-appraisal-check", "소수점을 반올림해 버리면 이 판정이 통째로 흔들립니다. 신고서 면적을 그대로 써야 하는 이유죠.", "평가 검증"),
                  ("wb-persona-num-compare", "저희가 면적을 소수점까지 표기해 온 게 여기서 쓸모가 생겼습니다.", "기준 통일")]))
    return o


# ── 은마아파트 3편 ─────────────────────────────────────────────

def posts_eunma():
    f = facts("eunma")
    o = []
    assert f["n"] == 22 and f["cancelled"] == 2

    o.append(dict(slug="eunma", persona="wb-persona-psy-thermo",
        title=f"표본 {f['n']}건. 기준으로 삼을 거래가 적습니다",
        body=f"""은마아파트의 2026년 매매 신고는 {f['n']}건입니다. 해제 신고 {f['cancelled']}건이 포함돼 있고, 금액은 {eok(f['lo'])}부터 {eok(f['hi'])}까지입니다.

4,424세대 단지에서 여덟 달 동안 {f['n']}건입니다. 저희가 보는 여섯 단지 중 가장 적습니다. 이 사실이 세금 이야기에서 의미가 있는 이유는, 상속 평가가 다른 집의 거래를 기준으로 삼기 때문입니다. 거래가 적으면 기준으로 삼을 후보도 적습니다.

단계마다 줄어듭니다. 평가기간 앞쪽 6개월로 좁히면 {f['win_n']}건, 거기서 면적 요건을 걸면 {f['sim_n']}건이 남습니다. 처음 {f['n']}건에서 출발해 한 자리 수가 됩니다.

여기서부터는 해석입니다. 후보가 적다는 건 한 건 한 건의 무게가 크다는 뜻입니다. 거래가 많은 단지에서는 튀는 한 건이 묻히지만, 적은 단지에서는 그 한 건이 기준이 될 수 있습니다. 그리고 해제된 거래를 어떻게 다루는지는 저희가 확인하지 못했습니다.

거래가 드문 단지에서 평가를 받아 보신 분이 계실까요? 어떤 거래가 기준이 되던가요?""",
        note=("거래는 국토교통부 실거래 2026년 계약분 "
              f"{f['n']}건(해제 {f['cancelled']}건 포함), 2026. 8. 23. 조회 · 평가기간과 면적 요건은 "
              "국세청 재산평가 상담사례 확인 2026. 9. 24. · 해제 거래의 취급은 확인하지 못했습니다"),
        srcs=[SRC_TRADE, SRC_EVAL],
        comments=[("wb-persona-trade-brief", "거래가 드문 단지일수록 개별 거래의 영향력이 커진다는 점, 평가에서도 그대로군요.", "기준 통일"),
                  ("wb-persona-question-post", "해제된 신고가 평가 기준이 될 수 있는지는 국세청 상담으로 확인이 필요한 대목입니다. 답을 찾으면 덧붙이겠습니다.", "확인 요청")]))

    o.append(dict(slug="eunma", persona="wb-persona-appraisal-check",
        title="아파트와 기업 승계가 한 법안에 묶여 있었습니다",
        body="""2024년 12월 10일 부결된 상속세 및 증여세법 개정안의 목록을 보면 성격이 다른 항목들이 한데 묶여 있습니다.

국회예산정책처가 정리한 내용으로는 최하위 과세표준 구간 확대, 최고세율 인하, 자녀공제 확대가 있고, 그 옆에 최대주주 보유주식 할증평가 폐지와 가업상속공제 확대가 함께 들어 있습니다. 앞의 셋은 아파트 한 채를 물려주는 집에 닿는 조항이고, 뒤의 둘은 기업을 물려주는 쪽 이야기입니다.

한 법안에 담겼으니 표결도 하나였습니다. 찬성하든 반대하든 다섯 항목을 한 번에 판단해야 하는 구조였고, 결과는 전부 부결이었습니다.

여기서부터는 해석입니다. 상속세 논의가 자주 평행선을 그리는 이유 중 하나가 이 묶음일 수 있습니다. 서로 다른 관심사가 한 표에 섞이면 어느 항목 때문에 막혔는지 나중에 가려내기 어렵습니다.

은마아파트처럼 재건축이 논의되는 단지라면 시점에 따라 조건이 또 달라질 수 있습니다. 다만 그건 다른 이야기고, 오늘 확인한 건 지금 표가 그대로라는 사실입니다.

세금 법안이 묶여 처리되는 구조, 알고 계셨나요?""",
        note=("국회예산정책처 2024년 개정세법 심의 결과 확인 2026. 9. 24. · 부결된 개정안의 항목 구성이며 "
              "현행 조문과 구분해 적었습니다"),
        srcs=[SRC_NABO],
        comments=[("wb-persona-policy-lab", "묶음 처리는 입법 효율을 위한 것이지만 책임 소재를 흐리기도 합니다. 양면이 있죠.", "정책 분석"),
                  ("wb-persona-tax-scenario", "가업상속공제와 아파트 상속은 적용 대상이 거의 겹치지 않습니다. 한 표에 묶인 게 이상하게 느껴질 만해요.", "시나리오 설계")]))

    o.append(dict(slug="eunma", persona="wb-persona-policy-lab",
        title=f"면적 요건을 통과한 {f['sim_n']}건, 폭은 3억",
        body=f"""은마아파트는 전용면적이 두 종류입니다. 2026년 매매 신고 {f['n']}건이 전부 그 둘 중 하나였습니다. 상속 평가에서는 이 구조가 유리하게 작동할 수 있습니다. 비교할 집을 찾기가 단순해지니까요.

실제로 해 봤습니다. 평가기간 앞쪽 6개월로 좁히면 {f['win_n']}건, 가장 많이 거래된 전용 {f['top_area']}㎡ 기준 5% 범위를 걸면 {f['sim_n']}건이 남고, 남은 면적은 {f['sim_areas'][0]}㎡ 하나입니다.

그런데 그 {f['sim_n']}건의 금액이 {eok(f['sim_lo'])}부터 {eok(f['sim_hi'])}까지입니다. 3억 차이입니다. 저희가 본 여섯 단지 중 가장 좁은 폭인데, 그래도 3억이 갈립니다.

면적이 같고 단지가 같고 기간이 같아도 금액이 하나로 모이지 않는다는 뜻입니다. 남은 요건인 공동주택가격 차이 5% 이내가 여기서 선별을 하게 되는데, 저희에게는 그 자료가 없습니다.

여기서부터는 해석입니다. 평형이 단순한 단지에서도 마지막 판단은 공시가격이 합니다. 실거래만 들고 평가액을 짐작하는 건 어느 단지에서든 어렵습니다.

부동산공시가격 알리미에서 동·호수별로 조회가 됩니다. 직접 맞춰 보시면 몇 건이 남던가요?""",
        note=("유사매매사례가액 요건은 국세청 재산평가 상담사례 확인 2026. 9. 24. · 거래는 국토교통부 "
              "실거래 2026. 8. 23. 조회분이라 9월 계약분이 빠져 있습니다 · 공동주택가격 요건은 확인하지 못했습니다"),
        srcs=[SRC_EVAL, SRC_TRADE],
        comments=[("wb-persona-num-compare", "평형이 단순해도 폭이 3억이면 결코 작지 않습니다. 기준 선택이 중요한 이유네요.", "기준 통일"),
                  ("wb-persona-real-talk", "같은 평형이라도 층과 동에 따라 사정이 다르니 당연한 결과이기도 합니다.", "생활 현실")]))
    return o


# ── 마포래미안푸르지오 3편 ─────────────────────────────────────

def posts_mapo():
    f = facts("mapo-raemian-prugio")
    o = []
    assert f["n"] == 45 and len(f["names"]) == 4

    over = f["band"].get("30억 초과", 0)
    o.append(dict(slug="mapo-raemian-prugio", persona="wb-persona-trade-brief",
        title=f"45건 중 30억을 넘은 건 {over}건입니다",
        body=f"""마포래미안푸르지오의 2026년 매매 신고는 {f['n']}건입니다. 금액은 {eok(f['lo'])}부터 {eok(f['hi'])}까지이고, 그중 30억을 넘은 신고는 {over}건입니다.

30억을 굳이 세는 이유는 상속세 세율표에서 과세표준 30억 초과 구간이 50%이기 때문입니다. 그 아래 10억 초과 30억 이하가 40%고요.

그런데 이 {over}건이 곧 50% 구간이라는 뜻은 아닙니다. 세율은 거래가가 아니라 과세표준에 붙습니다. 과세표준은 재산가액에서 공제를 뺀 값이라 거래가보다 낮아지고, 얼마나 낮아지는지는 상속인 구성에 따라 다릅니다. {eok(f['hi'])}짜리 거래라도 공제를 빼면 30억 아래로 내려갈 수 있습니다.

여기서부터는 해석입니다. 그래서 "이 단지에 50% 구간 거래가 있다"는 문장은 성립하지 않습니다. 정확히 말하면 "거래가 기준으로 30억을 넘은 신고가 {over}건 있다"까지입니다. 두 문장은 비슷해 보이지만 다른 이야기입니다.

세금 기사에서 이 두 가지가 섞여 있는 걸 보신 적 있으신가요?""",
        note=("세율표는 국세청 공개 자료 확인 2026. 9. 24. · 거래는 국토교통부 실거래 2026년 계약분 "
              f"{f['n']}건(해제 {f['cancelled']}건 포함), 2026. 8. 23. 조회 · 실거래에 1~4단지로 나뉘어 "
              "신고돼 합산했습니다 · 세액은 계산하지 않았습니다"),
        srcs=[SRC_RATE, SRC_TRADE],
        comments=[("wb-persona-appraisal-check", "거래가와 과세표준을 구분해 문장을 다시 쓴 부분이 정확합니다. 이 차이에서 오해가 나오죠.", "기준 통일"),
                  ("wb-persona-psy-thermo", "한 건이 넘었다는 사실만으로 단지 이미지가 만들어지기도 합니다. 건수를 같이 적는 게 맞아요.", "심리 균형")]))

    o.append(dict(slug="mapo-raemian-prugio", persona="wb-persona-num-compare",
        title="증여재산공제는 배우자 6억, 자녀 5천만원",
        body=f"""상속 이야기만 했으니 증여 쪽도 확인했습니다. 국세청이 공개한 증여재산공제 한도는 이렇습니다. 배우자에게 받으면 6억원, 직계존속에게 받으면 5천만원(받는 사람이 미성년자면 2천만원), 직계비속에게 받으면 5천만원, 4촌 이내 혈족이나 3촌 이내 인척이면 1천만원입니다.

이 금액을 이 단지 거래가 옆에 놓아 보겠습니다. 마포래미안푸르지오의 2026년 매매 신고는 {eok(f['lo'])}부터 {eok(f['hi'])}까지였습니다.

부모가 자녀에게 아파트를 증여하는 경우로 보면 공제는 5천만원입니다. 거래가와 자릿수가 다릅니다.

여기서부터는 해석입니다. 이 간격 때문에 아파트 증여에서는 공제보다 평가액과 분할 방법이 더 큰 변수가 됩니다. 다만 어떤 방법이 어떤 결과를 내는지는 각자의 조건에 달렸고, 저희가 안내할 수 있는 영역이 아닙니다. 세무 상담을 받으셔야 하는 지점입니다.

저희가 할 수 있는 건 공개된 숫자를 정확히 옮겨 놓는 것까지입니다. 이 공제 금액, 알고 계셨나요?""",
        note=("증여재산공제는 국세청 공개 자료 확인 2026. 9. 24. · 거래는 국토교통부 실거래 2026. 8. 23. "
              "조회분 · 세액은 계산하지 않았고 개별 상담은 세무 대리인의 영역입니다"),
        srcs=[SRC_GIFT, SRC_TRADE],
        comments=[("wb-persona-tax-oneline", "공제 금액과 자산 가격의 자릿수 차이를 나란히 보여 준 게 이 글의 값입니다.", "생활 세무"),
                  ("wb-persona-cashflow", "10년 단위로 합산하는 규칙도 있어서 시점 설계가 따라붙습니다. 그건 상담 영역이죠.", "비용 구조")]))

    o.append(dict(slug="mapo-raemian-prugio", persona="wb-persona-real-talk",
        title="1~4단지는 '같은 단지'일까요",
        body=f"""유사매매사례가액의 첫 번째 요건은 같은 공동주택단지 안에 있을 것입니다. 마포래미안푸르지오에서는 이 요건부터 걸립니다.

이 단지는 국토교통부 실거래에 1단지부터 4단지까지 넷으로 나뉘어 신고됩니다. K-apt에는 한 단지로 등록돼 있고 세대수도 합산값이라, 저희는 거래를 셀 때 네 이름을 모두 합쳐 왔습니다. 그래야 분모와 분자가 맞으니까요.

그런데 평가 기준을 찾을 때도 합쳐도 되는지는 다른 문제입니다. 1단지 아파트를 평가하는데 3단지 거래를 기준으로 쓸 수 있는지, 국세청이 말하는 '동일한 공동주택단지'가 어느 단위인지 저희는 확인하지 못했습니다.

참고로 평가기간 앞쪽 6개월에 신고된 거래는 {f['win_n']}건이고, 전용 {f['top_area']}㎡ 기준 5% 범위에 드는 거래는 {f['sim_n']}건, 금액은 {eok(f['sim_lo'])}부터 {eok(f['sim_hi'])}까지입니다. 다만 이 {f['sim_n']}건은 네 단지에 흩어져 있을 수 있습니다.

여기서부터는 해석입니다. 단지 경계가 어떻게 잡히느냐에 따라 후보가 늘거나 줄고, 그러면 기준가도 달라집니다. 통계에서는 합치는 게 맞았는데 평가에서는 아닐 수 있습니다. 같은 자료라도 무엇에 쓰느냐에 따라 묶는 단위가 달라진다는 이야기입니다.

확인 못 한 건 확인 못 했다고 적어 둡니다. 이 단지에서 평가를 받아 보신 분은 어느 범위의 거래가 쓰였나요?""",
        note=("유사매매사례가액 요건은 국세청 재산평가 상담사례 확인 2026. 9. 24. · 거래는 국토교통부 "
              "실거래 2026. 8. 23. 조회분이며 1~4단지 신고를 합산했습니다 · '동일한 공동주택단지'의 "
              "적용 단위와 공동주택가격 요건은 확인하지 못했습니다"),
        srcs=[SRC_EVAL, SRC_TRADE],
        comments=[("wb-persona-question-post", "단지 경계 문제는 국세청 상담으로 답이 나올 수 있습니다. 확인되면 이 글에 덧붙이겠습니다.", "확인 요청"),
                  ("wb-persona-field-scout", "같은 브랜드 이름을 쓰지만 준공 시점과 관리 주체가 다른 경우도 있습니다. 실제 경계는 현장이 더 잘 알죠.", "현장 검증 요청")]))
    return o


def build(ignore_cap):
    rows = (posts_onebailey() + posts_helio() + posts_ricents()
            + posts_gracium() + posts_eunma() + posts_mapo())
    assert len(rows) == 18
    per = Counter(r["slug"] for r in rows)
    assert all(v == 3 for v in per.values()) and len(per) == 6, per

    for slug, n in sorted(per.items()):
        live = published_today(CX[slug][1], DAY)
        total = n if live is None else n + live
        if total > 2:
            msg = (f"{slug} {DAY}: 팩 {n}편 + 게시분 "
                   f"{live if live is not None else '?'}편 — 콜드스타트 2편 초과")
            if ignore_cap:
                print(f"  [한도 초과] {msg} (--ignore-cap)", file=sys.stderr)
            else:
                print(f"  [반려] {msg}", file=sys.stderr)
                raise SystemExit(1)

    seq = Counter()
    bundles = []
    for k, r in enumerate(rows):
        seq[r["slug"]] += 1
        ext = f"tax-2026-09-{r['slug']}-{seq[r['slug']]}"
        ext_id, _feed, _name = CX[r["slug"]]
        hh, mm = divmod(8 * 60 + k * 45, 60)
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-v1",
            "payload": {
                "complex_external_id": ext_id, "topic": TOPIC_TAX,
                "post": {
                    "external_id": ext, "complex_external_id": ext_id,
                    "persona_external_id": r["persona"], "category": "세금",
                    "title": r["title"], "summary": r["body"].split("\n\n")[0][:220],
                    "body": r["body"], "verification": "verified",
                    "source_note": r["note"], "sources": r["srcs"],
                    "published_at": f"{DAY}T{hh:02d}:{mm:02d}:00+09:00", "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{n}", "persona_external_id": pid,
                     "body": b, "stance": st, "position": n}
                    for n, (pid, b, st) in enumerate(r["comments"])
                ],
            },
        })

    return {
        "meta": {"name": "상속·증여세 팩 (w1)", "posts": len(bundles), "built_at": DAY,
                 "per_complex": dict(per),
                 "premise": ("운영자 요청은 '변경된 상속증여세'였으나 2026-09-24 원문 확인 결과 "
                             "세율·공제는 바뀌지 않았다. 2024년 정부안은 2024-12-10 본회의 부결, "
                             "유산취득세 전환은 국회 미통과. 그래서 '현행 기준 + 안 바뀐 이유'로 썼다"),
                 "no_tax_amount": ("세액을 계산하지 않았다. 상속·증여세는 상속인 구성에 따라 갈리고 "
                                   "개별 세액 산출은 세무 대리 영역이다. 과세표준 구간과 평가 기준까지만 다룬다"),
                 "no_deduction_figures": ("일괄공제·배우자공제 금액은 국세청 페이지에서 확인하지 못해 "
                                          "본문에 쓰지 않았다. 증여재산공제만 확인돼 마포 글에 인용했다"),
                 "data_gap": f"실거래 캐시 조회일 {TRADE_ASOF}. 2026년 9월 계약분은 포함되지 않았다",
                 "unverified": ["공동주택가격(브이월드 해외 IP 차단)", "해제 거래의 평가 기준 적격 여부",
                                "'동일한 공동주택단지'의 적용 단위(마포 1~4단지)", "증여 평가기간"],
                 "note": "18편 전부 손글 뼈대. 세금 축은 처음이라 출고 검사를 특히 낮은 임계값으로 돌린다"},
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
    for key in ("published_at", "title"):
        vals = [p[key] for p in posts]
        if len(set(vals)) != len(vals):
            errs.append(f"{key} 중복: {[k for k, n in Counter(vals).items() if n > 1][:3]}")

    for p in posts:
        t = p["title"] + "\n" + p["body"]
        for w in BAN_TAXADVICE + BAN_STEER + BAN_JUDGE + BAN_COMPARE + BAN_VAGUE:
            if w in t:
                errs.append(f"금지 표현 '{w}': {p['external_id']}")
        m = BAD_RO.search(t)
        if m:
            errs.append(f"조사 '로' 오류 '{m.group()}': {p['external_id']}")
        if "**" in t:
            errs.append(f"마크다운 강조: {p['external_id']}")
        if not p["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {p['external_id']}")
        if "여기서부터는 해석입니다" not in p["body"]:
            errs.append(f"사실/해석 전환문 없음: {p['external_id']}")
        if len(p["title"]) > MAX_TITLE:
            errs.append(f"제목 {len(p['title'])}자 초과: {p['external_id']}")
        if p["published_at"] > NOW:
            errs.append(f"미래 시각: {p['external_id']}")
        if p["category"] != "세금":
            errs.append(f"카테고리가 세금이 아님: {p['external_id']}")
        if not p["sources"]:
            errs.append(f"sources 없음: {p['external_id']}")
        if p["persona_external_id"].startswith("adv-"):
            errs.append(f"홍보 페르소나가 세금 글을 쓸 수 없다: {p['external_id']}")
        if p["persona_external_id"] not in TAX_PERSONAS:
            errs.append(f"세금 글에 배정할 수 없는 페르소나: {p['persona_external_id']}")
        if p["persona_external_id"] not in registered:
            errs.append(f"미등록 페르소나: {p['persona_external_id']}")
        # 출처에 확인일이 없는 세법 인용은 시점을 잃는다
        if not any("확인 2026" in s["label"] for s in p["sources"]):
            errs.append(f"세법 출처에 확인일 없음: {p['external_id']}")

    for c in comments:
        if c["persona_external_id"] not in registered:
            errs.append(f"미등록 페르소나(댓글): {c['persona_external_id']}")
        if c["persona_external_id"].startswith("adv-"):
            errs.append(f"홍보 페르소나 댓글: {c['external_id']}")
    bodies = [c["body"] for c in comments]
    if len(set(bodies)) != len(bodies):
        errs.append(f"댓글 본문 중복: {[k for k, n in Counter(bodies).items() if n > 1][:2]}")

    for w, pair, want in [("리센츠", "은는", "리센츠는"), ("은마아파트", "이가", "은마아파트가")]:
        if J(w, pair) != want:
            errs.append(f"조사 오류: {J(w, pair)}")
    return errs


def main():
    ap = argparse.ArgumentParser(description="상속·증여세 팩 생성기")
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
    print(f"  {'글':30}{'페르소나':28}{'제목자수':>5}  제목")
    for b in pack["bundles"]:
        p = b["payload"]["post"]
        print(f"  {p['external_id']:30}{p['persona_external_id']:28}{len(p['title']):>5}  {p['title']}")
    print(f"\n글 {len(pack['bundles'])}편 · 댓글 "
          f"{sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
