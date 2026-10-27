#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""예측 장부 — 발표마다 다음 주 5개 구를 예측하고, 다음 발표로 판정한다.

  data/reb-weekly/releases/<발표일>.json 을 순서대로 읽는다.
  발표 t 의 예측은 발표 t 의 표만 본다(as-of). 판정은 발표 t+1 의 마지막 주 값이다.
  발표 사이에 같은 주 값이 고쳐진 적이 있으면 멈춘다 — 판정 기준이 흔들린다.

결과는 data/forecast/ledger.json 에 남긴다. 소급 기록 글과 매주 기록 글이 이 장부를 읽는다.

실행: python3 scripts/forecast_ledger.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forecast_engine as E  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
REL_DIR = REPO / "data" / "reb-weekly" / "releases"
OUT = REPO / "data" / "forecast" / "ledger.json"
START = "2026-08-06"   # 첫 글(8/1) 뒤 첫 발표


def releases():
    rels = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(REL_DIR.glob("*.json"))]
    rels = [r for r in rels if r["published"] >= START]
    # 발표가 매주 빠짐없이 이어지는지: 앞 발표의 마지막 주가 뒤 발표의 끝에서 두 번째 주여야 한다
    for a, b in zip(rels, rels[1:]):
        if a["weeks"][-1] != b["weeks"][-2]:
            raise SystemExit(f"발표가 끊겼다: {a['published']}({a['weeks'][-1]}) → {b['published']}({b['weeks'][-2]})")
    return rels


def no_revision(rels):
    seen = {}
    for r in rels:
        for g in E.DISTRICTS:
            for w, v in r["gu"][g]["sale"]["weekly"].items():
                k = (g, w)
                if k in seen and seen[k][1] != v:
                    raise SystemExit(f"값이 고쳐졌다 {k}: {seen[k]} → {r['published']} {v}")
                seen.setdefault(k, (r["published"], v))


def build():
    rels = releases()
    no_revision(rels)
    weeks = []
    for i, r in enumerate(rels):
        nxt = rels[i + 1] if i + 1 < len(rels) else None
        rows = []
        for g in E.DISTRICTS:
            f = E.forecast(r, g)
            if nxt:
                actual = nxt["gu"][g]["sale"]["weekly"][nxt["weeks"][-1]]
                res = E.outcome(actual)
                f["result"] = {"week": nxt["weeks"][-1], "value": actual, "side": res,
                               "settled_by": nxt["published"],
                               "consensus_hit": None if res is None or f["consensus"] is None else f["consensus"] == res}
                for v in f["votes"]:
                    v["hit"] = None if res is None or v["side"] is None else v["side"] == res
            else:
                f["result"] = None
            rows.append(f)
        weeks.append({"published": r["published"], "embargo_kst": r["embargo_kst"],
                      "reference_date": r["reference_date"], "target_week": None if not nxt else nxt["weeks"][-1],
                      "source_url": r["source_url"], "seoul_sale": r["seoul"]["sale"]["weekly"][r["weeks"][-1]],
                      "forecasts": rows})
    return {"engine": E.ENGINE, "start": START, "computed_from": [w["published"] for w in weeks], "weeks": weeks}


def summary(ledger):
    tot = hit = 0
    per = {}
    for w in ledger["weeks"]:
        line = []
        for f in w["forecasts"]:
            c = {"up": "↑", "down": "↓", None: "·"}[f["consensus"]]
            r = f["result"]
            mark = "?" if r is None else ("=" if r["consensus_hit"] is None else ("O" if r["consensus_hit"] else "X"))
            line.append(f"{f['gu']} p{f['p']:.1f}{c}{f['tally']['up']}:{f['tally']['down']}{mark}"
                        + (f"({r['value']:+.2f})" if r else ""))
            if r and r["consensus_hit"] is not None:
                tot += 1
                hit += r["consensus_hit"]
            for v in f["votes"]:
                if v.get("hit") is not None:
                    s = per.setdefault(v["name"], [0, 0])
                    s[0] += v["hit"]
                    s[1] += 1
        print(w["published"], " | ".join(line))
    print(f"\n컨센서스 적중 {hit}/{tot}")
    for n, (h, t) in per.items():
        print(f"  {n}: {h}/{t}")


def main():
    ledger = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary(ledger)
    print(f"→ {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
