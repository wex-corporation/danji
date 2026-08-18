#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""단지 → 법정동코드(10자리) 확정.

왜 만들었나
  `vworld_price.py` 의 법정동코드 표를 손으로 적어 넣었는데 파일럿 6곳 중
  4곳이 틀려 있었다. 파크리오 자리에는 잠실동 코드가, 헬리오시티는 아예 없었다.
  이런 표는 틀려도 조회가 **성공한다.** 엉뚱한 동의 값이 정상 응답으로 저장된다.
  `kapt_fees.py` 가 막았던 "미공개 월이 0원으로 기록되는" 사고와 같은 종류다.

어떻게 푸나
  손으로 적지 않고 조회로 확정한다. 이미 쓰는 매매 실거래 API 응답에
  `sggCd`(시군구 5자리)와 `umdCd`(읍면동 5자리)가 들어 있고,
  **법정동코드 10자리 = sggCd + umdCd** 다.

  단지의 자치구·법정동은 `data/complex-info/<slug>.json` 의 address 에서 읽는다.
  (예: "서울특별시 송파구 가락동 479 헬리오시티아파트" → 송파구 / 가락동)

못 찾으면 지어내지 않는다. 그 단지는 null 로 남기고 사유를 적는다.

사용법:
  export KAPT_SERVICE_KEY=...
  python3 scripts/ldcode.py
  python3 scripts/ldcode.py --months 202605 202606 202607
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INFO_DIR = REPO / "data" / "complex-info"
OUT = REPO / "data" / "ldcode.json"
API = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
UA = "danji-content-agent/1.0"
DEFAULT_MONTHS = ["202607", "202606", "202605"]

# build_outlier_pack.py 의 PILOT_R2 와 같아야 한다.
PILOT = ["one-bailey", "eunma", "olympic-park-foreon", "helio-city", "parkrio", "ricents"]

# trade_volume.py 와 같은 표. 자치구 이름 → 법정동 시군구코드.
SEOUL_GU = {
    "종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200",
    "광진구": "11215", "동대문구": "11230", "중랑구": "11260", "성북구": "11290",
    "강북구": "11305", "도봉구": "11320", "노원구": "11350", "은평구": "11380",
    "서대문구": "11410", "마포구": "11440", "양천구": "11470", "강서구": "11500",
    "구로구": "11530", "금천구": "11545", "영등포구": "11560", "동작구": "11590",
    "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710",
    "강동구": "11740",
}

ADDR = re.compile(r"서울특별시\s+(\S+구)\s+(\S+동)")


class LdError(RuntimeError):
    pass


def service_key():
    k = os.environ.get("KAPT_SERVICE_KEY") or os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not k:
        raise LdError("KAPT_SERVICE_KEY가 없습니다. `set -a && . ./.env && set +a`")
    return k


def fetch(key, lawd_cd, ymd, rows=1000):
    """조사 중 connection reset 이 실제로 났다. 재시도는 필수다."""
    q = {"serviceKey": key, "LAWD_CD": lawd_cd, "DEAL_YMD": ymd,
         "numOfRows": rows, "pageNo": 1}
    url = f"{API}?{urllib.parse.urlencode(q)}"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise LdError(f"HTTP {exc.code}: {body[:200]}") from exc
        except (urllib.error.URLError, OSError) as exc:
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise LdError(f"네트워크 실패: {exc}") from exc

    if "SERVICE_KEY_IS_NOT_REGISTERED" in raw:
        raise LdError("등록되지 않은 서비스키")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise LdError(f"응답 파싱 실패: {raw[:150]}") from exc

    out = {}
    for it in root.findall(".//item"):
        d = {c.tag: (c.text or "").strip() for c in it}
        dong, sgg, umd = d.get("umdNm"), d.get("sggCd"), d.get("umdCd")
        if dong and sgg and umd:
            out.setdefault(dong, sgg + umd)
    return out


def targets():
    """단지별 자치구·법정동을 complex-info 의 주소에서 읽는다."""
    rows = {}
    for slug in PILOT:
        path = INFO_DIR / f"{slug}.json"
        if not path.exists():
            rows[slug] = {"error": f"{path.name} 없음"}
            continue
        info = json.loads(path.read_text(encoding="utf-8"))
        m = ADDR.search(info.get("address") or "")
        if not m:
            rows[slug] = {"name": info.get("complex_name"),
                          "error": f"주소에서 구·동을 못 읽음: {info.get('address')!r}"}
            continue
        gu, dong = m.group(1), m.group(2)
        if gu not in SEOUL_GU:
            rows[slug] = {"name": info.get("complex_name"), "error": f"모르는 자치구: {gu}"}
            continue
        rows[slug] = {"name": info.get("complex_name"), "gu": gu, "dong": dong,
                      "gu_code": SEOUL_GU[gu], "address": info.get("address")}
    return rows


def main():
    ap = argparse.ArgumentParser(description="단지 → 법정동코드 확정")
    ap.add_argument("--months", nargs="+", default=DEFAULT_MONTHS,
                    help="YYYYMM. 앞에서부터 찾다가 나오면 멈춘다")
    args = ap.parse_args()

    try:
        key = service_key()
    except LdError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    rows = targets()
    need = sorted({r["gu_code"] for r in rows.values() if "gu_code" in r})
    table = {}          # gu_code → {dong: ldcode}
    used = {}           # gu_code → 어느 달에서 찾았는지
    for gu in need:
        merged = {}
        for ym in args.months:
            try:
                merged.update(fetch(key, gu, ym))
            except LdError as exc:
                print(f"  [실패] {gu} {ym}: {exc}", file=sys.stderr)
                continue
            used.setdefault(gu, []).append(ym)
            wanted = {r["dong"] for r in rows.values() if r.get("gu_code") == gu}
            if wanted <= set(merged):
                break
            time.sleep(0.3)
        table[gu] = merged
        print(f"  {gu} 법정동 {len(merged)}개 수집", flush=True)

    result, missing = {}, []
    for slug, r in rows.items():
        if "gu_code" not in r:
            result[slug] = {"ld_code": None, "reason": r.get("error")}
            missing.append(slug)
            continue
        code = table.get(r["gu_code"], {}).get(r["dong"])
        if not code:
            result[slug] = {"ld_code": None, "complex_name": r["name"],
                            "gu": r["gu"], "dong": r["dong"],
                            "reason": f"{args.months} 실거래에 {r['dong']} 기록이 없어 코드를 확정하지 못했다"}
            missing.append(slug)
            continue
        result[slug] = {
            "ld_code": code, "complex_name": r["name"], "gu": r["gu"], "dong": r["dong"],
            "address": r["address"],
            "derived_from": {"api": "국토교통부 아파트 매매 실거래가 상세 자료",
                             "fields": "sggCd + umdCd", "months": used.get(r["gu_code"], [])},
        }

    payload = {
        "note": ("법정동코드는 손으로 적지 않는다. 매매 실거래 응답의 sggCd + umdCd 로 확정한다. "
                 "손으로 적었을 때 파일럿 6곳 중 4곳이 틀렸고, 틀려도 조회는 성공해서 "
                 "엉뚱한 동의 값이 저장됐다"),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "complexes": result,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n{'단지':22}{'법정동':10}{'법정동코드':>14}")
    for slug in PILOT:
        r = result[slug]
        code = r.get("ld_code") or "— 확정 실패"
        print(f"  {(r.get('complex_name') or slug)[:18]:20}{r.get('dong','?'):10}{code:>14}")
    print(f"\n확정 {len(PILOT)-len(missing)} / {len(PILOT)}  → {OUT.relative_to(REPO)}")
    if missing:
        print(f"[주의] 확정 못 한 단지: {', '.join(missing)} — 지어내지 않고 null 로 뒀다",
              file=sys.stderr)
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
