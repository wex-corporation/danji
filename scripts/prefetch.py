#!/usr/bin/env python3
"""밤에 다음 날 배정 단지의 실거래 자료를 미리 받아 둔다 — data.go.kr 이 아침에 끊겨도 글을 쓸 수 있게.

11/23 아침 data.go.kr 이 몇 시간 끊겨 그날 글이 0편이었다(CLAUDE.md 52번). 전날 밤에는 됐다.
이 스크립트가 받은 것은 `data/.apicache/`(apicache.py)에 구·계약월 단위로 남고,
아침 루틴은 `preflight.py` 가 3(data.go.kr 안 됨)을 내면 `trade_registry.py`·`rent_series.py` 에
`--from-cache` 를 줘서 이걸 읽는다. 금액 칸은 저장하지 않는다.

받는 것(배정 묶음의 구마다):
  매매 실거래  2022-01 ~ 직전 달   (등기일·해제·거래 구분 — registry·구 요약이 쓰는 창)
  전월세 신고  직전 달 포함 26달  (rent_series 열두 달 두 번 창)
최근 13달은 매번 다시 받고(신고·등기·해제가 늦게 채워진다), 그보다 오래된 달은 스냅숏이 7일 넘었을 때만 받는다.
최근 달부터 받는다. 연속 4번 끊기면 호스트가 내려간 것으로 보고 멈춘다.
오늘 이미 받은 달은 건너뛴다 — 중간에 끊겨도 다시 돌리면 이어서 받는다.

실행:  python3 scripts/prefetch.py [--group odd|even|tomorrow]
종료 코드: 0 전부 받음 · 1 일부 못 받음(끊김) — 못 받은 달은 출력과 status.json 에 남는다
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import apicache  # noqa: E402
import preflight  # noqa: E402
import rent_series  # noqa: E402
import trade_registry  # noqa: E402
import trade_volume as tv  # noqa: E402
from trade_registry import month_range  # noqa: E402

TRADE_FROM = "202201"
RENT_MONTHS = 26
FRESH_MONTHS = 13
STALE_DAYS = 7
GIVE_UP_AFTER = 4          # 연속으로 이만큼 끊기면 호스트가 내려간 것으로 보고 멈춘다


def ym_add(ym, n):
    y, m = int(ym[:4]), int(ym[4:]) + n
    while m <= 0:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y}{m:02d}"


def need(kind, lawd, ym, prev, now):
    got = apicache.meta(kind, lawd, ym)
    if got is None:
        return True
    t = datetime.fromisoformat(got)
    if t.date() == now.date():
        return False                                  # 오늘 이미 받았다
    if ym >= ym_add(prev, -(FRESH_MONTHS - 1)):
        return True                                   # 최근 13달은 매일
    return now - t > timedelta(days=STALE_DAYS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=["odd", "even", "tomorrow"], default="tomorrow")
    a = ap.parse_args()
    preflight.load_env()
    now = datetime.now(preflight.KST)
    group = preflight.group_for(now + timedelta(days=1)) if a.group == "tomorrow" else a.group
    lawds = sorted(set(preflight.GROUPS[group].values()))
    prev = (now.replace(day=1) - timedelta(days=1)).strftime("%Y%m")
    key = tv.service_key()

    jobs = []
    for lawd in lawds:
        jobs += [("trade", lawd, ym) for ym in month_range(TRADE_FROM, prev)]
        jobs += [("rent", lawd, ym) for ym in month_range(ym_add(prev, -(RENT_MONTHS - 1)), prev)]
    todo = [j for j in jobs if need(*j, prev, now)]
    todo.sort(key=lambda j: j[2], reverse=True)       # 최근 달부터 — 중간에 끊겨도 글에 쓸 달이 먼저 남는다
    print(f"{now:%Y-%m-%d %H:%M} 배정 {group}({', '.join(preflight.GROUPS[group])}) · 구 {lawds} · 받을 것 {len(todo)}/{len(jobs)}")

    failed, streak, done = [], 0, 0
    for kind, lawd, ym in todo:
        try:
            if kind == "trade":
                trade_registry.fetch_month(key, lawd, ym)
            else:
                rent_series.fetch_month(key, lawd, ym)
            done += 1
            streak = 0
        except Exception as e:                        # noqa: BLE001 — 끊김·응답 오류 모두 기록하고 넘어간다
            failed.append({"kind": kind, "lawd": lawd, "ym": ym, "error": f"{type(e).__name__}: {str(e)[:120]}"})
            streak += 1
            if streak >= GIVE_UP_AFTER:
                left = todo[todo.index((kind, lawd, ym)) + 1:]
                failed += [{"kind": k, "lawd": lw, "ym": y, "error": "건너뜀(호스트 끊김)"} for k, lw, y in left]
                print(f"연속 {streak}번 끊겨 멈춘다 — data.go.kr 이 내려가 있다")
                break
        time.sleep(0.25)

    status = {"run_at": now.isoformat(timespec="seconds"), "group": group, "lawds": lawds, "prev_month": prev,
              "fetched": done, "todo": len(todo), "failed": failed}
    apicache.DIR.mkdir(parents=True, exist_ok=True)
    (apicache.DIR / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"받음 {done} · 못 받음 {len(failed)}")
    for f in failed[:10]:
        print("  ", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
