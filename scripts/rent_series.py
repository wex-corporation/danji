#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""한 단지의 전월세 신고를 계약월마다 센다 — 비가격 칸만 남긴다.

`rent_volume.py`는 몇 달을 묶어 비율을 낸다(표본 30 아래면 비율을 안 낸다).
이 스크립트는 달마다 **건수**만 센다 — 전체 · 전세(월세 0) · 월세 낀 계약 · 갱신(종전 보증금 기재) ·
계약 구분 '갱신' · 갱신요구권 '사용'. 보증금·월세 금액은 저장하지 않는다.

실행:
  python3 scripts/rent_series.py --complex mapo-raemian-prugio --from 202410 --to 202609
  → data/rents/series/<slug>-<from>_<to>.json
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import rent_volume as rv  # noqa: E402
from trade_registry import month_range  # noqa: E402

KST = timezone(timedelta(hours=9))


def run(slug, a, b):
    lawd, names = TARGET[slug]
    key = rv.service_key()
    months = {}
    for ym in month_range(a, b):
        rows = [r for r in rv.fetch(key, lawd, ym) if r["apt"] in names]
        months[ym] = {
            "n": len(rows),
            "jeonse": sum(1 for r in rows if r["monthly_manwon"] == 0),
            "with_monthly": sum(1 for r in rows if r["monthly_manwon"] > 0),
            "pre_deposit": sum(1 for r in rows if r["pre_deposit"]),
            "type_renew": sum(1 for r in rows if r["contract_type"] == "갱신"),
            "type_new": sum(1 for r in rows if r["contract_type"] == "신규"),
            "type_blank": sum(1 for r in rows if not r["contract_type"]),
            "rr_used": sum(1 for r in rows if r["use_rr_right"] == "사용"),
            "rr_filled": sum(1 for r in rows if r["use_rr_right"]),
            "area_le60": sum(1 for r in rows if r["area_m2"] <= 60),
        }
        assert months[ym]["jeonse"] + months[ym]["with_monthly"] == months[ym]["n"]
        time.sleep(0.2)
    out = REPO / "data" / "rents" / "series" / f"{slug}-{a}_{b}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "slug": slug, "lawd_cd": lawd, "apt_names": sorted(names),
        "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        "source": "국토교통부 아파트 전월세 실거래가 자료(공공데이터포털 15058017, getRTMSDataSvcAptRent)",
        "note": "계약월별 건수. 보증금·월세 금액은 저장하지 않는다. with_monthly = 월세가 0보다 큰 계약(반전세 포함). "
                "pre_deposit = 종전 보증금 칸이 채워진 계약, type_renew = 계약 구분 '갱신'(채움률이 서로 달라 섞지 않는다)",
        "months": months,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out, months


TARGET = {
    "mapo-raemian-prugio": ("11440", {"마포래미안푸르지오1단지", "마포래미안푸르지오2단지",
                                      "마포래미안푸르지오3단지", "마포래미안푸르지오4단지"}),
    "ricents": ("11710", {"리센츠"}),
    "one-bailey": ("11650", {"래미안원베일리"}),
}


def gu_dongs(lawd, a, b):
    """구 전체 전월세 신고를 달마다 동별·단지별 건수로. 금액은 저장하지 않는다."""
    from collections import Counter
    key = rv.service_key()
    months = {}
    for ym in month_range(a, b):
        rows = rv.fetch(key, lawd, ym)
        months[ym] = {"total": len(rows),
                      "by_dong": dict(Counter(r["dong"] for r in rows).most_common()),
                      "by_dong_apt": {dg: dict(Counter(r["apt"] for r in rows if r["dong"] == dg).most_common())
                                      for dg in sorted({r["dong"] for r in rows})}}
        time.sleep(0.2)
    out = REPO / "data" / "rents" / "gu" / f"{lawd}-{a}_{b}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "lawd_cd": lawd, "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        "source": "국토교통부 아파트 전월세 실거래가 자료(공공데이터포털 15058017, getRTMSDataSvcAptRent)",
        "note": "계약월별 동·단지 건수. 금액은 저장하지 않는다", "months": months,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="전월세 신고 계약월별 건수")
    ap.add_argument("--complex", choices=sorted(TARGET))
    ap.add_argument("--gu", help="구 코드. 주면 동·단지별 건수만 센다")
    ap.add_argument("--from", dest="a", required=True)
    ap.add_argument("--to", dest="b", required=True)
    a = ap.parse_args()
    if a.gu:
        print(gu_dongs(a.gu, a.a, a.b).relative_to(REPO))
        return 0
    out, months = run(a.complex, a.a, a.b)
    print(out.relative_to(REPO))
    for ym, m in months.items():
        print(" ", ym, m)


if __name__ == "__main__":
    sys.exit(main())
