#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""브이월드(V-World) 공동주택 공시가격 조회.

국토교통부 디지털트윈국토 NED API에서 법정동 단위 공동주택 공시가격을 받는다.
공시가격은 보유세·종부세·건강보험료 산정의 기준값이라 세금 글의 근거가 된다.

**중요 — 이 데이터는 홍보 페르소나가 쓰지 못한다.**
공시가격은 가격이다. 명세 7.2.1은 홍보 페르소나(ADV)에게 가격 전망·매수 권유를
금지하고, CLAUDE.md도 같은 선을 긋는다. 이 값은 세금·정책 맥락의 분석 페르소나
(세금한줄정리·절세시나리오·공시가격체크)만 인용한다. 홍보글에 넣으면 시세
부양으로 읽힌다.

인증키는 공공데이터포털과 별개다. `VWORLD_API_KEY` 환경변수로 넣는다.
브이월드 개발키는 **발급 시 등록한 도메인에서만** 동작한다. 도메인이 다르면
INCORRECT_KEY가 돌아온다(에러코드표 참조).

**어디서 실행해야 하나 — 한국 IP가 필요하다.**
api.vworld.kr 은 해외·데이터센터 IP를 막는다. 이 저장소의 실행 환경에서도,
앤트로픽 서버를 경유해도 똑같이 502가 돌아온다. 프록시 정책이나 키 문제가 아니다.
같은 유형: k-apt.go.kr, nsdi.go.kr, r-one.co.kr. 반대로 apis.data.go.kr,
realtyprice.kr, reb.or.kr, kosis.kr 은 해외에서도 열린다.
→ 국내 회선(운영자 PC)이나 국내 리전 서버에서 실행한다. 절차는 docs/vworld-run.md.

법정동코드는 손으로 적지 않는다. `scripts/ldcode.py` 가 매매 실거래 응답의
sggCd + umdCd 로 확정해 `data/ldcode.json` 에 남긴 값을 읽는다. 손으로 적었을 때
파일럿 6곳 중 4곳이 틀렸고, **틀려도 조회는 성공해서** 엉뚱한 동의 값이 저장됐다.

사용법:
  python3 scripts/ldcode.py                          # 먼저 법정동코드 확정
  export VWORLD_API_KEY=...
  python3 vworld_price.py --check                    # 도달성·키 점검
  python3 vworld_price.py --year 2026                # 파일럿 전체
  python3 vworld_price.py --only eunma               # 한 단지만
"""

import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "housing-price"
HOST = "api.vworld.kr"
ATTR_URL = f"https://{HOST}/ned/data/getApartHousingPriceAttr"
UA = "danji-content-agent/1.0"

# 브이월드 에러코드. 재시도해도 결과가 같은 것들이라 즉시 중단한다.
VW_ERRORS = {
    "INVALID_KEY": "등록되지 않은 인증키입니다",
    "INCORRECT_KEY": "인증키 정보가 올바르지 않습니다. 발급 시 등록한 도메인과 다를 수 있습니다",
    "UNAVAILABLE_KEY": "임시로 인증키를 사용할 수 없는 상태입니다",
    "OVER_REQUEST_LIMIT": "일일 사용량을 초과했습니다",
    "INVALID_TYPE": "파라미터 타입이 유효하지 않습니다",
    "INVALID_RANGE": "파라미터 값이 유효 범위를 넘었습니다",
    "SYSTEM_ERROR": "브이월드 시스템 오류",
    "UNKNOWN_ERROR": "알 수 없는 오류",
}

LDCODE_PATH = REPO / "data" / "ldcode.json"


def load_targets(only=None):
    """slug → {ld_code, complex_name, dong}. ldcode.py 가 만든 표를 읽는다."""
    if not LDCODE_PATH.exists():
        raise VWorldError(
            f"{LDCODE_PATH.relative_to(REPO)} 가 없습니다. 먼저 `python3 scripts/ldcode.py` 를 실행하세요")
    data = json.loads(LDCODE_PATH.read_text(encoding="utf-8"))["complexes"]
    rows = {}
    for slug, r in data.items():
        if only and slug not in only:
            continue
        if not r.get("ld_code"):
            print(f"[건너뜀] {slug}: 법정동코드 미확정 — {r.get('reason')}", file=sys.stderr)
            continue
        rows[slug] = r
    if not rows:
        raise VWorldError("조회할 단지가 없습니다")
    return rows


class VWorldError(RuntimeError):
    pass


def api_key():
    key = os.environ.get("VWORLD_API_KEY")
    if not key:
        raise VWorldError("VWORLD_API_KEY가 없습니다. vworld.kr 마이포털 > 인증키관리에서 발급합니다.")
    return key


def reachable():
    """도달 가능 여부를 본다.

    TCP 연결만 보면 안 된다. 이 호스트는 443 포트는 열어 두고 실제 요청은
    응답 없이 끊는다(k-apt.go.kr 과 같은 양상). 그래서 HTTP 왕복까지 확인한다.
    """
    try:
        ip = socket.gethostbyname(HOST)
    except OSError as exc:
        return False, f"DNS 실패: {exc}"
    try:
        with socket.create_connection((ip, 443), timeout=8):
            pass
    except OSError as exc:
        return False, f"{ip}:443 연결 실패: {exc}"
    try:
        req = urllib.request.Request(f"https://{HOST}/", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10):
            return True, ip
    except urllib.error.HTTPError as exc:
        if exc.code >= 500:
            # 지오블록 엣지가 502 를 돌려준다. 응답이 왔다고 쓸 수 있는 게 아니다.
            return False, f"{ip} 이 HTTP {exc.code} 만 돌려줍니다"
        return True, ip                      # 4xx 는 서비스가 살아 있다는 뜻이다
    except (urllib.error.URLError, OSError) as exc:
        return False, f"{ip} TCP 는 열리나 HTTP 응답이 없음 ({exc})"


def geo_hint(detail):
    """접속 실패 안내. 원인은 이그레스 정책이 아니라 상대 쪽 해외 IP 차단이다."""
    return "\n".join([
        f"브이월드에 접속할 수 없습니다 ({detail}). 키 문제도, 프록시 정책 문제도 아닙니다.",
        "api.vworld.kr 은 해외·데이터센터 IP를 막습니다 — k-apt.go.kr, nsdi.go.kr,",
        "r-one.co.kr 이 같은 유형입니다. apis.data.go.kr 은 해외에서도 열립니다.",
        "→ 국내 회선(운영자 PC)이나 국내 리전 서버에서 실행하세요. 절차: docs/vworld-run.md",
    ])


def match_items(items, target):
    """법정동 응답에서 우리 단지 것만 골라낸다.

    공시가격은 **법정동 단위**로 온다. 한 동에 여러 단지가 섞여 있으므로
    골라내지 못하면 단지별 지표로 쓸 수 없다. 응답 스키마를 단정할 수 없어
    값 전체를 훑어 단지명이나 지번이 들어 있는 레코드를 찾는다.
    """
    name = (target.get("complex_name") or "").replace(" ", "")
    m = re.search(r"[가-힣]+동\s+(\d+)", target.get("address") or "")
    bonbun = m.group(1).lstrip("0") if m else None

    hits, how = [], []
    for it in items:
        vals = [str(v).strip() for v in it.values() if v is not None]
        # 값을 하나로 이어 붙이면 지번이 옆 필드와 붙어 오탐이 난다. 필드별로 본다.
        by_name = name and any(name in v.replace(" ", "") for v in vals)
        # 지번은 0 으로 자리를 채워 오는 경우가 많다("0479"). 앞의 0 을 떼고 비교한다.
        by_jibun = bonbun and any(v.isdigit() and v.lstrip("0") == bonbun for v in vals)
        if by_name or by_jibun:
            hits.append(it)
            how.append("단지명 일치" if by_name else "지번 본번 일치")
    if not hits:
        return [], f"단지명({name})·지번({bonbun})으로 골라내지 못했다. 응답 필드를 눈으로 확인할 것"
    return hits, f"{sorted(set(how))} 로 {len(hits)}건 식별"


def _classify(text):
    for code, msg in VW_ERRORS.items():
        if code in text:
            return f"{msg} [{code}]"
    return None


def fetch(key, ldcode, year=None, rows=100, page=1):
    q = {"key": key, "format": "json", "numOfRows": rows, "pageNo": page, "ldCode": ldcode}
    if year:
        q["stdrYear"] = str(year)
    url = f"{ATTR_URL}?{urllib.parse.urlencode(q)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        known = _classify(body)
        raise VWorldError(known or f"HTTP {exc.code} — {body[:200]}") from exc
    except (urllib.error.URLError, OSError) as exc:
        ok, detail = reachable()
        if not ok:
            raise VWorldError(geo_hint(detail)) from exc
        raise VWorldError(f"네트워크 실패: {exc}") from exc

    known = _classify(raw)
    if known:
        raise VWorldError(known)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VWorldError(f"응답 파싱 실패: {raw[:200]}") from exc

    field = data.get("apartHousingPrices") or data.get("response") or {}
    items = (field.get("field") or field.get("items") or [])
    if isinstance(items, dict):
        items = [items]
    return items


def main():
    ap = argparse.ArgumentParser(description="브이월드 공동주택 공시가격 조회")
    ap.add_argument("--check", action="store_true", help="도달성과 키만 점검한다")
    ap.add_argument("--only", nargs="*", help="슬러그를 지정하면 그 단지만")
    ap.add_argument("--year", help="기준연도 (예: 2026)")
    args = ap.parse_args()

    ok, detail = reachable()
    print(f"[도달성] {HOST} → {'연결됨 ' + detail if ok else '연결 불가 — ' + detail}")
    if not ok:
        print("\n" + geo_hint(detail), file=sys.stderr)
        return 3

    try:
        key = api_key()
    except VWorldError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    try:
        targets = load_targets(args.only)
    except VWorldError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    if args.check:
        slug, first = next(iter(targets.items()))
        try:
            items = fetch(key, first["ld_code"], args.year, rows=1)
            print(f"[키] 정상 · {first['complex_name']}({first['dong']}) 표본 {len(items)}건 수신")
            return 0
        except VWorldError as exc:
            print(f"[키] 실패: {exc}", file=sys.stderr)
            if "INCORRECT_KEY" in str(exc):
                print("      vworld.kr 마이포털 > 인증키관리에서 등록 도메인에 localhost 를 추가하세요.",
                      file=sys.stderr)
            return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok_n = fail = 0
    for slug, t in targets.items():
        code = t["ld_code"]
        try:
            items = fetch(key, code, args.year)
        except VWorldError as exc:
            print(f"[실패] {slug} {t['dong']}({code}): {exc}", file=sys.stderr)
            fail += 1
            continue
        matched, how = match_items(items, t)
        rec = {"slug": slug, "complex_name": t["complex_name"],
               "ld_code": code, "ld_name": f"{t['gu']} {t['dong']}",
               "stdr_year": args.year,
               "count": len(items),
               "matched_count": len(matched),
               "matched": bool(matched),
               "match_note": how,
               "matched_items": matched,
               "items": items,
               "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "source": {"label": "브이월드 공동주택 공시가격 속성조회",
                          "url": "https://www.vworld.kr/", "publisher": "국토교통부"},
               "usage_note": "공시가격은 가격 자료다. 홍보 페르소나 인용 금지, 세금·정책 분석만 사용."}
        (OUT_DIR / f"{slug}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        flag = f"우리 단지 {len(matched)}건 식별" if matched else "**우리 단지를 못 골라냄**"
        print(f"[완료] {slug} {t['dong']}: 동 전체 {len(items)}건 · {flag}")
        ok_n += 1
        time.sleep(0.5)

    print(f"\n성공 {ok_n} / 실패 {fail}")
    unmatched = [s_ for s_ in targets
                 if (OUT_DIR / f"{s_}.json").exists()
                 and not json.loads((OUT_DIR / f"{s_}.json").read_text(encoding="utf-8"))["matched"]]
    if unmatched:
        print(f"[주의] 응답에서 우리 단지를 골라내지 못한 곳: {', '.join(unmatched)}", file=sys.stderr)
        print("      공시가격은 법정동 단위라 한 동에 여러 단지가 섞입니다.", file=sys.stderr)
        print("      골라내지 못하면 단지별 지표로 쓸 수 없습니다 — 글에 인용하지 마세요.", file=sys.stderr)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
