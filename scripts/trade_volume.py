#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""국토교통부 아파트 매매 실거래가 조회 — 거래량 랭킹과 평당가 산출.

두 가지에 쓴다.
  1. 단지 우선순위 — 거래가 활발한 곳부터 콘텐츠를 넣는다(명세 10.1 Phase 0)
  2. 예측 마켓 정산 — 주간 최고 평당가의 방향(오른다/내린다)

엔드포인트는 K-apt와 같은 1613000 기관이고, 별도 활용신청 없이 기존 키로 조회된다.
  1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev

중요 — 실거래는 **신고일** 기준이다.
계약일로부터 30일 이내 신고이므로 "이번 주 계약"은 이번 주에 보이지 않는다.
명세 5.2가 정한 대로 모든 집계·정산은 신고일이 아니라 계약일(dealYear/Month/Day)을
쓰되, 조회 시점에 아직 신고되지 않은 계약이 있다는 점을 항상 남긴다.

평당가 = dealAmount(만원) / excluUseAr(㎡) × 3.3058
전용면적 기준이다. 공급면적 기준 평당가와 다르므로 인용 시 반드시 밝힌다.

사용법:
  export KAPT_SERVICE_KEY=...
  python3 trade_volume.py --months 202605 202606 202607   # 서울 전역 거래량 랭킹
  python3 trade_volume.py --months 202607 --gu 11680      # 특정 구만
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "trades"
API = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
UA = "danji-content-agent/1.0"
PYEONG = 3.3058  # 1평 = 3.3058㎡

SEOUL_GU = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구",
    "11215": "광진구", "11230": "동대문구", "11260": "중랑구", "11290": "성북구",
    "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
    "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구",
    "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구",
    "11740": "강동구",
}


class TradeError(RuntimeError):
    pass


def service_key():
    k = os.environ.get("KAPT_SERVICE_KEY") or os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not k:
        raise TradeError("KAPT_SERVICE_KEY가 없습니다.")
    return k


def fetch(key, lawd_cd, ymd, rows=1000):
    q = {"serviceKey": key, "LAWD_CD": lawd_cd, "DEAL_YMD": ymd,
         "numOfRows": rows, "pageNo": 1}
    url = f"{API}?{urllib.parse.urlencode(q)}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8", errors="replace")
            break
        except (urllib.error.URLError, OSError) as exc:
            if attempt == 2:
                raise TradeError(f"네트워크 실패: {exc}") from exc
            time.sleep(2 ** attempt)

    if "SERVICE_KEY_IS_NOT_REGISTERED" in raw:
        raise TradeError("등록되지 않은 서비스키")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise TradeError(f"응답 파싱 실패: {raw[:150]}") from exc
    code = (root.findtext(".//resultCode") or "").strip()
    if code and code not in ("00", "000"):
        raise TradeError(f"{root.findtext('.//resultMsg')} ({code})")

    out = []
    for it in root.findall(".//item"):
        d = {c.tag: (c.text or "").strip() for c in it}
        try:
            amount = int(d.get("dealAmount", "").replace(",", ""))   # 만원
            area = float(d.get("excluUseAr", 0))                     # ㎡ 전용
        except ValueError:
            continue
        if not amount or area <= 0:
            continue
        out.append({
            "apt": d.get("aptNm", "").strip(),
            "dong": d.get("umdNm", "").strip(),
            "gu": SEOUL_GU.get(lawd_cd, lawd_cd),
            "amount_manwon": amount,
            "area_m2": area,
            "per_pyeong_manwon": round(amount / area * PYEONG, 1),
            "floor": d.get("floor", ""),
            "build_year": d.get("buildYear", ""),
            "deal_date": f"{d.get('dealYear','')}-{int(d.get('dealMonth',0) or 0):02d}-"
                         f"{int(d.get('dealDay',0) or 0):02d}",
            "cancel": bool((d.get("cdealType") or "").strip()),  # 해제신고 여부
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="아파트 매매 실거래 거래량·평당가 집계")
    ap.add_argument("--months", nargs="+", required=True, help="YYYYMM 여러 개")
    ap.add_argument("--gu", nargs="*", help="법정동 시군구코드. 생략 시 서울 25개구 전체")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    try:
        key = service_key()
    except TradeError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    gus = args.gu or list(SEOUL_GU)
    all_rows, failures = [], []
    for i, gu in enumerate(gus, 1):
        for ymd in args.months:
            try:
                rows = fetch(key, gu, ymd)
                all_rows.extend(rows)
            except TradeError as exc:
                failures.append((gu, ymd, str(exc)))
                print(f"  [실패] {SEOUL_GU.get(gu,gu)} {ymd}: {exc}", file=sys.stderr)
            time.sleep(0.25)
        print(f"  {i}/{len(gus)} {SEOUL_GU.get(gu,gu)} 누적 {len(all_rows):,}건", flush=True)

    live = [r for r in all_rows if not r["cancel"]]
    agg = defaultdict(lambda: {"n": 0, "prices": [], "gu": "", "dong": "", "years": set()})
    for r in live:
        k = (r["gu"], r["apt"])
        a = agg[k]
        a["n"] += 1
        a["prices"].append(r["per_pyeong_manwon"])
        a["gu"], a["dong"] = r["gu"], r["dong"]
        if r["build_year"]:
            a["years"].add(r["build_year"])

    ranked = sorted(agg.items(), key=lambda kv: -kv[1]["n"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "months": args.months,
        "gu_count": len(gus),
        "total_rows": len(all_rows),
        "cancelled_excluded": len(all_rows) - len(live),
        "failures": [{"gu": g, "month": m, "reason": r} for g, m, r in failures],
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": "계약일 기준 집계. 조회 시점에 미신고된 계약이 있을 수 있다. 해제신고 건은 제외했다.",
        "source": {"label": "국토교통부 아파트 매매 실거래가 상세 자료",
                   "url": "https://www.data.go.kr/data/15126469/openapi.do",
                   "publisher": "국토교통부"},
        "ranking": [
            {"rank": i, "gu": v["gu"], "dong": v["dong"], "apt": k[1], "trades": v["n"],
             "max_per_pyeong_manwon": max(v["prices"]),
             "median_per_pyeong_manwon": sorted(v["prices"])[len(v["prices"]) // 2],
             "build_year": sorted(v["years"])[0] if v["years"] else None}
            for i, (k, v) in enumerate(ranked[:200], 1)
        ],
    }
    path = OUT_DIR / f"volume-{'_'.join(args.months)}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n총 {len(all_rows):,}건 (해제 {payload['cancelled_excluded']}건 제외) · 실패 {len(failures)}건")
    print(f"\n{'순':>3} {'단지':24}{'구':7}{'거래':>5}{'최고평당(만)':>12}{'중위평당(만)':>12}")
    for r in payload["ranking"][:args.top]:
        print(f"{r['rank']:>3} {r['apt'][:22]:24}{r['gu'][:6]:7}{r['trades']:>5}"
              f"{r['max_per_pyeong_manwon']:>12,.0f}{r['median_per_pyeong_manwon']:>12,.0f}")
    print(f"\n→ {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
