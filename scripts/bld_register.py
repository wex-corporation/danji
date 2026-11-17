#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""건축물대장 표제부 — 단지 지번의 건물(동)마다 사용승인일·층수·세대수 등을 받는다.

국토교통부 건축HUB 건축물대장정보 서비스(공공데이터포털 15134735, 이용허락범위 제한 없음).
오퍼레이션 getBrTitleInfo(표제부). 기존 공공데이터 키(KAPT_SERVICE_KEY)로 된다(2026-11-17 확인).

- 시군구 5 + 법정동 5는 data/ldcode.json 의 ld_code 에서, 번·지는 K-apt 기본정보 지번 주소에서 뽑는다.
  손으로 적지 않는다(CLAUDE.md 1번 — 틀려도 조회는 성공한다). 지번이 둘 이상인 단지는 아직 다루지 않는다
- 저장하는 칸은 건물 사실뿐이다. 대장 칸이 비어 있으면(0·공백) 그대로 두고 '0'을 사실로 읽지 않는다
  (은마 28개 동은 승강기 칸이 모두 0인데 K-apt 기본정보는 42대다)

실행:
  python3 scripts/bld_register.py --complex eunma
  → data/building-register/<slug>-<조회일>.json
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
UA = "danji-content-agent/1.0"
URL = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
KEEP = ["dongNm", "bldNm", "mainPurpsCdNm", "mainAtchGbCdNm", "regstrGbCdNm", "grndFlrCnt", "ugrndFlrCnt",
        "hhldCnt", "hoCnt", "fmlyCnt", "rideUseElvtCnt", "emgenUseElvtCnt", "useAprDay", "pmsDay", "stcnsDay",
        "strctCdNm", "roofCdNm", "archArea", "totArea", "heit", "rserthqkDsgnApplyYn", "rserthqkAblty", "crtnDay"]


def key():
    k = os.environ.get("KAPT_SERVICE_KEY")
    if not k:
        sys.exit("KAPT_SERVICE_KEY 없음 — .env 를 읽고 실행한다")
    return k


def target(slug):
    ld = json.loads((REPO / "data" / "ldcode.json").read_text(encoding="utf-8"))
    ld = ld.get("complexes", ld)[slug]["ld_code"]
    addr = json.loads((REPO / "data" / "complex-info" / f"{slug}.json").read_text(encoding="utf-8"))["address"]
    m = re.search(r"[동가로]\s(\d+)(?:-(\d+))?(?:\s|$)", addr)
    if not m:
        sys.exit(f"지번을 못 읽었다: {addr}")
    return ld[:5], ld[5:], m.group(1).zfill(4), (m.group(2) or "0").zfill(4), addr


def fetch(k, sg, bj, bun, ji):
    items, page = [], 1
    while True:
        q = {"serviceKey": k, "sigunguCd": sg, "bjdongCd": bj, "bun": bun, "ji": ji,
             "numOfRows": "50", "pageNo": str(page), "_type": "json"}
        url = URL + "?" + urllib.parse.urlencode(q, safe="%")
        for t in range(5):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                    d = json.load(r)
                break
            except Exception as e:          # 503·연결 끊김이 잦다(11/17 첫 호출 503)
                print(f"  재시도 {page}쪽 {type(e).__name__}", flush=True)
                time.sleep(4 * (t + 1))
        else:
            sys.exit("건축물대장 응답 없음")
        body = d["response"]["body"]
        it = (body.get("items") or {}).get("item") or []
        if isinstance(it, dict):
            it = [it]
        items += it
        if len(items) >= int(body["totalCount"]) or not it:
            return items, int(body["totalCount"])
        page += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--complex", required=True)
    a = ap.parse_args()
    sg, bj, bun, ji, addr = target(a.complex)
    items, total = fetch(key(), sg, bj, bun, ji)
    assert len(items) == total, (len(items), total)
    now = datetime.now(KST)
    out = {
        "slug": a.complex, "address": addr, "query": {"sigunguCd": sg, "bjdongCd": bj, "bun": bun, "ji": ji},
        "fetched_at": now.isoformat(timespec="seconds"),
        "source": "국토교통부 건축HUB 건축물대장정보 서비스 getBrTitleInfo(표제부), 공공데이터포털 15134735",
        "license": "이용허락범위 제한 없음(공공데이터포털 15134735 화면, 2026-11-17 확인)",
        "note": "대장 칸 값 그대로. 0·공백은 '없음'이 아니라 '대장에 안 적힘'일 수 있다",
        "buildings": [{k: x.get(k) for k in KEEP} for x in items],
    }
    p = REPO / "data" / "building-register" / f"{a.complex}-{now:%Y-%m-%d}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{p.relative_to(REPO)} · 건물 {len(items)}")


if __name__ == "__main__":
    main()
