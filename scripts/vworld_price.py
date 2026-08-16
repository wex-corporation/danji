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

사용법:
  export VWORLD_API_KEY=...
  python3 vworld_price.py --check                    # 도달성·키 점검
  python3 vworld_price.py --ldcode 1165010700        # 법정동 단위 조회
"""

import argparse
import json
import os
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

# 우리가 다루는 단지의 법정동. 공시가격은 단지코드가 아니라 법정동 단위로 조회된다.
LDCODE = {
    "1165010700": "서초구 반포동",
    "1168010600": "강남구 대치동",
    "1171010200": "송파구 잠실동",
    "1171010300": "송파구 신천동",
    "1174010100": "강동구 상일동",
    "1174010200": "강동구 둔촌동",
    "1144012000": "마포구 아현동",
}


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
    except urllib.error.HTTPError:
        return True, ip  # 4xx/5xx 라도 응답이 온 것이므로 도달은 된다
    except (urllib.error.URLError, OSError) as exc:
        return False, f"{ip} TCP 는 열리나 HTTP 응답이 없음 ({exc})"


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
            raise VWorldError(f"{HOST} 에 접속할 수 없습니다 ({detail}). "
                              "이 실행 환경의 이그레스 제한일 수 있습니다") from exc
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
    ap.add_argument("--ldcode", help="법정동코드 10자리")
    ap.add_argument("--year", help="기준연도 (예: 2026)")
    args = ap.parse_args()

    ok, detail = reachable()
    print(f"[도달성] {HOST} → {'연결됨 ' + detail if ok else '연결 불가 — ' + detail}")
    if not ok:
        print("\n이 환경에서는 브이월드에 접속할 수 없습니다. 키 문제가 아닙니다.", file=sys.stderr)
        print("k-apt.go.kr 과 같은 유형의 이그레스 제한으로 보입니다.", file=sys.stderr)
        print("접속 가능한 환경에서 같은 명령을 실행하면 그대로 동작합니다.", file=sys.stderr)
        return 3

    try:
        key = api_key()
    except VWorldError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 2

    if args.check:
        try:
            items = fetch(key, next(iter(LDCODE)), args.year, rows=1)
            print(f"[키] 정상 · 표본 {len(items)}건 수신")
            return 0
        except VWorldError as exc:
            print(f"[키] 실패: {exc}", file=sys.stderr)
            return 1

    targets = [args.ldcode] if args.ldcode else list(LDCODE)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok_n = fail = 0
    for code in targets:
        try:
            items = fetch(key, code, args.year)
        except VWorldError as exc:
            print(f"[실패] {code} {LDCODE.get(code,'')}: {exc}", file=sys.stderr)
            fail += 1
            continue
        rec = {"ld_code": code, "ld_name": LDCODE.get(code, ""), "stdr_year": args.year,
               "count": len(items), "items": items,
               "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "source": {"label": "브이월드 공동주택 공시가격 속성조회",
                          "url": "https://www.vworld.kr/", "publisher": "국토교통부"},
               "usage_note": "공시가격은 가격 자료다. 홍보 페르소나 인용 금지, 세금·정책 분석만 사용."}
        (OUT_DIR / f"{code}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[완료] {code} {LDCODE.get(code,'')}: {len(items)}건")
        ok_n += 1
        time.sleep(0.5)

    print(f"\n성공 {ok_n} / 실패 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
