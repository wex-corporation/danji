"""공공데이터 실거래 응답 스냅숏 — data.go.kr 이 끊긴 날의 예비 자료.

11/23 apis.data.go.kr·www.data.go.kr 이 09:40~12:39 세 번 내리 TLS 접속 단계에서 끊겼다(다른 호스트는 정상).
그날 루틴이 받아야 할 자료가 전부 그 호스트에 있어 글이 0편이 됐다. 그래서:

- 실거래 매매·전월세를 **구·계약월** 단위로, 라이브 조회가 성공할 때마다 여기에 같이 남긴다(write-through)
- 밤 예약 작업(`prefetch.py`)이 다음 날 배정 단지의 구를 미리 받아 둔다
- 스크립트에 `--from-cache` 를 줄 때만 여기서 읽는다. 조용히 대신 읽지 않는다 —
  결과 파일의 `fetched_at` 은 읽은 스냅숏 가운데 **가장 오래된 조회 시각**이고 `from_cache: true` 가 붙는다.
  글의 확인일은 그 날짜로 적는다

금액 칸(거래금액·보증금·월세·종전 보증금)은 저장하지 않는다 — 월세가 붙었는지, 종전 보증금 칸이 채워졌는지만 참·거짓으로 남긴다.
`data/.apicache/` 는 git 에 올리지 않는다(구 전체 응답이라 크고, 컨테이너가 새로 만들어지면 사라진다 — 밤 작업이 다시 채운다).
"""

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIR = REPO / "data" / ".apicache"
KST = timezone(timedelta(hours=9))

# 매매 응답에서 남기는 칸. 금액(dealAmount)·지번 등은 뺀다
TRADE_KEEP = ("aptNm", "umdNm", "dealYear", "dealMonth", "dealDay", "excluUseAr", "floor", "buildYear",
              "rgstDate", "cdealType", "cdealDay", "dealingGbn", "buyerGbn", "slerGbn")
# 전월세(rent_volume 파싱 뒤)에서 남기는 칸. 금액은 참·거짓으로만
RENT_KEEP = ("apt", "dong", "area_m2", "floor", "contract_type", "contract_term", "use_rr_right", "deal_date")

USED = []          # 이번 실행에서 읽은 스냅숏의 조회 시각


class CacheMiss(RuntimeError):
    pass


def _path(kind, lawd, ym):
    return DIR / kind / f"{lawd}-{ym}.json.gz"


def now():
    return datetime.now(KST).isoformat(timespec="seconds")


def save_trade(lawd, ym, total, items):
    rows = [{k: d.get(k, "") for k in TRADE_KEEP} for d in items]
    _write("trade", lawd, ym, total, rows)


def save_rent(lawd, ym, rows):
    out = []
    for r in rows:
        x = {k: r.get(k) for k in RENT_KEEP}
        x["with_monthly"] = (r.get("monthly_manwon") or 0) > 0
        x["pre_deposit_filled"] = bool(r.get("pre_deposit"))
        out.append(x)
    _write("rent", lawd, ym, len(out), out)


def _write(kind, lawd, ym, total, rows):
    p = _path(kind, lawd, ym)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({"kind": kind, "lawd_cd": lawd, "ym": ym, "fetched_at": now(), "total": total, "rows": rows},
                  f, ensure_ascii=False)
    tmp.replace(p)


def meta(kind, lawd, ym):
    """스냅숏이 있으면 조회 시각(문자열), 없으면 None."""
    p = _path(kind, lawd, ym)
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)["fetched_at"]


def load(kind, lawd, ym):
    p = _path(kind, lawd, ym)
    if not p.exists():
        raise CacheMiss(f"스냅숏 없음: {kind} {lawd} {ym} — 밤 작업(prefetch.py)이 받지 못한 달이다")
    with gzip.open(p, "rt", encoding="utf-8") as f:
        d = json.load(f)
    USED.append(d["fetched_at"])
    return d["total"], d["rows"]


def fetched_at(from_cache):
    """결과 파일에 적을 조회 시각 — 스냅숏이면 읽은 것 가운데 가장 오래된 시각."""
    if from_cache:
        assert USED, "스냅숏을 하나도 읽지 않았다"
        return min(USED)
    return now()


def note_cache(from_cache):
    if from_cache:
        oldest = min(USED)
        print(f"※ 스냅숏 자료 — 가장 오래된 조회 {oldest}. 글의 확인일은 {oldest[:10]}로 적는다")


def has_monthly(r):
    """전월세 행에 월세가 붙었는지 — 라이브 행(금액)과 스냅숏 행(참·거짓) 둘 다 받는다."""
    return r["with_monthly"] if "with_monthly" in r else r["monthly_manwon"] > 0


def pre_deposit_filled(r):
    return r["pre_deposit_filled"] if "pre_deposit_filled" in r else bool(r["pre_deposit"])
