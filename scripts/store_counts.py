#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""소상공인시장진흥공단 상가(상권)정보 — 단지가 속한 법정동의 업종별 업소 수.

공공데이터포털 15012005. 기존 `KAPT_SERVICE_KEY`로 받아진다(11/7 확인, 활용신청 불필요).
  B553077/api/open/sdsc2/storeListInDong   divId=signguCd 로 구 전체를 받는다

왜 구 단위로 받아 동으로 나누나
  `divId=ldongCd`(법정동)·`adongCd`(행정동)는 11/8 기준 10자리·8자리·7자리 전부
  `INVALID_REQUEST_PARAMETER_ERROR` 다. 구 단위(`signguCd`)는 되고 응답 행마다
  `ldongCd`(10자리 법정동코드)가 있어서, 우리 쪽에서 동별로 센다.
  `data/ldcode.json`의 단지 법정동코드와 같은 체계라 바로 맞춰진다.

무엇을 저장하나
  업소 이름·주소·좌표는 저장하지 않는다. **동별 개수만** 남긴다(`removed_fields`).
  법정동 전체의 수이지 단지 도보권의 수가 아니다 — 글에 그렇게 적는다.

이 자료의 성격
  소상공인진흥공단이 여러 인허가 자료를 모아 가공한 수집본이다. 나이스 학원 등록 수,
  심평원 요양기관 수와 다를 수 있다. 다르면 그 차이 자체가 소재이고, 섞어 더하지 않는다.
  갱신은 분기 단위다. 조회일을 `checked_at`에 남기고 글에도 적는다.

사용법:
  python3 store_counts.py                       # 5개 구 전부, 기본 업종 묶음
  python3 store_counts.py --gu 11710            # 송파구만
  python3 store_counts.py --codes P10501 R10202 # 업종 골라서
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "stores"
LDCODE = REPO / "data" / "ldcode.json"
API = "https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInDong"
UA = "danji-content-agent/1.0"
ROWS = 1000

SOURCE = {"label": "소상공인시장진흥공단 상가(상권)정보",
          "url": "https://www.data.go.kr/data/15012005/openapi.do",
          "publisher": "소상공인시장진흥공단"}

# 자치구 코드 → 이름. 서버에 남은 단지 6곳이 있는 5개 구.
GU = {"11710": "송파구", "11680": "강남구", "11650": "서초구", "11740": "강동구", "11440": "마포구"}

# 소분류 코드(indsSclsCd). 11/8 `smallUpjongList`(247종)에서 골랐다.
# 묶음 이름은 우리가 붙인 것이고 글에는 공단의 소분류 이름을 그대로 쓴다.
CODES = {
    # 교육
    "P10501": ("교육", "입시·교과학원"),
    "P10615": ("교육", "외국어학원"),
    "P10611": ("교육", "미술학원"),
    "P10609": ("교육", "음악학원"),
    "P10601": ("교육", "태권도/무술학원"),
    "P10603": ("교육", "요가/필라테스 학원"),
    "P10627": ("교육", "컴퓨터 학원"),
    "R10202": ("교육", "독서실/스터디 카페"),
    # 보건
    "Q10201": ("보건", "내과/소아과 의원"),
    "Q10210": ("보건", "치과의원"),
    "Q10211": ("보건", "한의원"),
    "Q10206": ("보건", "이비인후과 의원"),
    "Q10205": ("보건", "안과 의원"),
    "Q10102": ("보건", "일반병원"),
    "Q10101": ("보건", "종합병원"),
    "G21501": ("보건", "약국"),
    # 생활
    "G20405": ("생활", "편의점"),
    "G21301": ("생활", "서점"),
    "G21302": ("생활", "문구/회화용품 소매업"),
    "S20901": ("생활", "세탁소"),
    "M11101": ("생활", "동물병원"),
    "G22001": ("생활", "애완동물/애완용품 소매업"),
    "R10307": ("생활", "헬스장"),
    "R10308": ("생활", "수영장"),
    "L10203": ("생활", "부동산 중개/대리업"),
}

# 저장하지 않는 응답 칸. 개수만 남기므로 업소를 특정할 수 있는 칸은 전부 버린다.
REMOVED_FIELDS = ["bizesId", "bizesNm", "brchNm", "lnoAdr", "rdnmAdr", "lnoCd", "bldMngNo",
                  "bldNm", "dongNo", "flrNo", "hoNo", "lon", "lat", "oldZipcd", "newZipcd"]


class StoreError(RuntimeError):
    pass


def fetch_page(key, gu, code, page):
    q = {"divId": "signguCd", "key": gu, "indsSclsCd": code,
         "numOfRows": ROWS, "pageNo": page, "type": "json"}
    url = API + "?" + urllib.parse.urlencode(q) + "&serviceKey=" + urllib.parse.quote(key, safe="")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.loads(r.read().decode("utf-8"))
            h = j.get("header", {})
            rc = h.get("resultCode")
            if rc == "00":
                b = j.get("body", {})
                return int(b.get("totalCount") or 0), (b.get("items") or [])
            if rc == "03":  # NODATA
                return 0, []
            raise StoreError(f"{gu} {code} p{page}: {rc} {h.get('resultMsg')}")
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(2 * (attempt + 1))  # apis.data.go.kr 은 연결이 가끔 끊긴다
    raise StoreError(f"{gu} {code} p{page}: 재시도 실패 {last}")


def fetch_code(key, gu, code):
    total, items = fetch_page(key, gu, code, 1)
    page = 1
    while len(items) < total:
        page += 1
        _, more = fetch_page(key, gu, code, page)
        if not more:
            break
        items.extend(more)
    if len(items) != total:
        raise StoreError(f"{gu} {code}: totalCount {total} 인데 받은 행 {len(items)}")
    return items


def count_dong(items):
    by_ld = Counter()
    by_ad = Counter()
    names_ld, names_ad = {}, {}
    for it in items:
        ld, ad = it.get("ldongCd"), it.get("adongCd")
        by_ld[ld] += 1
        by_ad[ad] += 1
        names_ld[ld] = it.get("ldongNm")
        names_ad[ad] = it.get("adongNm")
    return ({c: {"name": names_ld[c], "count": n} for c, n in sorted(by_ld.items())},
            {c: {"name": names_ad[c], "count": n} for c, n in sorted(by_ad.items())})


def run(key, gus, codes, today):
    ld = json.load(open(LDCODE, encoding="utf-8"))["complexes"]
    complexes = {slug: v["ld_code"] for slug, v in ld.items()}
    out_dir = OUT_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for gu in gus:
        result = {
            "source": SOURCE,
            "api": API,
            "checked_at": today,
            "signgu_code": gu,
            "signgu_name": GU[gu],
            "unit": "법정동 전체의 업소 수. 단지 도보권이 아니다",
            "nature": "소상공인진흥공단 수집본. 나이스·심평원 등 인허가 원부와 다를 수 있다",
            "removed_fields": REMOVED_FIELDS,
            "codes": {},
        }
        for code in codes:
            group, name = CODES[code]
            items = fetch_code(key, gu, code)
            by_ld, by_ad = count_dong(items)
            result["codes"][code] = {"group": group, "name": name, "total": len(items),
                                     "by_ldong": by_ld, "by_adong": by_ad}
            print(f"  {GU[gu]} {code} {name}: {len(items)}", file=sys.stderr)
        # 이 구에 있는 단지의 동 값만 따로 모아 둔다 — 글이 읽는 칸
        result["complexes"] = {}
        for slug, code10 in complexes.items():
            if code10[:5] != gu:
                continue
            row = {"ld_code": code10, "ld_name": None, "counts": {}}
            for code, v in result["codes"].items():
                cell = v["by_ldong"].get(code10)
                row["counts"][code] = cell["count"] if cell else 0
                if cell and not row["ld_name"]:
                    row["ld_name"] = cell["name"]
            result["complexes"][slug] = row
        path = out_dir / f"{gu}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gu", nargs="*", default=list(GU), help="자치구 코드 5자리")
    ap.add_argument("--codes", nargs="*", default=list(CODES), help="소분류 코드")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="조회일(폴더 이름)")
    a = ap.parse_args()
    key = os.environ.get("KAPT_SERVICE_KEY")
    if not key:
        sys.exit("KAPT_SERVICE_KEY 가 없다. .env 를 확인한다")
    bad = [g for g in a.gu if g not in GU] + [c for c in a.codes if c not in CODES]
    if bad:
        sys.exit(f"모르는 코드: {bad}")
    paths = run(key, a.gu, a.codes, a.date)
    for p in paths:
        print(p.relative_to(REPO))


if __name__ == "__main__":
    main()
