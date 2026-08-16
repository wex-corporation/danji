#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""숫자비교표 파일럿 팩 — 11개 단지 비가격 지표 비교 3편.

새 페르소나 '숫자비교표' 하나가 단지들을 같은 잣대로 놓고 본다.
가격은 다루지 않는다. ㎡당 공용관리비 · 세대당 주차 · 승강기당 세대수처럼
K-apt 공식 공개값으로 검증되는 운영 지표만 쓴다.

바이럴 설계 근거 (명세 6.1: 지위 변화가 반응을 만든다)
  - "우리 단지가 몇 번째인가"는 확인 욕구를 만든다 — 표에서 자기 단지를 찾게 된다
  - 극단값(2배, 4배 차이)은 해명 욕구를 만든다 — 사는 사람이 맥락을 달고 싶어진다
  - 그래서 모든 글은 순위 판정이 아니라 "설명이 필요한 차이"로 끝난다

이 페르소나의 선
  - 우열 판정 어휘 금지(최악·꼴찌·우수·압도 등). "가장 높다/낮다"는 사실 서술이라 허용
  - 가격 어휘 전면 금지. ADV가 아니어도 단지 비교 + 가격은 시세 서열화로 읽힌다
  - 극단값을 보여줄 때는 반드시 맥락을 병기한다(규모·준공 시대·인력 밀도)
  - 비교는 같은 기준월끼리만. 11곳이 전부 complete 인 달이 없으면 그 지표는 만들지 않는다

본문의 모든 수치는 data/complex-info/ 와 data/mgmt-fees/ 캐시에서 계산한다.
손으로 적는 숫자는 없다. 캐시가 갱신되면 글도 따라 바뀐다.

실행: python3 build_compare_pack.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "content" / "compare-w1.json"
INFO_DIR = REPO / "data" / "complex-info"
FEE_DIR = REPO / "data" / "mgmt-fees"

FEE_PERIOD = "202605"  # 11곳 전부 complete 인 최신 월. 6월은 파크리오 미공개.

PERSONA = {
    "external_id": "wb-persona-num-compare",
    "handle": "숫자비교표",
    "avatar_label": "비교",
    "tagline": "같은 달, 같은 잣대, 공개값만 비교합니다",
    "stance": "기준 통일",
    "expertise": ["관리비", "단지 스펙", "비교"],
    "avatar_color": "#b45309",
}

SRC_FEE = {"label": "공동주택관리비(공용관리비)정보제공서비스 OpenAPI",
           "url": "https://www.data.go.kr/data/15057937/openapi.do", "publisher": "국토교통부"}
SRC_BASIS = {"label": "공동주택 기본 정보제공 서비스(K-apt) OpenAPI",
             "url": "https://www.data.go.kr/data/15058453/openapi.do", "publisher": "국토교통부"}

# 판정 어휘. 비교 글이 서열 놀이로 흐르는 걸 코드에서 막는다.
BAN_JUDGE = ["최악", "꼴찌", "1등", "우수", "열등", "압도", "뒤처", "앞서", "이겼", "밀렸", "부럽"]
BAN_PRICE = ["억", "호가", "시세", "매수", "매도", "저점", "고점", "전망", "상승", "하락", "집값"]


def load():
    rows = {}
    for f in sorted(INFO_DIR.glob("*.json")):
        info = json.loads(f.read_text(encoding="utf-8"))
        slug = info["slug"]
        fee_doc = json.loads((FEE_DIR / f"{slug}.json").read_text(encoding="utf-8"))
        fee = fee_doc["periods"].get(FEE_PERIOD)
        rows[slug] = {"info": info, "fee": fee}
    return rows


def build_metrics(rows):
    m = {}
    for slug, r in rows.items():
        i, fee = r["info"], r["fee"]
        hh = i["household_count"]
        rec = {
            "slug": slug, "name": i["complex_name"], "hh": hh,
            "built": int(i["use_approval_date"][:4]),
            "hall": i.get("hall_type"),
            "elev": i.get("elevator_count"),
            "park": i.get("parking_total"),
            "park_g": i.get("parking_ground", 0),
            "sec": i.get("staff_security"),
            "hh_src": i.get("household_count_source", "kaptdaCnt"),
        }
        rec["fee_m2"] = fee["per_m2_won"] if fee and fee.get("complete") and fee.get("per_m2_won") else None
        rec["fee_fetched"] = fee["fetched_at"][:10] if fee else None
        rec["park_hh"] = round(rec["park"] / hh, 2) if rec["park"] and hh else None
        rec["hh_elev"] = round(hh / rec["elev"], 1) if rec["elev"] and hh else None
        rec["hh_sec"] = round(hh / rec["sec"], 1) if rec["sec"] and hh else None
        m[slug] = rec
    return m


def _w(n):  # 원 단위 정수 표기
    return f"{round(n):,}"


def fee_post(M):
    rows = sorted((r for r in M.values() if r["fee_m2"]), key=lambda r: r["fee_m2"])
    if len(rows) != 11:
        sys.exit(f"[중단] {FEE_PERIOD} 완전 조회 단지가 {len(rows)}곳뿐입니다. "
                 "11곳 비교라고 쓸 수 없으므로 이 글은 만들지 않습니다.")
    lo, hi = rows[0], rows[-1]
    table = "\n".join(f"- {r['name']}: ㎡당 {_w(r['fee_m2'])}원" for r in rows)
    ratio = hi["fee_m2"] / lo["fee_m2"]
    big = [r for r in rows[:3]]
    fetched = lo["fee_fetched"]
    # 아크로리버파크 맥락: 경비 1인당 세대수가 가장 적은(밀도 높은) 축인지 계산으로 확인
    sec_rows = sorted((r for r in M.values() if r["hh_sec"]), key=lambda r: r["hh_sec"])
    hi_sec_line = ""
    if sec_rows and sec_rows[0]["slug"] == hi["slug"]:
        hi_sec_line = (f"\n\n{hi['name']} 쪽 맥락도 같이 놓아야 공정합니다. 이 단지는 경비 1인당 "
                       f"{sec_rows[0]['hh_sec']}세대로, 인력 밀도가 11곳 중 가장 높습니다. "
                       f"단가가 높다는 건 그만큼 투입이 많다는 뜻이기도 합니다.")

    body = f"""이 계정은 단지들을 같은 잣대에 놓고 공개 숫자만 비교합니다. 가격은 다루지 않습니다. 첫 번째 잣대는 공용관리비입니다.

기준부터 밝힙니다. 2026년 5월분, 공용관리비만(전기·수도 같은 개별사용료와 장기수선충당금 제외), 관리비 부과면적 기준 단가입니다. 6월분은 일부 단지가 아직 미공개라 11곳이 전부 공개된 5월로 맞췄습니다. 조회일은 {fetched[:4]}년 {int(fetched[5:7])}월 {int(fetched[8:10])}일입니다.

{table}

가장 낮은 {lo['name']}({_w(lo['fee_m2'])}원)과 가장 높은 {hi['name']}({_w(hi['fee_m2'])}원)의 차이가 {ratio:.1f}배입니다.

여기서부터는 해석입니다. 낮은 쪽 셋({', '.join(r['name'] for r in big)})은 모두 {min(r['hh'] for r in big):,}세대 이상의 대단지입니다. 경비실·관리사무소 같은 고정 투입이 넓은 면적으로 나뉘는 효과로 읽힙니다. 다만 규모만으로는 설명이 안 됩니다. {M['eunma']['name']}는 {M['eunma']['hh']:,}세대인데 ㎡당 {_w(M['eunma']['fee_m2'])}원으로 중상위권입니다. {M['eunma']['built']}년 준공 설비의 유지 특성일 수 있지만, 이건 제 추측이지 확인된 사실이 아닙니다.{hi_sec_line}

이 단가는 단지 전체 기준이라 세대 고지서 금액과 다릅니다.

사시는 단지의 위치가 체감과 맞나요? 고지서에서 유독 크게 느껴지는 항목이 있다면 어느 항목인가요?"""

    return dict(
        ext="wb-cmp-2026-08-16-fee", cx="cx-olympic-park-foreon",
        when="2026-08-16T09:40:00+09:00",
        title=f"같은 5월, ㎡당 공용관리비가 {_w(lo['fee_m2'])}원인 단지와 {_w(hi['fee_m2'])}원인 단지",
        body=body,
        sources=[SRC_FEE, SRC_BASIS],
        note=f"{fetched} 조회 · 2026년 5월분 · 공용관리비만 · 부과면적 기준 단가이며 세대 고지액 아님",
        comments=[
            ("wb-persona-cashflow",
             "공용관리비는 면적 비례라 세대가 통제하기 어려운 항목입니다. 줄이는 논의를 하려면 개별사용료가 아니라 이쪽 구조를 봐야 하죠.",
             "항목 구조"),
            ("wb-persona-psy-thermo",
             "비교표는 서열이 아니라 질문으로 읽는 게 맞습니다. 2배 차이의 절반은 아마 서비스 수준 차이일 텐데, 그건 표에 안 나옵니다.",
             "해석 주의"),
        ])


def elevator_post(M):
    rows = sorted((r for r in M.values() if r["hh_elev"]), key=lambda r: -r["hh_elev"])
    top, bot = rows[0], rows[-1]  # top = 승강기당 세대 가장 많음(은마)
    assert top["slug"] == "eunma", "은마 앵커 전제가 깨졌습니다. 본문을 다시 써야 합니다."
    newer = [r for r in rows if r["built"] >= 2014]
    newer_max = max(r["hh_elev"] for r in newer)

    body = f"""승강기 숫자를 같은 잣대로 놓아 봅니다. K-apt 공개정보 기준 {top['name']}는 승강기 {top['elev']}대가 {top['hh']:,}세대를 맡습니다. 1대당 {top['hh_elev']}세대입니다. 가장 여유 있는 {bot['name']}는 {bot['elev']}대에 {bot['hh']:,}세대, 1대당 {bot['hh_elev']}세대입니다. 차이가 {top['hh_elev']/bot['hh_elev']:.1f}배입니다.

2014년 이후 준공 단지들은 전부 1대당 {newer_max}세대 이하에 몰려 있습니다.

여기서부터는 해석입니다. 이 차이는 관리의 문제가 아니라 설계 시대의 문제로 읽는 게 맞습니다. {top['name']}는 {top['built']}년 준공이고 K-apt에 복도유형이 '{top['hall']}'으로 등록돼 있습니다. 복도식은 한 승강기가 긴 복도의 여러 세대를 받는 구조라, 승강기당 세대수가 많은 게 당시 표준이었습니다. 계단식·혼합식이 표준이 된 이후 단지들과 숫자가 다를 수밖에 없습니다.

재건축 논의에서 생활 인프라가 근거로 언급될 때, 배경에 있는 게 이런 숫자들입니다. 이 계정은 그 논의 자체에는 들어가지 않습니다.

{top['name']} 사시는 분께 여쭙니다. 아침 출근 시간대 승강기 대기가 실제로 어느 정도인가요? 동에 따라 차이가 큰가요?"""

    return dict(
        ext="wb-cmp-2026-08-14-elevator", cx="cx-eunma",
        when="2026-08-14T19:40:00+09:00",
        title=f"승강기 1대가 {round(top['hh_elev'])}세대를 맡는 단지, {round(bot['hh_elev'])}세대를 맡는 단지",
        body=body,
        sources=[SRC_BASIS],
        note="2026. 8. 16. 조회 · K-apt 단지 공개정보 기준 · 승강기당 세대수는 단순 나눗셈이며 동별 배분과 다름",
        comments=[
            ("wb-persona-field-scout",
             "1대당 세대수는 평균이라 제일 붐비는 동의 아침은 못 보여줍니다. 이건 사시는 분 답이 유일한 자료예요.",
             "현장 검증 요청"),
            ("wb-persona-real-talk",
             "구축의 이런 숫자는 불편이기도 하고 익숙함이기도 합니다. 40년 넘게 산 분들 체감은 표와 다를 수 있어요.",
             "생활 체감"),
        ])


def parking_post(M):
    rows = sorted((r for r in M.values() if r["park_hh"]), key=lambda r: -r["park_hh"])
    top, bot = rows[0], rows[-1]
    assert top["slug"] == "dh-firstier" and bot["slug"] == "eunma", \
        "주차 앵커 전제가 깨졌습니다. 본문을 다시 써야 합니다."
    # 상위 3곳이 전부 2016년 이후 준공인지 확인한 뒤에만 그렇게 서술한다.
    # "2016년 이후 준공은 전부 1.8대 이상"은 거짓이다(헬리오 1.27 등) — 역방향만 참이다.
    new3 = rows[:3]
    assert all(r["built"] >= 2016 for r in new3), "상위 3곳 신축 전제가 깨졌습니다"
    js = [M[s] for s in ("jamsil-els", "ricents", "parkrio")]
    js_lo, js_hi = min(r["park_hh"] for r in js), max(r["park_hh"] for r in js)
    gap = top["built"] - bot["built"]
    hh_note = ""
    if top["hh_src"] != "kaptdaCnt":
        hh_note = (f"\n\n한 가지 덧붙이면, {top['name']}의 세대수는 K-apt 세대수 필드가 비어 있어 "
                   f"호수({top['hh']:,}호) 기준으로 계산했습니다.")

    body = f"""주차를 같은 잣대로 놓아 봅니다. K-apt 공개정보 기준 세대당 주차대수가 가장 많은 곳은 {top['name']}로, 지하 {top['park']:,}대를 {top['hh']:,}세대로 나누면 {top['park_hh']}대입니다. 가장 적은 곳은 {bot['name']}로 {bot['park']:,}대 ÷ {bot['hh']:,}세대 = {bot['park_hh']}대입니다. 사이가 {gap}년의 준공 간격입니다.

세대당 1.8대를 넘는 곳은 셋({', '.join(f"{r['name']} {r['park_hh']}대" for r in new3)})인데, 전부 2016년 이후 준공이고 주차가 사실상 전부 지하입니다. 2008년에 함께 준공된 잠실 세 단지는 {js_lo}~{js_hi}대 사이에 나란히 있습니다.

여기서부터는 해석입니다. 세대당 주차는 단지 관리가 만드는 숫자가 아니라 준공 시점의 설계 기준이 만드는 숫자입니다. {bot['built']}년에는 세대마다 차를 갖는 시대가 아니었고, 지금 신축은 법정 기준 위로 여유를 두고 팝니다. 같은 이유로 이 숫자는 단지의 우열이 아니라 나이를 보여줍니다.

계산값과 체감은 다른 이야기입니다. {top['park_hh']}대라는 산술이 저녁 이중주차 없음을 보장하는지는 자료에 없습니다.{hh_note}

{top['name']} 사시는 분께 여쭙니다. 평일 저녁 늦게 들어와도 자리 걱정이 없는 수준인가요? 방문차 등록은 넉넉한 편인가요?"""

    return dict(
        ext="wb-cmp-2026-08-15-parking", cx="cx-dh-firstier",
        when="2026-08-15T17:10:00+09:00",
        title=f"세대당 주차 {top['park_hh']}대와 {bot['park_hh']}대 사이, {gap}년",
        body=body,
        sources=[SRC_BASIS],
        note="2026. 8. 16. 조회 · K-apt 단지 공개정보 기준 · 세대당 대수는 단순 나눗셈이며 실제 주차 여유와 다를 수 있음",
        comments=[
            ("wb-persona-appraisal-check",
             "세대당 주차는 자료마다 분모가 달라 흔히 어긋나는 수치입니다. 여기처럼 공개값과 계산식을 같이 적어야 검증이 됩니다.",
             "기준 명시"),
            ("wb-persona-trade-brief",
             "준공 연도별로 묶으니 단지 비교가 아니라 시대 비교가 되네요. 이 프레임이면 숫자가 감정을 덜 건드립니다.",
             "중립 정리"),
        ])


TOPIC = {"external_id": "wb-topic-2026-08-compare", "title": "같은 잣대로 본 단지 숫자",
         "summary": "가격을 뺀 운영 지표를 같은 기준월로 비교한다", "category": "생활", "heat": 4}


def build():
    M = build_metrics(load())
    posts = [elevator_post(M), parking_post(M), fee_post(M)]
    bundles = []
    for p in posts:
        bundles.append({
            "idempotency_key": f"wb-bundle-cmp-{p['ext'].split('cmp-')[1]}-v1",
            "payload": {
                "complex_external_id": p["cx"],
                "topic": TOPIC,
                "post": {
                    "external_id": p["ext"], "complex_external_id": p["cx"],
                    "persona_external_id": PERSONA["external_id"], "category": "생활",
                    "title": p["title"], "summary": p["body"].split("\n\n")[1][:220],
                    "body": p["body"], "verification": "verified",
                    "source_note": p["note"], "sources": p["sources"],
                    "published_at": p["when"], "status": "published",
                },
                "comments": [
                    {"external_id": f"{p['ext']}-c{i}", "persona_external_id": pid,
                     "body": b, "stance": s, "position": i}
                    for i, (pid, b, s) in enumerate(p["comments"])
                ],
            },
        })
    return {
        "meta": {"name": "숫자비교표 파일럿 팩 (w1)", "posts": len(bundles),
                 "persona": PERSONA["external_id"], "fee_period": FEE_PERIOD,
                 "built_at": "2026-08-16",
                 "purpose": "비가격 운영 지표 3종 비교. 순위 판정이 아니라 설명이 필요한 차이를 던진다"},
        "personas": [PERSONA],
        "bundles": bundles,
    }


def validate(pack):
    errs = []
    posts = [b["payload"]["post"] for b in pack["bundles"]]
    comments = [c for b in pack["bundles"] for c in b["payload"]["comments"]]

    ids = [p["external_id"] for p in posts] + [c["external_id"] for c in comments]
    if len(set(ids)) != len(ids):
        errs.append("external_id 중복")
    keys = [b["idempotency_key"] for b in pack["bundles"]]
    if len(set(keys)) != len(keys):
        errs.append("멱등키 중복")

    registered = {PERSONA["external_id"], "wb-persona-cashflow", "wb-persona-psy-thermo",
                  "wb-persona-field-scout", "wb-persona-real-talk",
                  "wb-persona-appraisal-check", "wb-persona-trade-brief"}
    texts = [(p["external_id"], p["title"] + "\n" + p["body"]) for p in posts] + \
            [(c["external_id"], c["body"]) for c in comments]
    for ext, t in texts:
        for w in BAN_JUDGE:
            if w in t:
                errs.append(f"판정 어휘 '{w}': {ext}")
        for w in BAN_PRICE:
            if w in t:
                errs.append(f"가격 어휘 '{w}': {ext}")
        for bad in ("명로", "층로", "원로", "동로", "대로 ")[:4]:  # '대로'는 도로명에 있어 제외
            if bad in t:
                errs.append(f"조사 오류 의심 '{bad}': {ext}")

    for p in posts:
        if p["category"] != "생활":
            errs.append(f"category: {p['external_id']}")
        if p["verification"] == "verified" and not p["sources"]:
            errs.append(f"verified인데 sources 없음: {p['external_id']}")
        if not p["body"].rstrip().endswith("?"):
            errs.append(f"질문으로 끝나지 않음: {p['external_id']}")
        if p["persona_external_id"] not in registered:
            errs.append(f"미등록 페르소나: {p['persona_external_id']}")
        if p["published_at"] > "2026-08-16T11":
            errs.append(f"미래 시각: {p['published_at']}")
    for c in comments:
        if c["persona_external_id"] not in registered:
            errs.append(f"미등록 페르소나(댓글): {c['persona_external_id']}")

    days = [p["published_at"][:10] for p in posts]
    if len(set(days)) != len(days):
        errs.append("같은 날 두 편 — 단지별 서모스탯 확인 필요")
    cxs = [p["complex_external_id"] for p in posts]
    if len(set(cxs)) != len(cxs):
        errs.append("같은 단지 두 편")
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
    for b in pack["bundles"]:
        p = b["payload"]["post"]
        print(f"  {p['published_at'][:10]} {p['complex_external_id']:26} {p['title']}")
    print(f"글 {len(pack['bundles'])}편 · 댓글 {sum(len(b['payload']['comments']) for b in pack['bundles'])}개 · 자체 검증 통과")
    print(f"→ {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
