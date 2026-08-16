#!/usr/bin/env python3
"""K-apt 공개데이터 공개 미러(aptdamoa.com)에서 관리비를 읽는 보조 경로.

**보조 경로다. 1순위는 `kapt_fees.py`(공공데이터포털 공식 OpenAPI)다.**
공식 API 서비스키가 없을 때만 쓰고, 캐시에 `source_path: "public_mirror"`로
표시해 공식 조회분과 구분한다.

경로 선택 근거 (운영 명세 9.6.1 소스 위계):
  1순위 공공 API        → apis.data.go.kr. 키 없어 대기 중
  2순위 플랫폼 공식 API → 해당 없음
  3순위 로그인 없는 공개 페이지 저속 크롤링(robots.txt 준수) → 여기
  4순위 로그인 영역     → 금지

준수 사항 (9.6.4):
  - robots.txt 확인함: `User-agent: * / Allow: /` (2026-08-16 확인)
  - 요청 간격 1.5초 이상. 차단 신호(429·캡차) 시 즉시 중단
  - 우회 기술 미사용

한계: 단지코드를 이미 알고 있어야 한다. 이 사이트의 사이트맵은 코드만 담고
단지명이 없어 이름→코드 해석이 불가능하다. 코드 해석은 공식 API의
getSigunguAptList3가 담당하므로, 키가 들어오면 전 단지가 자동 해결된다.

사용법:
  python3 kapt_mirror.py --slug one-bailey --kapt-code A10023043 --month 202604
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO / "data" / "mgmt-fees"
BASE = "https://www.aptdamoa.com/apt"
UA = "danji-content-agent/1.0 (public management-fee lookup)"  # HTTP 헤더는 latin-1만 허용

# 미러가 쓰는 3분류. K-apt 공개 분류와 같다.
SECTIONS = ["공용관리비", "개별사용료", "장기수선충당금", "합계"]


class MirrorError(RuntimeError):
    pass


def fetch_text(kapt_code, yyyymm):
    url = f"{BASE}/{kapt_code}/{yyyymm}.html"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MirrorError(f"해당 월 자료 없음 ({yyyymm}). K-apt 공개 시점보다 이른 달일 수 있습니다.")
        if exc.code == 429:
            raise MirrorError("429 수신. 차단 신호이므로 중단합니다 (명세 9.6.4).")
        raise MirrorError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise MirrorError(f"네트워크 실패: {exc}") from exc

    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", body))
    return url, [ln.strip() for ln in text.split("\n") if ln.strip()]


def parse(lines):
    """라벨 뒤에 오는 '월간 총액'과 '단가'를 순서대로 집는다."""
    won = re.compile(r"^([\d,]+)원$")
    per = re.compile(r"^([\d,]+)원/㎡$")
    out = {}
    for i, line in enumerate(lines):
        if line not in SECTIONS or line in out:
            continue
        total = unit = None
        for j in range(i + 1, min(i + 8, len(lines))):
            if total is None and won.match(lines[j]):
                total = int(won.match(lines[j]).group(1).replace(",", ""))
            elif total is not None and per.match(lines[j]):
                unit = int(per.match(lines[j]).group(1).replace(",", ""))
                break
        if total is not None and unit is not None:
            out[line] = {"total_won": total, "per_m2_won": unit}
    missing = [s for s in SECTIONS if s not in out]
    if missing:
        raise MirrorError(f"표 파싱 실패. 누락: {missing}")
    return out


def build(slug, kapt_code, yyyymm, complex_name):
    url, lines = fetch_text(kapt_code, yyyymm)
    table = parse(lines)
    common = table["공용관리비"]
    total = table["합계"]
    # 부과면적은 총액÷단가로 역산한다. 미러가 면적을 직접 노출하지 않는다.
    area = round(total["total_won"] / total["per_m2_won"]) if total["per_m2_won"] else None
    kapt_name = next((l for l in lines[:60] if "원베일리" in l or complex_name[:4] in l), "")
    return {
        "slug": slug,
        "complex_name": complex_name,
        "kapt_code": kapt_code,
        "kapt_name_seen": kapt_name[:40],
        "period": yyyymm,
        "area_m2_derived": area,
        "common_fee_total_won": common["total_won"],
        "per_m2_won": common["per_m2_won"],
        "breakdown": {
            "공용관리비": table["공용관리비"],
            "개별사용료": table["개별사용료"],
            "장기수선충당금": table["장기수선충당금"],
            "합계": table["합계"],
        },
        "complete": True,
        "source_path": "public_mirror",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": {
            "label": f"K-apt 공개데이터 연계 관리비 · {yyyymm[:4]}년 {yyyymm[4:]}월",
            "url": url,
            "publisher": "공동주택관리정보시스템(K-apt) 원자료 · aptdamoa 공개 페이지 경유",
            "origin_url": "https://www.k-apt.go.kr/",
        },
        "note": (
            "공용관리비는 청소·경비 등 공동 비용이다. 주민 고지서 총액은 여기에 "
            "개별사용료와 장기수선충당금이 더해진 금액이며, 개별 세대 고지액이 아니라 "
            "단지 전체를 관리비 부과면적으로 나눈 단가다."
        ),
        "caveat": "공식 OpenAPI(1순위)가 아닌 공개 미러(3순위) 경유. 키 확보 후 kapt_fees.py로 재검증할 것.",
    }


def main():
    ap = argparse.ArgumentParser(description="공개 미러에서 관리비 조회 (보조 경로)")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--kapt-code", required=True)
    ap.add_argument("--month", required=True, action="append",
                    help="YYYYMM. 여러 번 주면 여러 달을 받는다")
    ap.add_argument("--name", default="래미안 원베일리")
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    records, failures = [], []
    for i, month in enumerate(args.month):
        if i:
            time.sleep(1.5)  # 명세 9.6.4 저속 요청
        try:
            records.append(build(args.slug, args.kapt_code, month, args.name))
            print(f"[완료] {args.name} {month}: 공용관리비 ㎡당 {records[-1]['per_m2_won']}원")
        except MirrorError as exc:
            failures.append((month, str(exc)))
            print(f"[실패] {args.name} {month}: {exc}", file=sys.stderr)

    if not records:
        print("\n조회된 자료가 없습니다. 캐시를 쓰지 않습니다.", file=sys.stderr)
        return 1

    records.sort(key=lambda r: r["period"], reverse=True)
    path = CACHE_DIR / f"{args.slug}.json"
    path.write_text(json.dumps({
        "slug": args.slug,
        "complex_name": args.name,
        "kapt_code": args.kapt_code,
        "latest_period": records[0]["period"],
        "periods": {r["period"]: r for r in records},
        "failed_periods": dict(failures),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{path.relative_to(REPO)} 기록 ({len(records)}개월)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
