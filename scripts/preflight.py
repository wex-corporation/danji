#!/usr/bin/env python3
"""루틴 시작 전 점검 — 오늘 무엇이 되고 무엇이 안 되는지 먼저 정한다.

11/16 danji.life 인증서 만료, 11/23 data.go.kr 접속 장애 — 두 번 다 루틴이 자료를 받거나 글을 보내다가
중간에 막힌 걸 알았다. 이제 아침·밤 예약 작업과 슬롯 작업이 맨 먼저 이걸 돌리고 종료 코드로 갈 길을 정한다.

  0  전부 된다
  2  danji.life 가 안 된다(게시·피드 조회 불가) — 글을 쓰지 않고 재시도를 건다
  3  data.go.kr 이 안 된다(게시는 된다) — 그날 글은 밤에 받아 둔 스냅숏(`--from-cache`)으로 쓴다
  4  키가 없다(.env) — 대표님께 알리고 멈춘다

키 값은 출력하지 않는다. 있다/없다만.

실행:  python3 scripts/preflight.py [--json] [--group odd|even|auto]
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import apicache  # noqa: E402

KST = timezone(timedelta(hours=9))
UA = "danji-content-agent/1.0"
KEYS = ("CIVIC_PULSE_API_KEY", "KAPT_SERVICE_KEY")
TRADE_API = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
PROBES = 5                 # data.go.kr 은 다섯 번 따로 찔러 다섯 번 다 붙어야 된다고 본다(11/23)

# 배정표(docs/daily-routine-2026-11.md 2장) — 단지 → 구 코드
GROUPS = {
    "even": {"ricents": "11710", "mapo-raemian-prugio": "11440", "one-bailey": "11650"},
    "odd": {"eunma": "11680", "helio-city": "11710", "godeok-gracium": "11740"},
}


def load_env():
    """셸에서 .env 를 안 읽고 불렀을 때를 위해 — 이미 있는 값은 덮지 않는다."""
    p = REPO / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def alias_keys():
    """공공데이터 키를 다른 이름으로 넣어도 KAPT_SERVICE_KEY 로 본다(11/24 — 라엘이 DATA_GO_KR_KEY 로 안내).
    값은 옮기기만 하고 찍지 않는다."""
    if not os.environ.get("KAPT_SERVICE_KEY"):
        for alt in ("DATA_GO_KR_SERVICE_KEY", "DATA_GO_KR_KEY"):
            if os.environ.get(alt):
                os.environ["KAPT_SERVICE_KEY"] = os.environ[alt]
                break


def probe(url, tries=2, timeout=20, check=None):
    """(ok, 설명). 키가 들어간 URL 이어도 설명에는 호스트만 남긴다."""
    host = urllib.parse.urlsplit(url).netloc
    last = ""
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(200_000).decode("utf-8", errors="replace")
                if check and not check(body):
                    return False, f"{host} 응답은 왔지만 내용이 예상과 다르다"
                return True, f"{host} {r.status}"
        except urllib.error.HTTPError as e:
            last = f"{host} HTTP {e.code}"
            if e.code < 500:
                return False, last
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            last = f"{host} 접속 실패({type(reason).__name__}: {str(reason)[:80]})"
        if t + 1 < tries:
            time.sleep(5)
    return False, last


def group_for(day):
    return "even" if day.day % 2 == 0 else "odd"


def snapshot_age(group, today):
    """그 배정 단지 구들의 매매·전월세 스냅숏 중 직전 달 것 — 가장 오래된 조회 시각."""
    prev = (today.replace(day=1) - timedelta(days=1)).strftime("%Y%m")
    times = []
    for lawd in sorted(set(GROUPS[group].values())):
        for kind in ("trade", "rent"):
            m = apicache.meta(kind, lawd, prev)
            times.append(m)
    if not times or None in times:
        return None
    return min(times)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--group", choices=["odd", "even", "auto"], default="auto",
                    help="스냅숏을 볼 배정 묶음. auto = 오늘 날짜의 홀짝")
    a = ap.parse_args()
    load_env()
    alias_keys()
    now = datetime.now(KST)
    group = group_for(now) if a.group == "auto" else a.group

    res = {"checked_at": now.isoformat(timespec="seconds"), "group": group}
    res["keys"] = {k: bool(os.environ.get(k)) for k in KEYS}

    ok, why = probe(os.environ.get("BASE_URL", "https://danji.life") + "/api/v1/stats",
                    check=lambda b: '"posts"' in b)
    res["danji"] = {"ok": ok, "detail": why}

    if res["keys"]["KAPT_SERVICE_KEY"]:
        prev = (now.replace(day=1) - timedelta(days=1)).strftime("%Y%m")
        q = {"serviceKey": os.environ["KAPT_SERVICE_KEY"], "LAWD_CD": "11710", "DEAL_YMD": prev,
             "numOfRows": 1, "pageNo": 1}
        # 11/23 16:23 — 한 번 붙은 것만 보고 '된다'로 판정했는데, 바로 뒤 30분 동안 24달 중 2달만 받혔다(끊겼다 붙었다).
        # 그래서 따로 다섯 번 찔러 보고 다섯 번 다 붙어야 '된다'로 본다. 한 번이라도 끊기면 '들쭉날쭉'으로 3을 낸다
        url = f"{TRADE_API}?{urllib.parse.urlencode(q)}"
        hits, last = 0, ""
        for i in range(PROBES):
            one, why1 = probe(url, tries=1, timeout=15,
                              check=lambda b: "<resultCode>00" in b or "<resultCode>000" in b)
            hits += one
            last = why1 if not one else last
            if i + 1 < PROBES:
                time.sleep(2)
        ok = hits == PROBES
        why = f"apis.data.go.kr {PROBES}번 중 {hits}번 붙음" + (f" — {last}" if last else "")
        res["data_go_kr_flaky"] = 0 < hits < PROBES
    else:
        ok, why = False, "키 없음"
    res["data_go_kr"] = {"ok": ok, "detail": why}

    for name, url in (("reb", "https://www.reb.or.kr/"), ("neis", "https://open.neis.go.kr/hub/acaInsTiInfo?Type=json&pIndex=1&pSize=1")):
        ok, why = probe(url)
        res[name] = {"ok": ok, "detail": why}

    snap = snapshot_age(group, now)
    st = apicache.DIR / "status.json"
    verified = json.loads(st.read_text(encoding="utf-8")).get("verified") if st.exists() else None
    res["snapshot"] = {"oldest_prev_month": snap, "verified": verified,
                       "usable": bool(snap) and verified is not False
                       and (now - datetime.fromisoformat(snap)) <= timedelta(days=3)}

    if not all(res["keys"].values()):
        code = 4
    elif not res["danji"]["ok"]:
        code = 2
    elif not res["data_go_kr"]["ok"]:
        code = 3
    else:
        code = 0
    res["exit"] = code
    res["plan"] = {
        0: "평소대로 — 자료는 라이브로 받는다",
        2: "danji.life 안 됨 — 글을 쓰지 않는다. 1시간 뒤 재시도(17시까지), 처음 막힌 때 대표님께 한 번 알린다",
        3: (("data.go.kr 들쭉날쭉(붙었다 끊겼다) — 라이브로 몇십 달을 받기 어렵다. " if res.get("data_go_kr_flaky") else "data.go.kr 안 됨 — ")
            + "스냅숏(--from-cache)으로 쓴다. 확인일은 스냅숏 조회일"
            if res["snapshot"]["usable"] else
            ("data.go.kr 들쭉날쭉" if res.get("data_go_kr_flaky") else "data.go.kr 안 됨")
            + ", 쓸 만한 스냅숏도 없음 — 커밋된 캐시(관리비·장충금·대장·상가·학원)로 쓸 소재가 있는지 보고, 없으면 재시도"),
        4: "키 없음 — 대표님께 알리고 멈춘다",
    }[code]

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(f"점검 {res['checked_at']} · 배정 {group}")
        print("  키   " + " · ".join(f"{k} {'있음' if v else '없음'}" for k, v in res["keys"].items()))
        for n in ("danji", "data_go_kr", "reb", "neis"):
            print(f"  {n:<10} {'된다' if res[n]['ok'] else '안 된다'} — {res[n]['detail']}")
        print(f"  스냅숏  {snap or '없음'}{' (쓸 수 있음)' if res['snapshot']['usable'] else ''}"
              f"{' — 밤 검증에서 어긋나 쓰지 않는다' if verified is False else ''}")
        print(f"→ {res['plan']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
