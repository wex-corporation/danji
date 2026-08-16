#!/usr/bin/env python3
"""K-apt 공동주택 관리비 조회 — 단지별 ㎡당 공용관리비 캐시 생성기.

공공데이터포털(apis.data.go.kr) OpenAPI만 사용한다. k-apt.go.kr 직접 조회는
차단되므로 경로에서 제외했다. 표준 라이브러리만 쓴다.

엔드포인트는 키 없이 실재 여부를 확인해 확정한 것들이다.
없는 경로는 NO_OPENAPI_SERVICE, 있는 경로는 SERVICE_KEY_IS_NOT_REGISTERED가 돌아온다.

  공용관리비 17항목  1613000/AptCmnuseManageCostServiceV2/getHsmp*InfoV2
  단지 상세(면적)    1613000/AptBasisInfoServiceV4/getAphusDtlInfoV4
  단지 기본          1613000/AptBasisInfoServiceV4/getAphusBassInfoV4
  시군구 단지목록    1613000/AptListService3/getSigunguAptList3

사용법:
  export KAPT_SERVICE_KEY="발급받은_디코딩_키"
  python3 kapt_fees.py --month 202606                 # 전 단지
  python3 kapt_fees.py --complex one-bailey --month 202606
  python3 kapt_fees.py --probe                        # 키 없이 엔드포인트 점검

원칙: 확인 못 한 수치는 만들지 않는다. 한 항목이라도 조회에 실패하면
complete=false로 기록하고, 본문 인용 대상에서 제외한다.
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
from pathlib import Path

BASE = "https://apis.data.go.kr/1613000"
COST_SVC = f"{BASE}/AptCmnuseManageCostServiceV2"
BASIS_SVC = f"{BASE}/AptBasisInfoServiceV4"
LIST_SVC = f"{BASE}/AptListService3"

REPO = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO / "data" / "mgmt-fees"

# 공용관리비 17개 항목. K-apt 공개 분류 그대로다.
COMMON_FEE_OPS = [
    ("getHsmpLaborCostInfoV2", "인건비"),
    ("getHsmpOfcrkCostInfoV2", "제사무비"),
    ("getHsmpTaxdueInfoV2", "제세공과금"),
    ("getHsmpClothingCostInfoV2", "피복비"),
    ("getHsmpEduTraingCostInfoV2", "교육훈련비"),
    ("getHsmpVhcleMntncCostInfoV2", "차량유지비"),
    ("getHsmpEtcCostInfoV2", "그 밖의 부대비용"),
    ("getHsmpGuardCostInfoV2", "경비비"),
    ("getHsmpCleaningCostInfoV2", "청소비"),
    ("getHsmpDisinfectionCostInfoV2", "소독비"),
    ("getHsmpElevatorMntncCostInfoV2", "승강기유지비"),
    ("getHsmpHomeNetworkMntncCostInfoV2", "지능형 홈네트워크 설비 유지비"),
    ("getHsmpRepairsCostInfoV2", "수선비"),
    ("getHsmpFacilityMntncCostInfoV2", "시설유지비"),
    ("getHsmpSafetyCheckUpCostInfoV2", "안전점검비"),
    ("getHsmpDisasterPreventionCostInfoV2", "재해예방비"),
    ("getHsmpConsignManageFeeInfoV2", "위탁관리수수료"),
]

# 응답 item에서 금액이 아닌 식별 필드. 합계에서 제외한다.
NON_AMOUNT_FIELDS = {"kaptCode", "kaptName", "resultCode", "resultMsg"}

# 서울 자치구 법정동 시군구코드. 단지코드 조회에 쓴다.
SIGUNGU = {
    "서초구": "11650",
    "강남구": "11680",
    "송파구": "11710",
    "강동구": "11740",
    "마포구": "11440",
}

# 캐시 대상 단지. name은 K-apt 등록 명칭 기준으로 맞춰야 조회된다.
TARGETS = [
    ("one-bailey", "래미안 원베일리", "서초구"),
    ("acro-river-park", "아크로리버파크", "서초구"),
    ("eunma", "은마아파트", "강남구"),
    ("dh-firstier", "디에이치 퍼스티어 아이파크", "강남구"),
    ("helio-city", "헬리오시티", "송파구"),
    ("jamsil-els", "잠실엘스", "송파구"),
    ("ricents", "리센츠", "송파구"),
    ("parkrio", "파크리오", "송파구"),
    ("olympic-park-foreon", "올림픽파크 포레온", "강동구"),
    ("godeok-gracium", "고덕그라시움", "강동구"),
    ("mapo-raemian-prugio", "마포래미안푸르지오", "마포구"),
]


UA = "danji-content-agent/1.0"

# 포털이 내려주는 오류 코드. 인증·권한·한도 오류는 재시도해도 결과가 같다.
PORTAL_ERRORS = {
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR":
        "등록되지 않은 서비스키입니다. 발급 직후라면 반영까지 최대 1시간 걸립니다",
    "SERVICE_ACCESS_DENIED_ERROR":
        "활용신청이 승인되지 않았습니다. 마이페이지에서 승인 상태를 확인하세요",
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR":
        "일일 호출 한도를 초과했습니다 (개발계정 기본 5,000건)",
    "DEADLINE_HAS_EXPIRED_ERROR": "활용기간이 만료됐습니다. 연장 신청이 필요합니다",
    "UNREGISTERED_IP_ERROR": "등록되지 않은 IP입니다",
    "NO_OPENAPI_SERVICE_ERROR": "해당 오픈API 서비스가 없거나 폐기됐습니다",
    "HTTP_ERROR": "포털 내부 오류",
}


class KaptError(RuntimeError):
    pass


def _classify(text):
    for code, message in PORTAL_ERRORS.items():
        if code in text:
            return f"{message} [{code}]"
    return None


def _http_get(url, timeout=20, retries=3):
    """포털 오류와 네트워크 오류를 구분한다. 인증 오류는 재시도하지 않는다."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            known = _classify(body)
            if known:
                raise KaptError(known) from exc
            if exc.code < 500:
                raise KaptError(f"HTTP {exc.code} — {body[:160]}") from exc
            last = exc  # 5xx는 재시도 가치가 있다
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    raise KaptError(f"네트워크 실패: {last}")


def service_key():
    key = os.environ.get("KAPT_SERVICE_KEY") or os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not key:
        raise KaptError(
            "KAPT_SERVICE_KEY가 없습니다. 공공데이터포털에서 "
            "'공동주택관리비(공용관리비)정보제공서비스' 활용신청 후 "
            "일반 인증키(Decoding)를 넣으세요."
        )
    return key


def _request(url, params):
    """단건 호출. JSON을 먼저 시도하고 XML로 떨어지면 XML로 읽는다."""
    q = dict(params)
    q["_type"] = "json"
    text = _http_get(f"{url}?{urllib.parse.urlencode(q)}").strip()
    # 포털은 오류를 200 본문으로 내려주기도 한다.
    known = _classify(text)
    if known:
        raise KaptError(known)
    if text.startswith("{"):
        data = json.loads(text)
        resp_obj = data.get("response", data)
        header = resp_obj.get("header", {})
        code = str(header.get("resultCode", "")).zfill(2)
        if code not in ("00", ""):
            raise KaptError(f"{header.get('resultMsg', 'API 오류')} (resultCode={code})")
        body = resp_obj.get("body") or {}
        return body.get("item") or {}

    # XML 경로. 인증 오류는 여기로 떨어지는 경우가 많다.
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise KaptError(f"응답 파싱 실패: {text[:160]}") from exc
    err = root.findtext(".//errMsg") or root.findtext(".//returnAuthMsg")
    if err:
        raise KaptError(f"{err} / {root.findtext('.//returnReasonCode') or ''}".strip(" /"))
    code = (root.findtext(".//resultCode") or "").strip()
    if code and code.zfill(2) != "00":
        raise KaptError(f"{root.findtext('.//resultMsg') or 'API 오류'} (resultCode={code})")
    item = root.find(".//item")
    if item is None:
        return {}
    return {child.tag: (child.text or "").strip() for child in item}


def _sum_amounts(item):
    """item의 금액 필드를 모두 더한다. K-apt는 항목별 세부 비목을 나눠 준다."""
    total = 0
    used = {}
    for key, value in item.items():
        if key in NON_AMOUNT_FIELDS:
            continue
        if value in (None, "", "-"):
            continue
        try:
            amount = float(str(value).replace(",", ""))
        except ValueError:
            continue
        total += amount
        used[key] = amount
    return int(round(total)), used


def resolve_kapt_code(key, name, gu):
    """시군구 단지목록에서 단지코드를 찾는다."""
    code = SIGUNGU.get(gu)
    if not code:
        raise KaptError(f"시군구코드 미등록: {gu}")
    url = f"{LIST_SVC}/getSigunguAptList3"
    q = {"serviceKey": key, "sigunguCode": code, "pageNo": 1, "numOfRows": 1000, "_type": "json"}
    raw = _http_get(f"{url}?{urllib.parse.urlencode(q)}", timeout=25).strip()
    known = _classify(raw)
    if known:
        raise KaptError(known)
    items = []
    if raw.startswith("{"):
        body = json.loads(raw).get("response", {}).get("body", {}) or {}
        node = body.get("items") or {}
        items = node.get("item", []) if isinstance(node, dict) else node
        if isinstance(items, dict):
            items = [items]
    else:
        root = ET.fromstring(raw)
        err = root.findtext(".//errMsg") or root.findtext(".//returnAuthMsg")
        if err:
            raise KaptError(err)
        items = [
            {c.tag: (c.text or "").strip() for c in it} for it in root.findall(".//item")
        ]

    def norm(s):
        return "".join(str(s).split()).replace("아파트", "")

    target = norm(name)
    for it in items:
        if norm(it.get("kaptName", "")) == target:
            return it.get("kaptCode"), it.get("kaptName")
    for it in items:
        if target in norm(it.get("kaptName", "")) or norm(it.get("kaptName", "")) in target:
            return it.get("kaptCode"), it.get("kaptName")
    raise KaptError(f"단지코드를 찾지 못했습니다: {name} ({gu}, 후보 {len(items)}건)")


def fetch_area(key, kapt_code):
    """관리비부과면적(㎡)을 가져온다. 필드명이 버전에 따라 달라 후보를 순회한다."""
    item = _request(f"{BASIS_SVC}/getAphusDtlInfoV4", {"serviceKey": key, "kaptCode": kapt_code})
    for field in ("kaptMparea", "kaptMarea", "kaptTarea", "kaptdaArea", "privArea"):
        value = item.get(field)
        if value:
            try:
                area = float(str(value).replace(",", ""))
            except ValueError:
                continue
            if area > 0:
                return area, field
    raise KaptError(f"관리비부과면적을 찾지 못했습니다. 응답 필드: {sorted(item)[:12]}")


def fetch_common_fees(key, kapt_code, yyyymm):
    """공용관리비 17항목을 조회한다. 실패 항목은 감추지 않고 그대로 남긴다."""
    items, failures = {}, {}
    for op, label in COMMON_FEE_OPS:
        try:
            raw = _request(f"{COST_SVC}/{op}", {
                "serviceKey": key, "kaptCode": kapt_code, "searchDate": yyyymm,
            })
            amount, detail = _sum_amounts(raw)
            items[label] = {"amount_won": amount, "detail": detail, "op": op}
        except KaptError as exc:
            failures[label] = str(exc)
        time.sleep(0.3)  # 포털 호출 간격. 사람이 읽는 속도 수준으로 유지한다.
    return items, failures


def build(slug, name, gu, yyyymm, key):
    kapt_code, kapt_name = resolve_kapt_code(key, name, gu)
    area, area_field = fetch_area(key, kapt_code)
    items, failures = fetch_common_fees(key, kapt_code, yyyymm)
    complete = not failures and len(items) == len(COMMON_FEE_OPS)
    total = sum(v["amount_won"] for v in items.values())
    record = {
        "slug": slug,
        "complex_name": name,
        "kapt_code": kapt_code,
        "kapt_name": kapt_name,
        "period": yyyymm,
        "area_m2": area,
        "area_field": area_field,
        "common_fee_total_won": total,
        # 반올림 전 값을 함께 남긴다. 본문 인용은 정수로 하되 검산이 가능해야 한다.
        "per_m2_won": round(total / area, 2) if area else None,
        "items": items,
        "failures": failures,
        "complete": complete,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": {
            "label": "공동주택관리정보시스템(K-apt) 공용관리비 · 공공데이터포털 OpenAPI",
            "url": "https://www.data.go.kr/data/15057937/openapi.do",
            "publisher": "국토교통부",
            "endpoint": f"{COST_SVC}/<항목별 오퍼레이션>",
        },
        "note": (
            "공용관리비 17개 항목 합계를 관리비부과면적으로 나눈 값이다. "
            "개별사용료(난방·급탕·전기·수도)와 장기수선충당금은 포함하지 않는다."
        ),
    }
    if not complete:
        record["warning"] = "일부 항목 조회 실패. 본문 인용 금지 대상."
    return record


def probe():
    """키 없이 엔드포인트 실재 여부만 점검한다."""
    paths = [f"{COST_SVC}/{op}" for op, _ in COMMON_FEE_OPS] + [
        f"{BASIS_SVC}/getAphusDtlInfoV4",
        f"{BASIS_SVC}/getAphusBassInfoV4",
        f"{LIST_SVC}/getSigunguAptList3",
    ]
    ok = 0
    for path in paths:
        url = f"{path}?serviceKey=PROBE"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "danji-content-agent/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - 점검용이므로 사유만 보여준다
            print(f"  ?? {path.split('/')[-1]:36} {exc}")
            continue
        if "SERVICE_KEY_IS_NOT_REGISTERED" in text:
            print(f"  OK {path.split('/')[-1]:36} 실재 (키만 있으면 조회 가능)")
            ok += 1
        elif "NO_OPENAPI_SERVICE" in text:
            print(f"  XX {path.split('/')[-1]:36} 경로 없음")
        else:
            print(f"  ?? {path.split('/')[-1]:36} {text[:70]}")
        time.sleep(0.4)
    print(f"\n{ok}/{len(paths)} 엔드포인트 확인")
    return 0 if ok == len(paths) else 1


def main():
    ap = argparse.ArgumentParser(description="K-apt 단지별 ㎡당 공용관리비 캐시 생성")
    ap.add_argument("--month", help="조회 월 YYYYMM (예: 202606)")
    ap.add_argument("--complex", dest="only", help="슬러그 하나만 조회")
    ap.add_argument("--probe", action="store_true", help="키 없이 엔드포인트 점검")
    args = ap.parse_args()

    if args.probe:
        return probe()

    if not args.month:
        ap.error("--month가 필요합니다 (예: --month 202606)")

    try:
        key = service_key()
    except KaptError as exc:
        print(f"[중단] {exc}\n", file=sys.stderr)
        print("발급 절차:", file=sys.stderr)
        print("  1. data.go.kr 로그인", file=sys.stderr)
        print("  2. '공동주택관리비(공용관리비)정보제공서비스' 활용신청", file=sys.stderr)
        print("     https://www.data.go.kr/data/15057937/openapi.do", file=sys.stderr)
        print("  3. 마이페이지 > 오픈API > 인증키(Decoding) 복사", file=sys.stderr)
        print("  4. export KAPT_SERVICE_KEY='...'", file=sys.stderr)
        print("\n엔드포인트만 점검하려면: python3 kapt_fees.py --probe", file=sys.stderr)
        return 2

    targets = [t for t in TARGETS if not args.only or t[0] == args.only]
    if not targets:
        print(f"[중단] 알 수 없는 슬러그: {args.only}", file=sys.stderr)
        return 2

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    for slug, name, gu in targets:
        try:
            record = build(slug, name, gu, args.month, key)
        except KaptError as exc:
            print(f"[실패] {name}: {exc}", file=sys.stderr)
            fail += 1
            continue
        path = CACHE_DIR / f"{slug}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        flag = "" if record["complete"] else "  (일부 항목 실패 — 인용 금지)"
        print(f"[완료] {name}: ㎡당 {record['per_m2_won']}원 · {args.month}{flag}")
        ok += 1

    print(f"\n성공 {ok} / 실패 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
