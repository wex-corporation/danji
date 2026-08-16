#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""K-apt 단지 기본·상세 정보 캐시 — 홍보글이 인용할 사실 표를 만든다.

공동주택 기본 정보제공 서비스(AptBasisInfoServiceV4) 두 오퍼레이션을 합친다.

  getAphusBassInfoV4  세대수·동수·층수·사용승인일·관리비부과면적·전용면적별 세대현황·시공사
  getAphusDtlInfoV4   주차·승강기·CCTV·인력·지하철·복리시설·편의시설·교육시설

명세 7.2.1이 홍보 페르소나에게 허용한 것이 정확히 이 범위다.
"세대수·동수·주차·시설·역·학교처럼 공개 자료로 확인되는 항목만 쓴다."
여기 없는 항목은 홍보글에 쓰지 않는다.

필드 이름이 헷갈리기 쉬워 주석을 달아 둔다. 실제로 헷갈렸던 것들이다.
  kaptdEcnt   승강기 대수      (kaptdScnt 가 아니다)
  kaptdScnt   경비 인원        (승강기도 CCTV도 아니다)
  kaptdCccnt  CCTV 대수
  kaptdClcnt  청소 인원
  kaptMgrCnt  일반관리 인원
  kaptMarea   관리비부과면적   (kaptTarea 는 건축물대장 연면적이라 훨씬 크다)

사용법:
  export KAPT_SERVICE_KEY=...
  python3 kapt_complex_info.py             # 전 단지
  python3 kapt_complex_info.py --complex one-bailey
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kapt_fees as K  # noqa: E402  경로·오류처리·키 로딩을 그대로 쓴다

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "complex-info"

# 응답 필드 → 우리가 쓰는 이름. 주석은 위 문서 참고.
BASS_FIELDS = {
    "kaptName": "kapt_name", "kaptDongCnt": "dong_count", "kaptdaCnt": "household_count",
    "kaptTopFloor": "top_floor", "kaptUsedate": "use_approval_date",
    "kaptMarea": "billed_area_m2", "kaptTarea": "gross_floor_area_m2",
    "privArea": "private_area_sum_m2", "codeHeatNm": "heating", "codeMgrNm": "manage_type",
    "codeHallNm": "hall_type", "kaptBcompany": "builder", "kaptAcompany": "developer",
    "doroJuso": "road_address", "kaptAddr": "address", "hoCnt": "ho_count",
    "kaptMparea60": "hh_upto60", "kaptMparea85": "hh_60_85",
    "kaptMparea135": "hh_85_135", "kaptMparea136": "hh_over135",
}
DTL_FIELDS = {
    "kaptdPcnt": "parking_ground", "kaptdPcntu": "parking_underground",
    "kaptdEcnt": "elevator_count", "kaptdCccnt": "cctv_count",
    "kaptMgrCnt": "staff_manage", "kaptdScnt": "staff_security", "kaptdClcnt": "staff_clean",
    "kaptCcompany": "manage_company", "kaptdSecCom": "security_company",
    "codeStr": "structure", "codeSec": "security_type", "codeClean": "clean_type",
    "codeElev": "elevator_type", "codeGarbage": "garbage_type",
    "subwayLine": "subway_line", "subwayStation": "subway_station",
    "kaptdWtimesub": "subway_walk", "kaptdWtimebus": "bus_walk",
    "welfareFacility": "welfare_facility", "convenientFacility": "convenient_facility",
    "educationFacility": "education_facility",
    "groundElChargerCnt": "ev_ground", "undergroundElChargerCnt": "ev_underground",
}

NUMERIC = {
    "dong_count", "household_count", "top_floor", "billed_area_m2", "gross_floor_area_m2",
    "private_area_sum_m2", "ho_count", "hh_upto60", "hh_60_85", "hh_85_135", "hh_over135",
    "parking_ground", "parking_underground", "elevator_count", "cctv_count",
    "staff_manage", "staff_security", "staff_clean", "ev_ground", "ev_underground",
}


def _clean(raw, mapping):
    out = {}
    for src, dst in mapping.items():
        v = raw.get(src)
        if v in (None, "", "-"):
            continue
        if dst in NUMERIC:
            try:
                f = float(str(v).replace(",", ""))
            except ValueError:
                continue
            out[dst] = int(f) if f == int(f) else f
        else:
            out[dst] = str(v).strip()
    return out


def build(slug, name, gu, key):
    kapt_code, kapt_name = K.resolve_kapt_code(key, name, gu)
    bass = K._request(f"{K.BASIS_SVC}/getAphusBassInfoV4",
                      {"serviceKey": key, "kaptCode": kapt_code})
    if K._is_no_data(bass):
        raise K.KaptError("기본정보 응답이 비어 있습니다")
    time.sleep(0.3)
    dtl = K._request(f"{K.BASIS_SVC}/getAphusDtlInfoV4",
                     {"serviceKey": key, "kaptCode": kapt_code})

    rec = {"slug": slug, "complex_name": name, "kapt_code": kapt_code,
           "kapt_name": kapt_name}
    rec.update(_clean(bass, BASS_FIELDS))
    rec.update(_clean(dtl, DTL_FIELDS) if not K._is_no_data(dtl) else {})

    # 세대수 보정. K-apt는 단지에 따라 kaptdaCnt를 0으로 비워 둔다
    # (디에이치 퍼스티어 아이파크가 그렇다). 이때 호수(hoCnt)가 실제 세대수와
    # 맞으므로 대체하되, 어느 필드를 썼는지 남겨 인용할 때 판단할 수 있게 한다.
    if not rec.get("household_count") and rec.get("ho_count"):
        rec["household_count"] = rec["ho_count"]
        rec["household_count_source"] = "hoCnt (kaptdaCnt가 0으로 비어 있음)"
    elif rec.get("household_count"):
        rec["household_count_source"] = "kaptdaCnt"

    # 파생값. 계산으로 나온 것임을 이름에 남긴다.
    pg, pu = rec.get("parking_ground", 0), rec.get("parking_underground", 0)
    if pg or pu:
        rec["parking_total"] = pg + pu
    hh = rec.get("household_count")
    if hh and rec.get("parking_total"):
        rec["parking_per_household"] = round(rec["parking_total"] / hh, 2)

    # 전용면적별 세대현황도 통째로 0인 단지가 있다. 합이 0이면 아예 지운다.
    bands = ["hh_upto60", "hh_60_85", "hh_85_135", "hh_over135"]
    if sum(rec.get(b, 0) for b in bands) == 0:
        for b in bands:
            rec.pop(b, None)
        rec["area_bands_available"] = False
    else:
        rec["area_bands_available"] = True
    staff = [rec.get(k) for k in ("staff_manage", "staff_security", "staff_clean")]
    if all(s is not None for s in staff):
        rec["staff_total"] = sum(staff)

    rec["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    rec["source"] = {
        "label": "공동주택 기본 정보제공 서비스(K-apt) OpenAPI",
        "url": "https://www.data.go.kr/data/15058453/openapi.do",
        "publisher": "국토교통부",
    }
    return rec


def main():
    ap = argparse.ArgumentParser(description="K-apt 단지 기본·상세 정보 캐시")
    ap.add_argument("--complex", dest="only")
    args = ap.parse_args()

    try:
        key = K.service_key()
    except K.KaptError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    targets = [t for t in K.TARGETS if not args.only or t[0] == args.only]
    if not targets:
        print(f"[중단] 알 수 없는 슬러그: {args.only}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    for slug, name, gu in targets:
        try:
            rec = build(slug, name, gu, key)
        except K.KaptError as exc:
            print(f"[실패] {name}: {exc}", file=sys.stderr)
            fail += 1
            continue
        (OUT_DIR / f"{slug}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[완료] {name}: {rec.get('dong_count')}개동 "
              f"{rec.get('household_count'):,}세대 · 주차 {rec.get('parking_total', 0):,}대"
              f"(세대당 {rec.get('parking_per_household', 0)}) · 승강기 {rec.get('elevator_count', 0)}대")
        ok += 1
        time.sleep(0.3)

    print(f"\n성공 {ok} / 실패 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
