#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""나이스 교육정보 개방포털 학원·교습소 정보 — 자치구별 분야 집계.

  https://open.neis.go.kr/hub/acaInsTiInfo   서울시교육청 ATPT_OFCDC_SC_CODE=B10

키 없이 되는 것 / 안 되는 것 (11/8 확인)
  키 없이 부르면 행은 5개만 오지만 `list_total_count`는 전체 값이다. 그리고
  `REALM_SC_NM`(분야) 필터는 적용된다 — 분야별 총수를 더하면 구 총수와 같다(5개 구 전부).
  `ACA_INSTI_SC_NM`(학원/교습소) 필터는 **무시된다**(총수가 그대로 온다). 학원·교습소 구분,
  동별 수, 정원 합계는 행을 다 받아야 하므로 키가 필요하다.
  키는 open.neis.go.kr 회원가입 뒤 즉시 발급(무료). `.env`의 `NEIS_KEY`로 읽는다.

개인정보
  `FA_TELNO`(전화번호)에 개인 휴대전화가 섞여 있다. 행을 받을 때 저장 전에 지운다.
  저장은 집계값이고, 행 단위 원본은 남기지 않는다.

사용법:
  python3 neis_academy.py                    # 5개 구, 분야별 총수(키 불필요)
  NEIS_KEY=... python3 neis_academy.py       # 전량 받아 학원/교습소·동별·정원까지
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "academies"
API = "https://open.neis.go.kr/hub/acaInsTiInfo"
UA = "danji-content-agent/1.0"
OFFICE = "B10"  # 서울특별시교육청

SOURCE = {"label": "나이스 교육정보 개방포털 학원교습소정보",
          "url": "https://open.neis.go.kr/portal/data/service/selectServicePage.do?infId=OPEN17320190722180924242823",
          "publisher": "교육부·한국교육학술정보원"}

GUS = ["송파구", "강남구", "서초구", "강동구", "마포구"]

# 나이스 분야 구분(REALM_SC_NM). 11/8 다섯 구에서 합이 총수와 같은지 확인한 목록.
REALMS = ["입시.검정 및 보습", "예능(대)", "국제화", "독서실", "종합(대)", "직업기술",
          "인문사회(대)", "기타(대)", "정보", "기예(대)", "특수교육", "종합", "예능", "기예"]

REMOVED_FIELDS = ["FA_TELNO"]
DONG_RE = re.compile(r"\(([가-힣0-9]+동)[,)\s]")


class NeisError(RuntimeError):
    pass


def call(params, key=None, page=1, size=5):
    q = {"Type": "json", "pIndex": page, "pSize": size, "ATPT_OFCDC_SC_CODE": OFFICE}
    q.update(params)
    if key:
        q["KEY"] = key
    url = API + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.loads(r.read().decode("utf-8"))
            if "acaInsTiInfo" in j:
                head = j["acaInsTiInfo"][0]["head"]
                total = head[0]["list_total_count"]
                rows = j["acaInsTiInfo"][1].get("row", [])
                return total, rows
            code = j.get("RESULT", {}).get("CODE", "")
            if code == "INFO-200":  # 해당하는 데이터가 없습니다
                return 0, []
            raise NeisError(f"{params}: {j.get('RESULT')}")
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise NeisError(f"{params}: 재시도 실패 {last}")


def totals(gu):
    total, _ = call({"ADMST_ZONE_NM": gu})
    by_realm = {}
    for r in REALMS:
        n, _ = call({"ADMST_ZONE_NM": gu, "REALM_SC_NM": r})
        if n:
            by_realm[r] = n
    if sum(by_realm.values()) != total:
        raise NeisError(f"{gu}: 분야 합 {sum(by_realm.values())} ≠ 총수 {total}. REALMS 목록을 다시 본다")
    return total, by_realm


def full_rows(gu, key):
    rows = []
    page = 1
    while True:
        total, batch = call({"ADMST_ZONE_NM": gu}, key=key, page=page, size=1000)
        for r in batch:
            for f in REMOVED_FIELDS:
                r.pop(f, None)
        rows.extend(batch)
        if len(rows) >= total or not batch:
            break
        page += 1
    if len(rows) != total:
        raise NeisError(f"{gu}: 총수 {total} 인데 받은 행 {len(rows)}")
    return rows


def dong_of(row):
    # 도로명주소 상세(FA_RDNDA)의 괄호 안 법정동. "…, 101호(장지동)" 꼴. 없으면 None
    for f in ("FA_RDNDA", "FA_RDNMA"):
        m = DONG_RE.search((row.get(f) or "") + " ")
        if m:
            return m.group(1)
    return None


def aggregate(rows):
    open_rows = [r for r in rows if (r.get("REG_STTUS_NM") or "").strip() == "개원"]
    agg = {
        "rows": len(rows),
        "status": dict(Counter((r.get("REG_STTUS_NM") or "").strip() for r in rows)),
        "institution": dict(Counter((r.get("ACA_INSTI_SC_NM") or "").strip() for r in open_rows)),
        "realm": dict(Counter((r.get("REALM_SC_NM") or "").strip() for r in open_rows)),
        "course": dict(Counter((r.get("LE_CRSE_NM") or "").strip() or "(없음)" for r in open_rows).most_common(40)),
        "capacity_sum": sum(int(r.get("TOFOR_SMTOT") or 0) for r in open_rows),
        "by_dong": {},
        "dong_unresolved": 0,
    }
    dong = Counter()
    dong_realm = {}
    for r in open_rows:
        d = dong_of(r)
        if not d:
            agg["dong_unresolved"] += 1
            continue
        dong[d] += 1
        dong_realm.setdefault(d, Counter())[(r.get("REALM_SC_NM") or "").strip()] += 1
    agg["by_dong"] = {d: {"count": n, "realm": dict(dong_realm[d])} for d, n in dong.most_common()}
    return agg


def run(gus, key, today):
    out_dir = OUT_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for gu in gus:
        total, by_realm = totals(gu)
        res = {"source": SOURCE, "api": API, "checked_at": today, "gu": gu, "office": OFFICE,
               "total": total, "by_realm": by_realm,
               "note": "총수·분야별 수는 키 없이 list_total_count 로 받은 값. 등록 상태 구분 없음(개원·휴원·폐원 포함 여부 미확인)",
               "removed_fields": REMOVED_FIELDS, "full": None}
        if key:
            rows = full_rows(gu, key)
            res["full"] = aggregate(rows)
            res["note"] = "full 은 행 전량에서 집계. institution·realm·by_dong·capacity_sum 은 '개원' 상태만"
        print(f"  {gu}: {total} {by_realm}", file=sys.stderr)
        p = out_dir / f"{gu}.json"
        p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(p)
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gu", nargs="*", default=GUS)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    key = os.environ.get("NEIS_KEY") or None
    if not key:
        print("NEIS_KEY 없음 — 분야별 총수만 받는다(행은 받지 않는다)", file=sys.stderr)
    for p in run(a.gu, key, a.date):
        print(p.relative_to(REPO))


if __name__ == "__main__":
    main()
