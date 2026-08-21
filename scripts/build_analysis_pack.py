#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""분석 글 생성기 — 가격·정책을 다루되 기준을 반드시 붙인다.

왜 따로 두나
  홍보·특이값 생성기는 금지 어휘에 '억'·'시세'가 들어 있다. 홍보 페르소나가
  가격을 말하면 시세 부양으로 읽히기 때문이다(명세 7.2.1).
  반면 분석 페르소나는 실거래를 인용할 수 있다. 대신 CLAUDE.md 4장의
  "숫자에는 기준을 붙인다"를 어기면 안 된다 — 금액만 던지는 글은 여기서도 못 나간다.

이 팩이 지키는 선
  - 담합 유도·매수/매도 지시·전망 단정 금지. 검증기가 막는다
  - 단지 간 우열 비교 금지. 이 팩은 한 단지 안에서만 이야기한다
  - 모든 수치는 우리가 조회한 원자료에서 나온다. 언론·커뮤니티 인용은 쓰지 않는다

서모스탯 (명세 6.3)
  단지당 하루 2편이 한도다. **팩 안에서만 세면 안 된다** — 실제로 2026-08-18에
  원베일리가 서로 다른 팩에서 3편 나갔다. 그래서 이 생성기는 게시된 피드를
  조회해 그날 이미 몇 편 나갔는지 확인하고 합산해서 판정한다.

실행: python3 scripts/build_analysis_pack.py
"""

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "content" / "analysis-w1.json"
OUT_R2 = REPO / "content" / "analysis-w2.json"
FEE_DIR = REPO / "data" / "mgmt-fees"
TRADE_2026 = REPO / "data" / "trades" / "one-bailey-2026.json"
INFO_DIR = REPO / "data" / "complex-info"
BASE = os.environ.get("BASE_URL", "https://danji.life")
NOW = "2026-08-21T23:50:00+09:00"
DAY = NOW[:10]

CX = {"one-bailey": "cx-one-bailey"}

SRC_TRADE = {"label": "국토교통부 아파트 매매 실거래가 상세 자료",
             "url": "https://www.data.go.kr/data/15126469/openapi.do", "publisher": "국토교통부"}
SRC_FEE = {"label": "공동주택 관리비 서비스(K-apt) OpenAPI",
           "url": "https://www.data.go.kr/data/15057937/openapi.do", "publisher": "국토교통부"}
SRC_BASIS = {"label": "공동주택 기본 정보제공 서비스(K-apt) OpenAPI",
             "url": "https://www.data.go.kr/data/15058453/openapi.do", "publisher": "국토교통부"}

TOPIC = {"external_id": "wb-topic-2026-08-basis", "title": "숫자에는 기준이 붙어야 합니다",
         "summary": "같은 거래도 무엇으로 나누느냐에 따라 달라진다. 원자료로 확인한다",
         "category": "거래", "heat": 5}

# 분석 글에도 넘지 않는 선이 있다. 가격은 쓰되 이것들은 못 쓴다.
BAN_STEER = ["얼마 이하로", "내놓지 마", "지금 사", "지금 파", "매수 추천", "매도 추천",
             "사야 합니다", "팔아야 합니다", "오를 겁니다", "내릴 겁니다", "전망합니다"]
BAN_JUDGE = ["최악", "꼴찌", "우수", "열등", "압도", "명문", "상위권", "학군지"]
BAN_COMPARE = ["보다 낫", "보다 좋", "보다 우수"]
BAN_VAGUE = ["인터넷에서", "알려져 있", "라고 한다", "찾아보니", "카페에서", "커뮤니티에서"]


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


def won(manwon):
    """만원 단위를 읽는 형태로 바꾼다.

    900,000만원 은 사람이 쓰는 말이 아니다. 90억원이라고 써야 읽힌다.
    CLAUDE.md 4장이 금지하는 건 금액 자체가 아니라 기준 없는 금액이다 —
    예시도 "7월 6일 계약, 전용 116.95㎡ 25층 기준 90억"이다.
    """
    m = round(manwon)
    eok, rest = divmod(m, 10_000)
    if eok and rest:
        return f"{eok}억 {rest:,}만원"
    if eok:
        return f"{eok}억원"
    return f"{rest:,}만원"


def published_today(cx_ext, day):
    """그날 이미 게시된 편수를 서버에서 센다.

    팩 안에서만 세면 팩 사이를 넘는 초과를 못 잡는다. 2026-08-18 에
    원베일리가 outlier3 1편 + nearby 2편으로 3편 나간 적이 있다.
    """
    slug = [s for s, e in CX.items() if e == cx_ext][0]
    try:
        req = urllib.request.Request(f"{BASE}/api/v1/posts?complex={slug}&limit=100",
                                     headers={"User-Agent": "danji-content-agent/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            items = json.load(r)["items"]
    except Exception as exc:  # noqa: BLE001
        print(f"[주의] 피드 조회 실패로 서모스탯을 확인하지 못했습니다: {exc}", file=sys.stderr)
        return None
    return sum(1 for i in items if (i.get("published_at") or "").startswith(day))


def oku(manwon):
    """제목용 짧은 억 표기. 60억 3,000만원 → 60.3억. 본문은 won() 을 그대로 쓴다."""
    v = manwon / 10000
    return f"{v:.1f}억".replace(".0억", "억")


def build_r2():
    """운영자가 올린 원베일리 심층 리포트를 원자료와 맞춰 보고 쓴 글 3편.

    리포트 자체를 인용하지 않는다. 거기 실린 후기 41건은 호갱노노·당근·블라인드
    출처라 명세 9.6.3이 원문·닉네임·URL 저장을 금지하고, 하자 규모 같은 수치는
    소송이 걸린 사안이라 확인이 안 된다. 쓸 수 있는 건 리포트가 가리킨 항목을
    **우리가 원자료로 다시 조회한 값**뿐이다.
    """
    i = json.loads((INFO_DIR / "one-bailey.json").read_text(encoding="utf-8"))
    name = i["complex_name"]
    ratio = i["billed_area_m2"] / i["private_area_sum_m2"]
    rows = json.loads(TRADE_2026.read_text(encoding="utf-8"))["deals"]
    fee = json.loads((FEE_DIR / "one-bailey.json").read_text(encoding="utf-8"))["periods"]["202605"]
    bd = fee["breakdown"]

    n = len(rows)
    cancelled = sum(1 for r in rows if r["cancel"])
    mo = Counter(r["deal_date"][:7] for r in rows)
    peak_m, peak_n = max(mo.items(), key=lambda kv: kv[1])
    by_amt = sorted(rows, key=lambda r: r["amount_manwon"])
    lo, hi = by_amt[0], by_amt[-1]
    second = [r for r in rows if r["area_m2"] > 160 and r is not hi]
    g = sorted([r for r in rows if 84.5 <= r["area_m2"] < 85.5], key=lambda r: r["amount_manwon"])
    glo, ghi = g[0], g[-1]
    bands = Counter(round(r["area_m2"]) for r in rows)

    def dt(r):
        y, m, d = r["deal_date"].split("-")
        return f"{int(m)}월 {int(d)}일"

    body1 = f"""2026년 들어 국토교통부에 신고된 {name} 매매 계약을 계약일 순으로 전부 세어 봤습니다. {n}건입니다. 해제 신고는 {'한 건도 없습니다' if not cancelled else f'{cancelled}건입니다'}.

월별로는 1월 {mo['2026-01']}건, 2월 {mo['2026-02']}건, 3월 {mo.get('2026-03', 0)}건, 4월 {mo['2026-04']}건, 5월 {mo['2026-05']}건, 6월 {mo['2026-06']}건, 7월 {mo['2026-07']}건입니다. 절반이 넘는 {peak_n}건이 {int(peak_m[5:])}월 한 달에 몰려 있습니다.

금액이 가장 낮은 신고는 {dt(lo)} 계약, 전용 {lo['area_m2']}㎡ {lo['floor']}층 {won(lo['amount_manwon'])}입니다. 가장 높은 신고는 {dt(hi)} 계약, 전용 {hi['area_m2']}㎡ {hi['floor']}층 {won(hi['amount_manwon'])}이고요. 사흘 뒤인 {dt(second[0])}에도 전용 {second[0]['area_m2']}㎡ {second[0]['floor']}층이 {won(second[0]['amount_manwon'])}에 신고됐습니다.

면적별로는 전용 85㎡대가 {bands[85]}건으로 가장 많습니다. 그다음이 60㎡대 {bands[60]}건, 102㎡대 {bands[102]}건이고 117·134·169㎡대가 각각 {bands[117]}건씩, 75㎡대가 {bands[75]}건입니다.

여기서부터는 해석입니다. {int(peak_m[5:])}월에 몰린 이유는 이 자료만으로 알 수 없습니다. 실거래는 계약일 기준으로 집계하고 신고 기한이 30일이라 최근 달은 아직 덜 찬 상태이기도 합니다. 7월 {mo['2026-07']}건이 최종 수치가 아니라는 뜻이죠.

정리된 표를 보실 때는 빠진 건이 없는지도 같이 보시면 좋겠습니다. 이 {n}건 가운데 직접 지켜보신 거래가 있으신가요?"""

    title1 = f"올해 신고 {n}건 중 {peak_n}건이 {int(peak_m[5:])}월에 몰렸습니다"

    up = [r for r in g if int(r["floor"]) >= 30][0]
    down = [r for r in g if int(r["floor"]) <= 6 and r["amount_manwon"] > up["amount_manwon"]][0]
    body2 = f"""같은 단지 같은 면적이면 값도 비슷할 것 같지만, 올해 신고분에서 전용 85㎡대만 떼어 보면 그렇지 않습니다.

국토교통부 실거래 신고에서 2026년 계약분 중 전용 {glo['area_m2']}㎡부터 {ghi['area_m2']}㎡ 사이가 {len(g)}건입니다. 가장 낮은 신고는 {dt(glo)} 계약 {glo['floor']}층 {won(glo['amount_manwon'])}, 가장 높은 신고는 {dt(ghi)} 계약 {ghi['floor']}층 {won(ghi['amount_manwon'])}입니다. 같은 면적 안에서 {won(ghi['amount_manwon'] - glo['amount_manwon'])}이 벌어집니다.

층 순서와 금액 순서도 맞지 않습니다. {dt(up)} 계약 {up['floor']}층은 {won(up['amount_manwon'])}, {dt(down)} 계약 {down['floor']}층은 {won(down['amount_manwon'])}입니다. {int(up['floor']) - int(down['floor'])}개 층 차이를 뒤집는 신고가 같은 해 안에 함께 있습니다. 같은 {down['floor']}층끼리도 {dt(glo)}과 {dt(down)}이 {won(down['amount_manwon'] - glo['amount_manwon'])} 차이고요.

여기서부터는 해석입니다. 신고서에는 향도, 동도, 수리 상태도, 거래 사정도 적히지 않습니다. 층 하나만 놓고 값을 견주기 어려운 이유입니다. 계약일도 넉 달 가까이 벌어져 있고요.

그래서 이 단지 숫자를 인용할 때는 계약일과 전용면적과 층을 함께 붙여야 합니다. 셋이 없으면 서로 다른 집 이야기를 하고 있을 수 있습니다.

{len(g)}건 중 어느 거래가 이 단지를 대표하는 값으로 통하고 있나요?"""

    title2 = (f"{down['floor']}층 {oku(down['amount_manwon'])}, "
              f"{up['floor']}층 {oku(up['amount_manwon'])}. 같은 84㎡")

    ex = 84.98
    billed = ex * ratio
    total_per_m2 = bd["합계"]["per_m2_won"]
    est = round(billed * total_per_m2 / 1000) * 1000
    body3 = f"""관리비가 한 달에 얼마냐는 질문에, 공개 자료로 어디까지 답할 수 있는지부터 적겠습니다.

공공데이터포털 OpenAPI로 받은 2026년 5월분 공용관리비 총액은 {won(fee['common_fee_total_won'] / 10000)}입니다. 관리비 부과면적 {fee['area_m2']:,.0f}㎡로 나누면 ㎡당 {fee['per_m2_won']:,.0f}원입니다. 여기까지가 공식 조회분입니다.

K-apt 공개 자료에는 같은 달 개별사용료 {won(bd['개별사용료']['total_won'] / 10000)}(㎡당 {bd['개별사용료']['per_m2_won']:,}원)과 장기수선충당금 {won(bd['장기수선충당금']['total_won'] / 10000)}(㎡당 {bd['장기수선충당금']['per_m2_won']:,}원)이 함께 실려 있습니다. 공용관리비 값은 공식 조회분과 원 단위까지 같았습니다. 셋을 더하면 ㎡당 {total_per_m2:,}원입니다.

전용 {ex}㎡ 한 세대로 환산해 보겠습니다. {J(name, '은는')} 부과면적이 전용의 {ratio:.2f}배라 부과 기준으로는 {billed:.1f}㎡입니다. 여기에 ㎡당 {total_per_m2:,}원을 곱하면 {est:,}원쯤 나옵니다.

여기서부터는 해석입니다. 이 값은 단지 전체를 평균한 단가로 되짚은 것이라 개별 고지서와 다릅니다. 개별사용료는 세대마다 쓴 만큼 붙고 계절을 크게 탑니다. 5월은 냉난방이 적게 드는 달이고요. 어느 달을 집었느냐로 답이 달라집니다.

공용관리비 항목과 총액을 나눠 적어 주시면 이 계산이 어디서 벌어지는지 맞춰 보겠습니다. 지금 손에 든 고지서에는 얼마가 찍혀 있나요?"""

    man = f"{est // 10000}만 {est % 10000 // 1000}천원" if est % 10000 else f"{est // 10000}만원"
    title3 = f"전용 85㎡ 환산 {man}. 고지서와 다른 이유"

    note_trade = ("2026. 8. 21. 조회 · 국토교통부 실거래 2026년 1~7월 계약분 "
                  f"{n}건을 계약일 기준으로 직접 집계")
    return [
        ("deals-2026-08-one-bailey-year", title1, body1, "wb-persona-trade-brief", "거래",
         [SRC_TRADE], note_trade, f"{DAY}T23:05:00+09:00",
         [("wb-persona-policy-lab", "한 달에 몰린 신고는 계약일 분포일 뿐입니다. 그달에 무슨 일이 있었는지는 따로 봐야 합니다.", "정책 분석"),
          ("wb-persona-real-talk", "건수가 적은 달은 한두 건이 전체 인상을 정합니다. 표본 크기를 먼저 보는 습관이 필요해요.", "생활 현실")]),
        ("deals-2026-08-one-bailey-84", title2, body2, "wb-persona-appraisal-check", "거래",
         [SRC_TRADE], note_trade, f"{DAY}T23:20:00+09:00",
         [("wb-persona-trade-brief", "같은 면적 안의 폭이 이 정도면, 대표값 하나로 줄이는 순간 정보가 사라집니다.", "기준 통일"),
          ("wb-persona-cashflow", "층과 향은 관리비에도 영향을 줍니다. 값만 놓고 비교하기 어려운 이유가 하나 더 있는 셈이죠.", "비용 구조")]),
        ("fee-2026-08-one-bailey-bill", title3, body3, "wb-persona-cashflow", "생활",
         [SRC_FEE, SRC_BASIS],
         "2026년 5월분 · 공용관리비는 공공데이터포털 OpenAPI 공식 조회분 · "
         "개별사용료와 장기수선충당금은 K-apt 공개 자료 값 · 부과면적 환산은 직접 계산",
         f"{DAY}T23:35:00+09:00",
         [("wb-persona-real-talk", "평균 단가로 되짚은 값과 실제 고지서가 벌어지는 폭이 궁금합니다. 그 차이가 곧 세대별 사용량이니까요.", "생활 현실"),
          ("wb-persona-appraisal-check", "부과면적과 전용면적을 섞으면 관리비 단가도 가격처럼 어긋납니다. 여기서도 분모를 밝혀 뒀습니다.", "기준 통일")]),
    ]


def build(rn=1):
    if rn == 2:
        return assemble(build_r2(), rn)
    i = json.loads((INFO_DIR / "one-bailey.json").read_text(encoding="utf-8"))
    name = i["complex_name"]
    priv, marea, hh = i["private_area_sum_m2"], i["billed_area_m2"], i["household_count"]
    ratio = marea / priv

    # 2026-07-06 계약, 전용 116.95㎡ 25층, 90억. 국토부 실거래 신고 원자료.
    amt_manwon, area = 900_000, 116.95
    per_excl = amt_manwon / area * 3.3058
    eq_area = area * ratio
    per_billed = amt_manwon / eq_area * 3.3058

    body1 = f"""부동산 이야기에서 평당가는 거의 매번 등장하는데, 무엇으로 나눈 값인지는 잘 안 붙습니다. 그래서 한 건을 놓고 직접 나눠 봤습니다.

국토교통부 실거래 신고 기준으로 2026년 7월 6일 계약, 전용 {area}㎡ 25층이 {won(amt_manwon)}에 거래됐습니다. 이 금액을 전용면적으로 나누면 평당 {won(per_excl)}입니다.

그런데 같은 집을 부르는 면적이 하나가 아닙니다. K-apt 공개정보에서 {J(name, '은는')} 전용면적 합계 {priv:,.1f}㎡, 관리비 부과면적 {marea:,.1f}㎡로 등록돼 있습니다. 부과면적이 전용면적의 {ratio:.2f}배입니다. 세대로 나누면 평균 전용 {priv/hh:.1f}㎡, 평균 부과 {marea/hh:.1f}㎡가 됩니다.

이 비율로 아까 그 거래를 환산하면 {eq_area:.1f}㎡가 되고, 평당가는 {won(per_billed)}으로 내려앉습니다. 같은 계약, 같은 금액인데 평당 {won(per_excl)}과 {won(per_billed)}이 함께 나옵니다.

여기서부터는 해석입니다. 둘 중 틀린 값은 없습니다. 분모가 다를 뿐이죠. 문제는 기준을 밝히지 않은 평당가가 돌아다닐 때 생깁니다. 전용 기준끼리 비교해야 할 자리에 공급이나 부과 기준 값이 섞여 들어오면, 비교 자체가 성립하지 않습니다. 저희가 예측 정산 규칙에서 전용면적 기준을 못 박아 둔 이유도 이것입니다.

어디선가 들으신 이 단지 평당가는 어느 면적 기준이던가요? 기준을 물어보셨을 때 바로 답을 들으셨나요?"""

    title1 = f"평당 {won(per_excl)}과 {won(per_billed)}. 같은 거래"

    # 2024-01~2026-07 국토부 신고 176건을 월별로 집계한 결과다.
    body2 = f"""토지거래허가구역 재지정이 거래를 줄였다는 이야기는 자주 나오는데, 이 단지에서 실제로 얼마나 줄었는지는 세어 보면 알 수 있습니다.

국토교통부 실거래 신고 자료에서 {name} 계약을 2024년 1월부터 2026년 7월까지 모으면 176건입니다. 재지정 시행일은 2025년 3월 24일입니다.

시행 직전 12개월(2024년 4월~2025년 3월)은 104건, 월 평균 8.7건입니다. 직후 12개월(2025년 4월~2026년 3월)은 27건, 월 평균 3.9건입니다. 신고가 한 건도 없는 달이 다섯 번 있었습니다.

여기서부터는 해석입니다. 줄어든 건 분명한데, 허가제 하나 때문이라고 단정할 수는 없습니다. 같은 기간에 대출 한도를 조이는 대책도 있었고, 실거래는 신고일이 아니라 계약일 기준이라 최근 달은 아직 덜 찬 상태로 보입니다. 거래가 줄었다는 사실과 무엇이 줄였는지는 다른 이야기입니다.

숫자로 확인되지 않는 대목이 하나 더 있습니다. 허가를 실제로 신청하면 무엇을 준비해야 하고 며칠이 걸리는지는 어느 통계에도 없습니다. 밟아 보신 분이 계시면 그 과정이 어땠는지 알려 주시겠어요?"""

    title2 = "허가구역 뒤 거래가 월 8.7건에서 3.9건으로"

    specs = [
        ("basis-2026-08-one-bailey", title1, body1, "wb-persona-appraisal-check", "거래",
         [SRC_TRADE, SRC_BASIS],
         "2026. 8. 21. 조회 · 국토교통부 실거래 신고 원자료와 K-apt 공개정보로 직접 계산한 값",
         f"{DAY}T09:30:00+09:00",
         [("wb-persona-trade-brief", "기준을 안 밝힌 평당가는 비교에 쓸 수 없습니다. 표를 만들 때 제일 먼저 통일해야 하는 항목이에요.", "기준 통일"),
          ("wb-persona-cashflow", "관리비는 부과면적으로 매겨집니다. 같은 면적 이름이 가격과 관리비에서 다르게 쓰인다는 점도 같이 보셔야 합니다.", "비용 구조")]),
        ("permit-2026-08-one-bailey", title2, body2, "wb-persona-trade-brief", "정책",
         [SRC_TRADE],
         "2026. 8. 21. 조회 · 국토교통부 실거래 2024년 1월~2026년 7월 계약분 176건을 월별로 집계",
         f"{DAY}T14:10:00+09:00",
         [("wb-persona-policy-lab", "제도 시행 전후 비교는 다른 변수가 겹치면 인과가 흐려집니다. 같은 시기 대출 규제를 함께 놓고 봐야 합니다.", "정책 분석"),
          ("wb-persona-real-talk", "거래가 줄면 남은 몇 건이 전체를 대표하게 됩니다. 표본이 작아진다는 점도 같이 봐야 해요.", "생활 현실")]),
    ]

    return assemble(specs, 1)


def assemble(specs, rn):
    """봉투는 라운드가 달라도 같다. 값 만드는 방식만 다르다."""
    bundles = []
    for ext, title, body, persona, cat, srcs, note, pub, cmts in specs:
        bundles.append({
            "idempotency_key": f"wb-bundle-{ext}-v1",
            "payload": {
                "complex_external_id": CX["one-bailey"],
                "topic": dict(TOPIC, category=cat),
                "post": {
                    "external_id": ext, "complex_external_id": CX["one-bailey"],
                    "persona_external_id": persona, "category": cat,
                    "title": title, "summary": body.split("\n\n")[1][:220], "body": body,
                    "verification": "verified", "source_note": note, "sources": srcs,
                    "published_at": pub, "status": "published",
                },
                "comments": [
                    {"external_id": f"{ext}-c{n}", "persona_external_id": pid,
                     "body": b, "stance": st, "position": n}
                    for n, (pid, b, st) in enumerate(cmts)
                ],
            },
        })
    meta = {"name": f"분석 팩 (w{rn})", "round": rn, "posts": len(bundles), "built_at": DAY,
            "complex": "one-bailey",
            "purpose": "가격·정책을 다루되 기준을 붙인다. 수치는 전부 원자료에서 계산했다",
            "note": "홍보 페르소나는 이 팩에 쓰지 않는다. 가격을 말하는 순간 시세 부양으로 읽힌다"}
    if rn == 2:
        meta["source_of_topics"] = (
            "운영자가 올린 원베일리 심층 리포트가 가리킨 항목을 원자료로 다시 조회해서 썼다. "
            "리포트 본문과 후기 41건은 인용하지 않는다 — 명세 9.6.3")
        meta["report_crosscheck"] = {
            "일치": ["2026-06-12 168.93㎡ 13층 130억", "2026-05-23 133.95㎡ 29층 105.5억",
                     "2026-02-06 59.96㎡ 49.5억"],
            "불일치": ["51.2억(74.92㎡)의 계약일은 2026-05-29 가 아니라 2026-05-01"],
            "누락": ["2026-06-15 168.87㎡ 9층 122억"],
            "검증 불가": ["공시가 45억 6,900만원과 보유세 2,855만원 — 브이월드가 해외 IP 차단이라 못 봤다",
                          "하자 약 600가구 — 소송 계류 사안이고 원자료가 없다",
                          "시가총액 158조 — 2,990세대 기준으로 자릿수가 맞지 않는다"],
        }
    return {"meta": meta, "personas": [], "bundles": bundles}


def validate(pack, ignore_cap=False):
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    comments = [c for b in pack["bundles"] for c in b["payload"]["comments"]]
    reg = {"wb-persona-appraisal-check", "wb-persona-trade-brief", "wb-persona-cashflow",
           "wb-persona-policy-lab", "wb-persona-real-talk"}

    ids = [p["external_id"] for p in posts] + [c["external_id"] for c in comments]
    if len(set(ids)) != len(ids):
        errs.append("external_id 중복")
    if len({p["published_at"] for p in posts}) != len(posts):
        errs.append("published_at 중복")

    for p in posts:
        t = p["title"] + "\n" + p["body"]
        for w in BAN_STEER + BAN_JUDGE + BAN_COMPARE + BAN_VAGUE:
            if w in t:
                errs.append(f"금지 표현 '{w}': {p['external_id']}")
        if "**" in t:
            errs.append(f"마크다운 강조는 렌더링되지 않는다: {p['external_id']}")
        if not p["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {p['external_id']}")
        if "여기서부터는 해석입니다." not in p["body"]:
            errs.append(f"사실/해석 전환 문장 없음: {p['external_id']}")
        if p["verification"] == "verified" and not p["sources"]:
            errs.append(f"verified인데 sources 없음: {p['external_id']}")
        if p["published_at"] > NOW:
            errs.append(f"미래 시각: {p['external_id']}")
        if p["persona_external_id"] not in reg:
            errs.append(f"미등록 페르소나: {p['persona_external_id']}")
        if p["persona_external_id"].startswith("adv-"):
            errs.append(f"홍보 페르소나가 가격 글을 쓸 수 없다: {p['external_id']}")
        # 제목은 공유 카드에 2줄로 그려진다. 34자를 넘으면 잘리거나 3줄이 된다.
        if len(p["title"]) > 34:
            errs.append(f"제목 {len(p['title'])}자 — 공유 카드 2줄을 넘는다: {p['external_id']}")
    for c in comments:
        if c["persona_external_id"] not in reg:
            errs.append(f"미등록 페르소나: {c['persona_external_id']}")

    # 서모스탯 — 이 팩 + 이미 게시된 그날 편수를 합산해서 본다
    per = Counter((p["complex_external_id"], p["published_at"][:10]) for p in posts)
    for (cx, day), n in per.items():
        live = published_today(cx, day)
        total = n if live is None else n + live
        if total > 2:
            msg = (f"서모스탯 콜드스타트(단지당 일 2편) 초과: {cx} {day} "
                   f"이미 {live}편 + 이번 {n}편 = {total}편")
            if ignore_cap:
                print(f"  [한도 초과] {msg} (--ignore-cap 으로 진행)", file=sys.stderr)
            else:
                errs.append(msg)
    return errs


def main():
    ap = argparse.ArgumentParser(description="분석 글 생성기")
    ap.add_argument("--round", type=int, default=2, choices=(1, 2))
    ap.add_argument("--ignore-cap", action="store_true",
                    help="서모스탯 한도를 넘겨도 반려하지 않는다. 출고 검사는 그대로 건다")
    args = ap.parse_args()

    pack = build(args.round)
    errs = validate(pack, args.ignore_cap)
    if errs:
        print("자체 검증 실패:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    out = OUT_R2 if args.round == 2 else OUT
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for b in pack["bundles"]:
        p = b["payload"]["post"]
        print(f"  [{p['category']}] {p['persona_external_id']:28}{len(p['title']):>3}자  {p['title']}")
    print(f"\n글 {len(pack['bundles'])}편 · 댓글 {sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
