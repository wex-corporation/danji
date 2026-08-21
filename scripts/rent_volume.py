#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""국토교통부 아파트 전월세 실거래가 조회 — 단지별 임대차 지표 캐시.

매매(`trade_volume.py`)와 같은 1613000 기관이지만 **별도 활용신청**이 필요했다.
2026-08-18 승인됐고 키는 기존 `KAPT_SERVICE_KEY`와 같다.
  1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent   일 10,000건

왜 전월세인가
  매매보다 표본이 훨씬 크다. 헬리오시티 3개월 기준 전월세 251건 대 매매 57건이다.
  그리고 매매에는 없는 필드가 있다 — 신규/갱신, 갱신요구권 사용 여부, 갱신 전 조건.
  이것들은 단지마다 확연히 갈려서 특이값 소재가 된다.

가격은 캐시에만 남기고 글에는 쓰지 않는다
  보증금·월세는 `raw_stats`에 남기지만 파생 지표는 전부 **비가격**이다.
  홍보 페르소나가 인용할 수 없고, 분석 글에서도 시세 부양으로 읽힐 여지를 만들지 않는다.

계약일 기준이다
  실거래는 신고일 기준으로 들어온다. 계약일로부터 30일 이내 신고이므로
  최근 달은 아직 덜 찼다. 집계는 계약일(dealYear/Month/Day)로 하되
  조회 시점에 미신고 계약이 있다는 점을 캐시에 남긴다.

사용법:
  export KAPT_SERVICE_KEY=...
  python3 rent_volume.py                                  # 기본 3개월
  python3 rent_volume.py --months 202605 202606 202607
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
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "rents"
INFO_DIR = REPO / "data" / "complex-info"
API = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"
UA = "danji-content-agent/1.0"

DEFAULT_MONTHS = ["202605", "202606", "202607"]

# 표본이 이보다 적으면 비율 지표가 흔들린다. complete: false 로 남기고 글에 쓰지 않는다.
MIN_SAMPLE = 30

# 실거래 응답의 aptNm 은 K-apt 등록명과 다르다.
# "올림픽파크포레온"(공백 없음), "은마"(아파트 없음), "래미안원베일리"(공백 없음).
# 표기가 바뀔 수 있어 후보를 여러 개 둔다.
TARGETS = [
    ("one-bailey", "11650", ["래미안원베일리", "래미안 원베일리"]),
    ("eunma", "11680", ["은마", "은마아파트"]),
    ("helio-city", "11710", ["헬리오시티"]),
    ("ricents", "11710", ["리센츠"]),
    ("parkrio", "11710", ["파크리오", "잠실파크리오"]),
    ("olympic-park-foreon", "11740", ["올림픽파크포레온", "올림픽파크 포레온"]),
    # 파일럿 밖 5곳. 2026-08-21 실거래 응답에서 표기를 확인하고 적었다.
    ("acro-river-park", "11650", ["아크로리버파크"]),
    ("dh-firstier", "11680", ["디에이치퍼스티어아이파크"]),
    ("godeok-gracium", "11740", ["고덕그라시움"]),
    ("jamsil-els", "11710", ["잠실엘스"]),
    # 마포래미안푸르지오는 실거래에 1~4단지로 따로 신고된다. K-apt 는 한 단지로
    # 등록돼 있고 세대수도 합산값이라, 네 이름을 모두 합쳐야 분모와 분자가 맞는다.
    ("mapo-raemian-prugio", "11440", ["마포래미안푸르지오1단지", "마포래미안푸르지오2단지",
                                      "마포래미안푸르지오3단지", "마포래미안푸르지오4단지"]),
]

PORTAL_ERRORS = {
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR":
        "등록되지 않은 서비스키입니다. 발급 직후라면 반영까지 최대 1시간 걸립니다",
    "SERVICE_ACCESS_DENIED_ERROR":
        "활용신청이 승인되지 않았습니다. 마이페이지에서 승인 상태를 확인하세요",
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR":
        "일일 트래픽(10,000건)을 초과했습니다",
}

SOURCE = {"label": "국토교통부 아파트 전월세 실거래가 자료",
          "url": "https://www.data.go.kr/data/15058017/openapi.do",
          "publisher": "국토교통부"}


class RentError(RuntimeError):
    pass


def service_key():
    k = os.environ.get("KAPT_SERVICE_KEY") or os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not k:
        raise RentError("KAPT_SERVICE_KEY가 없습니다. `set -a && . ./.env && set +a` 를 먼저 실행하세요.")
    return k


def _page(key, lawd_cd, ymd, page, rows):
    """한 페이지를 받아 (totalCount, 목록) 을 돌려준다.

    조사 중 connection reset 이 실제로 났다 — 재시도는 필수다.
    """
    q = {"serviceKey": key, "LAWD_CD": lawd_cd, "DEAL_YMD": ymd,
         "numOfRows": rows, "pageNo": page}
    url = f"{API}?{urllib.parse.urlencode(q)}"
    raw = None
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
            raise RentError(f"HTTP {exc.code}: {body[:200]}") from exc
        except (urllib.error.URLError, OSError) as exc:
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise RentError(f"네트워크 실패: {exc}") from exc

    for code, msg in PORTAL_ERRORS.items():
        if code in raw:
            raise RentError(msg)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise RentError(f"응답 파싱 실패: {raw[:150]}") from exc
    code = (root.findtext(".//resultCode") or "").strip()
    if code and code not in ("00", "000"):
        raise RentError(f"{root.findtext('.//resultMsg')} ({code})")

    out = []
    for it in root.findall(".//item"):
        d = {c.tag: (c.text or "").strip() for c in it}
        try:
            area = float(d.get("excluUseAr") or 0)
            deposit = int((d.get("deposit") or "0").replace(",", ""))          # 만원
            monthly = int((d.get("monthlyRent") or "0").replace(",", ""))      # 만원
        except ValueError:
            continue
        if area <= 0:
            continue
        floor = d.get("floor", "")
        out.append({
            "apt": d.get("aptNm", "").strip(),
            "dong": d.get("umdNm", "").strip(),
            "area_m2": area,
            "deposit_manwon": deposit,
            "monthly_manwon": monthly,
            "floor": int(floor) if floor.lstrip("-").isdigit() else None,
            "contract_type": d.get("contractType", "").strip(),   # 신규 / 갱신
            "contract_term": d.get("contractTerm", "").strip(),
            "pre_deposit": (d.get("preDeposit") or "").strip(),   # 갱신 전 조건. 있으면 갱신계약
            "use_rr_right": (d.get("useRRRight") or "").strip(),  # '사용' 이면 갱신요구권 행사
            "deal_date": f"{d.get('dealYear','')}-{int(d.get('dealMonth',0) or 0):02d}-"
                         f"{int(d.get('dealDay',0) or 0):02d}",
        })
    try:
        total = int(root.findtext(".//totalCount") or 0)
    except ValueError:
        total = 0
    return total, out


def fetch(key, lawd_cd, ymd, rows=1000):
    """한 구·한 달치를 **끝까지** 받는다.

    강남·송파·강동은 한 달 전월세가 1,000건을 넘는다. 첫 페이지만 받으면
    그 달의 앞부분만 보고 비율을 내게 된다 — 실제로 첫 실행에서 여러 구가
    정확히 1,000건으로 잘렸다. totalCount 를 보고 페이지를 끝까지 돈다.
    """
    total, out = _page(key, lawd_cd, ymd, 1, rows)
    page = 2
    while len(out) < total:
        time.sleep(0.3)
        _, more = _page(key, lawd_cd, ymd, page, rows)
        if not more:                      # 더 안 나오면 멈춘다. 무한루프 방지
            break
        out.extend(more)
        page += 1
    if len(out) != total:
        print(f"  [주의] {lawd_cd} {ymd}: totalCount {total:,} 인데 {len(out):,}건만 받았습니다",
              file=sys.stderr)
    return out


def pct(n, d):
    return round(n / d * 100, 1) if d else None


def derive(rows, households):
    """비가격 파생 지표. 글에 쓰는 건 전부 여기서 나온다."""
    n = len(rows)
    if n < MIN_SAMPLE:
        return None
    jeonse = sum(1 for r in rows if r["monthly_manwon"] == 0)
    renew = sum(1 for r in rows if r["pre_deposit"])
    rr = sum(1 for r in rows if r["use_rr_right"] == "사용")
    small = sum(1 for r in rows if r["area_m2"] <= 60)
    low = sum(1 for r in rows if r["floor"] is not None and 1 <= r["floor"] <= 3)
    return {
        "전세 비중": pct(jeonse, n),
        "갱신계약 비율": pct(renew, n),
        "갱신요구권 사용률": pct(rr, n),
        "전월세 회전율": pct(n, households),
        "60㎡이하 계약 비중": pct(small, n),
        "저층 계약 비중": pct(low, n),
    }


def raw_stats(rows):
    """가격은 여기에만 남긴다. 캐시 대조용이지 인용용이 아니다."""
    jeonse = sorted(r["deposit_manwon"] for r in rows if r["monthly_manwon"] == 0)
    areas = Counter(r["area_m2"] for r in rows)
    return {
        "note": "가격 항목은 대조용이다. 콘텐츠에는 파생 지표만 쓴다",
        "jeonse_count": len(jeonse),
        "jeonse_median_deposit_manwon": jeonse[len(jeonse) // 2] if jeonse else None,
        "area_mix_m2": [{"area_m2": a, "count": c} for a, c in areas.most_common()],
    }


def main():
    ap = argparse.ArgumentParser(description="아파트 전월세 실거래 단지별 지표 캐시")
    ap.add_argument("--months", nargs="+", default=DEFAULT_MONTHS, help="YYYYMM 여러 개")
    ap.add_argument("--only", nargs="*", help="슬러그를 지정하면 그 단지만")
    args = ap.parse_args()

    try:
        key = service_key()
    except RentError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    targets = [t for t in TARGETS if not args.only or t[0] in args.only]
    if not targets:
        print(f"[중단] 알 수 없는 슬러그: {args.only}", file=sys.stderr)
        return 2

    # 같은 구를 여러 단지가 공유한다. 구·월 조합은 한 번만 받는다.
    need = sorted({(t[1], m) for t in targets for m in args.months})
    cache, failures = {}, []
    for i, (gu, ym) in enumerate(need, 1):
        try:
            cache[(gu, ym)] = fetch(key, gu, ym)
            print(f"  {i}/{len(need)} {gu} {ym} {len(cache[(gu, ym)]):>5,}건", flush=True)
        except RentError as exc:
            failures.append({"gu": gu, "month": ym, "reason": str(exc)})
            print(f"  [실패] {gu} {ym}: {exc}", file=sys.stderr)
        time.sleep(0.4)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    summary = []
    for slug, gu, names in targets:
        info = json.loads((INFO_DIR / f"{slug}.json").read_text(encoding="utf-8"))
        rows = [r for m in args.months for r in cache.get((gu, m), []) if r["apt"] in names]
        households = info["household_count"]
        metrics = derive(rows, households)
        complete = metrics is not None
        payload = {
            "slug": slug,
            "complex_name": info["complex_name"],
            "rtms_apt_names": sorted({r["apt"] for r in rows}) or names,
            "months": args.months,
            "sample_size": len(rows),
            "household_count": households,
            "household_count_source": info.get("household_count_source"),
            "complete": complete,
            "min_sample": MIN_SAMPLE,
            "metrics": metrics,
            "raw_stats": raw_stats(rows) if rows else None,
            "contract_type_mix": dict(Counter(r["contract_type"] for r in rows if r["contract_type"])),
            "fetched_at": fetched_at,
            "note": ("계약일 기준 집계. 계약일로부터 30일 이내 신고이므로 최근 달은 아직 덜 찼다. "
                     "지표는 전부 비가격이며 보증금·월세는 raw_stats 대조용이다"),
            "source": SOURCE,
            "failures": [f for f in failures if f["gu"] == gu],
        }
        if not complete:
            print(f"  [주의] {slug}: 표본 {len(rows)}건 < {MIN_SAMPLE} → metrics null, complete false",
                  file=sys.stderr)
        (OUT_DIR / f"{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary.append((slug, info["complex_name"], len(rows), metrics))

    print(f"\n{'단지':22}{'표본':>6}{'전세%':>7}{'갱신%':>7}{'갱신권%':>8}{'회전%':>7}{'60이하%':>8}{'저층%':>7}")
    for slug, name, n, m in summary:
        if not m:
            print(f"  {name[:18]:20}{n:>6}   표본 부족 — 이번 라운드에서 제외")
            continue
        print(f"  {name[:18]:20}{n:>6}{m['전세 비중']:>7.1f}{m['갱신계약 비율']:>7.1f}"
              f"{m['갱신요구권 사용률']:>8.1f}{m['전월세 회전율']:>7.1f}"
              f"{m['60㎡이하 계약 비중']:>8.1f}{m['저층 계약 비중']:>7.1f}")
    print(f"\n→ {OUT_DIR.relative_to(REPO)} · 조회 실패 {len(failures)}건")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
