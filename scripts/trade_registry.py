#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""계약에서 등기까지 — 국토부 매매 실거래 응답의 등기일자(rgstDate)·해제 칸을 단지별로 모은다.

소재 목록(docs/topic-ideas-2026-11.md) 21번. 금액은 저장하지 않는다(비가격 지표).
등기일이 비어 있는 거래는 '아직 등기가 없다'까지만 말할 수 있다 — 잔금 전일 수 있다.

실행:
  python3 scripts/trade_registry.py --complex one-bailey --from 202308 --to 202609
  → data/trades/registry/<slug>-<from>_<to>.json
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import trade_volume as tv  # noqa: E402

KST = timezone(timedelta(hours=9))

# 실거래 신고서의 단지 이름(aptNm). 마래푸는 1~4단지로 나뉘어 신고된다(CLAUDE.md 22번)
COMPLEX = {
    "one-bailey": ("11650", ["래미안원베일리"]),
    "ricents": ("11710", ["리센츠"]),
    "helio-city": ("11710", ["헬리오시티"]),
    "eunma": ("11680", ["은마"]),
    "godeok-gracium": ("11740", ["고덕 그라시움", "고덕그라시움"]),
    "mapo-raemian-prugio": ("11440", ["마포래미안푸르지오1단지", "마포래미안푸르지오2단지",
                                      "마포래미안푸르지오3단지", "마포래미안푸르지오4단지"]),
}


def yymmdd(s):
    """'26.08.28' → '2026-08-28'. 빈칸이면 None."""
    s = (s or "").strip()
    if not s:
        return None
    y, m, d = s.split(".")
    return f"20{int(y):02d}-{int(m):02d}-{int(d):02d}"


def month_range(a, b):
    y, m = int(a[:4]), int(a[4:])
    while f"{y}{m:02d}" <= b:
        yield f"{y}{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def fetch_month(key, lawd, ym):
    q = {"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ym, "numOfRows": 1000, "pageNo": 1}
    url = f"{tv.API}?{urllib.parse.urlencode(q)}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": tv.UA}), timeout=30) as r:
                raw = r.read().decode("utf-8", errors="replace")
            break
        except OSError:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    root = ET.fromstring(raw)
    code = (root.findtext(".//resultCode") or "").strip()
    assert code in ("00", "000"), (ym, root.findtext(".//resultMsg"))
    total = int(root.findtext(".//totalCount") or 0)
    items = root.findall(".//item")
    assert total == len(items) <= 1000, (ym, total, len(items))  # 한 쪽에 다 들어와야 한다
    return total, [{c.tag: (c.text or "").strip() for c in it} for it in items]


def run(slug, a, b):
    lawd, names = COMPLEX[slug]
    key = tv.service_key()
    rows, gu_totals = [], {}
    for ym in month_range(a, b):
        total, items = fetch_month(key, lawd, ym)
        gu_totals[ym] = total
        for d in items:
            if d.get("aptNm", "").strip() not in names:
                continue
            rows.append({
                "deal_date": f"{d['dealYear']}-{int(d['dealMonth']):02d}-{int(d['dealDay']):02d}",
                "apt": d["aptNm"].strip(),
                "area_m2": float(d.get("excluUseAr") or 0),
                "floor": d.get("floor", ""),
                "rgst_date": yymmdd(d.get("rgstDate")),
                "cancel": bool(d.get("cdealType", "").strip()),
                "cancel_date": yymmdd(d.get("cdealDay")),
                "dealing": d.get("dealingGbn", ""),
                "buyer": d.get("buyerGbn", ""),
                "seller": d.get("slerGbn", ""),
            })
        time.sleep(0.2)
    rows.sort(key=lambda r: (r["deal_date"], r["area_m2"], r["floor"]))
    out = REPO / "data" / "trades" / "registry" / f"{slug}-{a}_{b}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "slug": slug, "lawd_cd": lawd, "apt_names": names,
        "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        "source": "국토교통부 아파트 매매 실거래가 상세 자료(공공데이터포털 15126469, getRTMSDataSvcAptTradeDev)",
        "note": "계약월별 조회. 금액은 저장하지 않는다. rgst_date 빈칸 = 응답에 등기일자가 없음(해제·잔금 전 등). 계약일과 등기일은 신고서 값 그대로",
        "gu_totals": gu_totals, "rows": rows,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out, rows


BULK_MIN = 10   # 같은 단지·같은 계약일이 이만큼 넘으면 묶음으로 따로 적는다


def gu_summary(lawd, a, b):
    """구 전체 매매를 달마다 — 총수, 동별, 중개/직거래, 한 단지 하루 묶음(BULK_MIN 이상).

    11/10에 알았다: 송파구 2026년 9월 322건 중 170건이 한 단지(장지동)의 9월 18일 하루 계약이었다
    (직거래 · 매도 법인 · 매수 공공기관 · 전용 18㎡대). 구 전체 건수를 비교군으로 쓰는 글은 이 묶음을 먼저 본다.
    """
    from collections import Counter
    key = tv.service_key()
    months = {}
    for ym in month_range(a, b):
        total, items = fetch_month(key, lawd, ym)
        cl = Counter((d["aptNm"].strip(), d["dealDay"]) for d in items)
        bulks = []
        for (apt, day), n in cl.most_common():
            if n < BULK_MIN:
                break
            rs = [d for d in items if d["aptNm"].strip() == apt and d["dealDay"] == day]
            bulks.append({
                "apt": apt, "dong": rs[0].get("umdNm", ""), "deal_date": f"{ym[:4]}-{ym[4:]}-{int(day):02d}", "n": n,
                "dealing": dict(Counter(d.get("dealingGbn", "") for d in rs)),
                "seller": dict(Counter(d.get("slerGbn", "") for d in rs)),
                "buyer": dict(Counter(d.get("buyerGbn", "") for d in rs)),
                "area_m2_int": dict(Counter(str(int(float(d.get("excluUseAr") or 0))) for d in rs)),
                "build_year": dict(Counter(d.get("buildYear", "") for d in rs)),
                "cancel": sum(1 for d in rs if d.get("cdealType", "").strip()),
            })
        months[ym] = {
            "total": total,
            "by_dong": dict(Counter(d.get("umdNm", "") for d in items).most_common()),
            "by_dong_apt": {dg: dict(Counter(d["aptNm"].strip() for d in items if d.get("umdNm") == dg).most_common())
                            for dg in sorted({d.get("umdNm", "") for d in items})},
            "dealing": dict(Counter(d.get("dealingGbn", "") for d in items)),
            "cancel": sum(1 for d in items if d.get("cdealType", "").strip()),
            "bulks": bulks,
            "total_minus_bulks": total - sum(x["n"] for x in bulks),
        }
        time.sleep(0.2)
    out = REPO / "data" / "trades" / "gu" / f"{lawd}-{a}_{b}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "lawd_cd": lawd, "gu": tv.SEOUL_GU.get(lawd, lawd),
        "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        "source": "국토교통부 아파트 매매 실거래가 상세 자료(공공데이터포털 15126469, getRTMSDataSvcAptTradeDev)",
        "note": f"계약월별. 금액은 저장하지 않는다. bulks = 같은 단지·같은 계약일 {BULK_MIN}건 이상. total 은 해제 신고 포함",
        "months": months,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="계약에서 등기까지")
    ap.add_argument("--complex", choices=sorted(COMPLEX))
    ap.add_argument("--gu", help="구 코드. 주면 단지 대신 구 요약(동별 건수·한 단지 하루 묶음)을 만든다")
    ap.add_argument("--from", dest="a", required=True)
    ap.add_argument("--to", dest="b", required=True)
    a = ap.parse_args()
    if a.gu:
        out = gu_summary(a.gu, a.a, a.b)
        print(out.relative_to(REPO))
        return 0
    out, rows = run(a.complex, a.a, a.b)
    reg = sum(1 for r in rows if r["rgst_date"])
    print(f"{out.relative_to(REPO)} · 거래 {len(rows)} · 등기일 있음 {reg} · 해제 {sum(r['cancel'] for r in rows)}")


if __name__ == "__main__":
    sys.exit(main())
