#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""장기수선충당금 — 걷은 돈 · 쓴 돈 · 남은 돈 (공공데이터포털 15059160, 공식 OpenAPI).

국토교통부_공동주택관리비(장기수선충당금)정보서비스 `1613000/AptRepairsCostServiceV3`.
이용허락범위 제한 없음(포털 원문, 2026-11-11 확인). 키는 기존 KAPT_SERVICE_KEY 그대로(11/11 확인).

오퍼레이션 넷, 단지코드(kaptCode)와 발생년월(searchDate, YYYYMM)을 받는다:
  getHsmpMonthFeeInfoV3          sLevy  월부과액
  getHsmpMonthRetalFeeInfoV3     sUse   월사용액
  getHsmpReserveBalanceInfoV3    sTot   충당금잔액
  getHsmpAccumulationTariffInfoV3 sPer  적립요율(%)  — 6곳 중 5곳이 0.0이라 글에 쓰지 않는다

주의
- 빈 item 은 0원이 아니다. 받지 못한 칸은 None 으로 남기고 complete 에서 뺀다(CLAUDE.md 1번 파크리오 0원 사고)
- 잔액 변화가 '부과 − 사용'과 맞지 않는 달이 있다(원베일리 2026-08). 이자·다른 수입일 수 있지만 자료에 없다.
  gap 칸에 차이만 적고 해석하지 않는다
- 사용액은 합계뿐이다. 무엇에 썼는지는 이 자료에 없다
- ㎡당 값은 K-apt 관리비부과면적(kaptMarea = complex-info 의 billed_area_m2)으로 나눈다(CLAUDE.md 1번)

실행:
  python3 scripts/kapt_repairs.py --from 202501 --to 202609          # 6곳
  python3 scripts/kapt_repairs.py --complex ricents --from 202605 --to 202609
  → data/repair-reserve/<slug>.json
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import kapt_fees as kf  # noqa: E402
from trade_registry import month_range  # noqa: E402

KST = timezone(timedelta(hours=9))
API = "https://apis.data.go.kr/1613000/AptRepairsCostServiceV3/"
OPS = {
    "levy": ("getHsmpMonthFeeInfoV3", "sLevy"),
    "use": ("getHsmpMonthRetalFeeInfoV3", "sUse"),
    "balance": ("getHsmpReserveBalanceInfoV3", "sTot"),
    "rate": ("getHsmpAccumulationTariffInfoV3", "sPer"),
}
SIX = ["one-bailey", "eunma", "helio-city", "ricents", "godeok-gracium", "mapo-raemian-prugio"]
SOURCE = "국토교통부_공동주택관리비(장기수선충당금)정보서비스(공공데이터포털 15059160, AptRepairsCostServiceV3)"


def fetch(key, code, ym, op, field):
    q = {"serviceKey": key, "kaptCode": code, "searchDate": ym, "_type": "json"}
    url = API + op + "?" + urllib.parse.urlencode(q)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": kf.UA}), timeout=30) as r:
                j = json.loads(r.read().decode("utf-8", errors="replace"))
            break
        except (OSError, ValueError):
            if attempt == 4:
                return "ERR"
            time.sleep(2 ** attempt)
    head = j.get("response", {}).get("header", {})
    assert head.get("resultCode") in ("00", "000"), (code, ym, op, head)
    item = j["response"].get("body", {}).get("item")
    if isinstance(item, list):           # 사용액은 배열로 오기도 한다(명세 type: array). 한 단지 한 달이면 하나
        assert len(item) <= 1, (code, ym, op, len(item))
        item = item[0] if item else None
    if not isinstance(item, dict) or item.get(field) in (None, ""):
        return None
    return float(item[field]) if field == "sPer" else int(float(item[field]))


def run(slug, a, b):
    info = json.loads((REPO / "data" / "complex-info" / f"{slug}.json").read_text(encoding="utf-8"))
    fees = json.loads((REPO / "data" / "mgmt-fees" / f"{slug}.json").read_text(encoding="utf-8"))
    code = info["kapt_code"]
    assert code == fees["kapt_code"], slug
    key = kf.service_key()
    months, failures = {}, []
    for ym in month_range(a, b):
        row = {}
        for k, (op, f) in OPS.items():
            v = fetch(key, code, ym, op, f)
            if v == "ERR":
                failures.append(f"{ym} {op}")
                v = None
            row[k] = v
            time.sleep(0.12)
        row["complete"] = all(row[k] is not None for k in ("levy", "use", "balance"))
        months[ym] = row
    # 전달 잔액 + 부과 − 사용 과 이번 달 잔액의 차이. 해석하지 않는다(이자·다른 수입·정산 시점 차이일 수 있지만 자료에 없다)
    yms = sorted(months)
    for p, c in zip(yms, yms[1:]):
        P, C = months[p], months[c]
        if P["balance"] is not None and C["complete"]:
            C["gap_vs_prev"] = C["balance"] - (P["balance"] + C["levy"] - C["use"])
    # 공개 페이지(mgmt-fees breakdown) 값과 부과액 대조
    cross = {}
    for ym, per in (fees.get("periods") or {}).items():
        bd = (per or {}).get("breakdown") or {}
        lt = bd.get("장기수선충당금")
        if lt and ym in months and months[ym]["levy"] is not None:
            cross[ym] = {"public_page_won": lt["total_won"], "api_won": months[ym]["levy"],
                         "match": lt["total_won"] == months[ym]["levy"]}
    area = info["billed_area_m2"]
    out = REPO / "data" / "repair-reserve" / f"{slug}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(out.read_text(encoding="utf-8"))["months"] if out.exists() else {}
    for ym, row in old.items():            # 지난 조회분은 남기되, 이번에 받은 달은 새 값으로
        months.setdefault(ym, row)
    out.write_text(json.dumps({
        "slug": slug, "complex_name": info["complex_name"], "kapt_code": code,
        "household_count": info["household_count"], "billed_area_m2": area,
        "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        "source": SOURCE, "license": "이용허락범위 제한 없음(공공데이터포털 15059160)",
        "note": "원 단위. levy=월부과액 · use=월사용액 · balance=충당금잔액 · rate=적립요율(%, 글에 쓰지 않음). "
                "None = 응답에 값이 없음(0원 아님). gap_vs_prev = 이번 달 잔액 − (전달 잔액 + 부과 − 사용), 이유는 자료에 없다. "
                "사용액은 합계뿐이고 용처는 없다. ㎡당 = 원 ÷ billed_area_m2(K-apt 관리비부과면적)",
        "crosscheck_public_page": cross, "failures": failures,
        "months": dict(sorted(months.items())),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out, months, failures, cross


def main():
    ap = argparse.ArgumentParser(description="장기수선충당금 월부과·사용·잔액")
    ap.add_argument("--complex", choices=SIX)
    ap.add_argument("--from", dest="a", required=True)
    ap.add_argument("--to", dest="b", required=True)
    a = ap.parse_args()
    bad = 0
    for slug in ([a.complex] if a.complex else SIX):
        out, months, failures, cross = run(slug, a.a, a.b)
        mism = [ym for ym, c in cross.items() if not c["match"]]
        print(f"{out.relative_to(REPO)} · {len(months)}달 · 완전 {sum(m.get('complete', False) for m in months.values())} · "
              f"실패 {len(failures)} · 공개 페이지 대조 {len(cross)}건 불일치 {mism or 0}")
        bad += len(mism)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
