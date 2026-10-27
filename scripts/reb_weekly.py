#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""한국부동산원 주간 아파트가격 동향 — 발표 원문을 받아 서울 구별 표로 저장한다.

왜 만들었나
  예측 기록(CLAUDE.md 44번)은 매주 목요일 발표를 입력으로 쓰고 다음 발표로 판정한다.
  10월분은 국내 회선 에이전트가 PDF를 받아 왔지만, 매주 사람 손을 거칠 수는 없다.

경로
  게시판 목록 → 상세 페이지의 첨부 PDF 키 → 문서 뷰어(StreamDocs)의 페이지별 텍스트 API.
  첨부 다운로드(RAONK)는 브라우저 전용이라 쓰지 않는다. 뷰어 텍스트는 PDF 원문과 같은 글자다.
  10/1~10/22 발표 4건을 이 경로로 다시 받아, 원문 PDF에서 옮긴 `seoul-gu-2026-10.json`과
  표 값이 전부 같은지 `--check` 로 확인한다.

저장
  data/reb-weekly/releases/<발표일>.json — 서울 전체 행(붙임1)과 서울 25개 구·5개 권역 행(붙임2),
  매매·전세 각각 '25년 누계, '26년 누계, 6주 주간 변동률. 해설 문단은 저장하지 않는다.

reb.or.kr 은 이 환경에서 연결이 자주 끊긴다. 요청마다 재시도한다.

실행:
  python3 scripts/reb_weekly.py                 # 게시판 앞 4쪽에서 새 발표를 찾아 저장
  python3 scripts/reb_weekly.py --sn 117921     # 특정 글
  python3 scripts/reb_weekly.py --check         # 저장된 발표끼리 겹치는 주 값과 10월 원문 대조
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "reb-weekly" / "releases"
OCT = REPO / "data" / "reb-weekly" / "seoul-gu-2026-10.json"
BASE = "https://www.reb.or.kr"
BOARD = f"{BASE}/reb/na/ntt/selectNttList.do?mi=9565&bbsId=1154"
INFO = f"{BASE}/reb/na/ntt/selectNttInfo.do?mi=9565&bbsId=1154&nttSn="
KST = timezone(timedelta(hours=9))

GU = ["종로", "중", "용산", "성동", "광진", "동대문", "중랑", "성북", "강북", "도봉", "노원", "은평", "서대문", "마포",
      "양천", "강서", "구로", "금천", "영등포", "동작", "관악", "서초", "강남", "송파", "강동"]
GROUPS = ["도심권", "동북권", "서북권", "서남권", "동남권"]
NUM = r"(-?\d+\.\d+|-)"


def curl(args, out=None):
    for i in range(6):
        cmd = ["curl", "-sS", "-m", "60", "-A", "Mozilla/5.0"] + args
        if out:
            cmd += ["-o", str(out)]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace") if out is None else True
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"reb.or.kr 요청 실패: {args[-1][:90]}")


def board(pages=4):
    found = {}
    q = urllib.parse.quote("주간아파트가격동향")
    for pg in range(1, pages + 1):
        h = curl([f"{BOARD}&searchCnd=1&searchKrwd={q}&currPage={pg}"])
        for sn, t in re.findall(r'data-id="(\d+)"[^>]*class="nttInfoBtn">\s*(.*?)\s*<', h, re.S):
            t = re.sub(r"\s+", "", t)
            m = re.match(r"주간아파트가격동향\((\d{8})기준\)$", t)
            if m:
                found[sn] = m.group(1)
    return found


# ── 페이지 텍스트 → 줄 ───────────────────────────────────────

def page_lines(items, tol=3):
    """같은 높이(top)의 조각을 왼쪽부터 잇는다. 표의 한 행이 한 줄이 된다."""
    pts = []
    for it in items:
        rs = it.get("rect") or []
        if not rs or not it.get("text", "").strip():
            continue
        pts.append((max(r["top"] for r in rs), min(r["left"] for r in rs), it["text"].strip()))
    pts.sort(key=lambda x: (-x[0], x[1]))
    lines, cur, cur_top = [], [], None
    for top, left, t in pts:
        if cur_top is None or abs(top - cur_top) <= tol:
            cur.append((left, t))
            cur_top = top if cur_top is None else cur_top
        else:
            lines.append(" ".join(x for _, x in sorted(cur)))
            cur, cur_top = [(left, t)], top
    if cur:
        lines.append(" ".join(x for _, x in sorted(cur)))
    return lines


def fetch(sn):
    html = curl([INFO + sn])
    m = re.search(r"AddUploadedFile\('\d+', '([^']+\.pdf)', '', '(\d+)', '([0-9a-f]{32})'", html)
    if not m:
        raise RuntimeError(f"{sn}: PDF 첨부를 못 찾았다")
    fname, _size, key = m.groups()
    did = json.loads(curl(["-X", "POST", "-d", f"fileKey={key}", f"{BASE}/reb/docView.do"]))["docViewId"]
    info = json.loads(curl([f"{BASE}/docview/v4/documents/{did}/info"]))
    pages = []
    for pg in range(int(info["PageCount"])):
        pages.append(page_lines(json.loads(curl([f"{BASE}/docview/v4/documents/{did}/texts/{pg}"]))))
        time.sleep(0.3)
    return fname, pages


# ── 표 파싱 ──────────────────────────────────────────────────

def row(line, name):
    # '서  울'처럼 글자 사이에 공백이 들어간 행 이름이 있다
    pat = r"\s*".join(map(re.escape, name.replace(" ", "")))
    m = re.search(r"(?:^|\s)" + pat + r"\s+" + r"\s+".join([NUM] * 8) + r"(?:\s|$)", line)
    if not m:
        return None
    v = [None if x == "-" else float(x) for x in m.groups()]
    return v


def parse(fname, pages):
    text = "\n".join("\n".join(p) for p in pages)
    emb = re.search(r"보\s*도\s*일\s*시\s*(\d{4})년\s*(\d+)월\s*(\d+)일\s*\(.\)\s*(\d\d:\d\d)", text)
    ref = re.search(r"\((\d+)\.(\d+)일\s*기준\)", text)
    if not emb or not ref:
        raise RuntimeError(f"{fname}: 보도 시각이나 기준일을 못 찾았다")
    pub = f"{emb.group(1)}-{int(emb.group(2)):02d}-{int(emb.group(3)):02d}"

    # 표 머리글 '‘25년 ‘26년 m.d ×6'. 어느 표인지는 앞서 나온 '붙임 N'과 '□ 매매/전세가격지수'로 정한다.
    # 표가 다음 쪽으로 이어지면 머리글이 다시 나오므로 (붙임, 종류)마다 첫 머리글만 쓴다
    heads, att, kind = {}, None, None
    for pi, lines in enumerate(pages):
        for li, ln in enumerate(lines):
            m = re.search(r"붙임\s*(\d)", ln)
            if m:
                att = int(m.group(1))
            m = re.search(r"□\s*(매매|전세)가격지수", ln)
            if m:
                kind = "sale" if m.group(1) == "매매" else "jeonse"
            m = re.search(r"[‘’']25년\s*[‘’']?26년\s+((?:\d{1,2}\.\d{1,2}\s*){6})", ln)
            if m and att in (1, 2) and kind:
                heads.setdefault((att, kind), (pi, li, m.group(1).split()))
    need = [(1, "sale"), (1, "jeonse"), (2, "sale"), (2, "jeonse")]
    if any(k not in heads for k in need):
        raise RuntimeError(f"{fname}: 표 머리글을 못 찾았다 {sorted(heads)}")
    weeks = heads[(1, "sale")][2]
    assert all(heads[k][2] == weeks for k in need), [heads[k][2] for k in need]

    def block(h, names):
        pi, li, _ = h
        lines = pages[pi][li + 1:]
        out = {}
        for n in names:
            for ln in lines:
                v = row(ln, n)
                if v:
                    out[n] = {"ytd_2025": v[0], "ytd_2026": v[1], "weekly": dict(zip(weeks, v[2:]))}
                    break
        missing = [n for n in names if n not in out]
        if missing:
            raise RuntimeError(f"{fname}: {missing} 행을 못 찾았다")
        return out

    seoul = {"sale": block(heads[(1, "sale")], ["서 울"])["서 울"], "jeonse": block(heads[(1, "jeonse")], ["서 울"])["서 울"]}
    s, j = block(heads[(2, "sale")], GROUPS + GU), block(heads[(2, "jeonse")], GROUPS + GU)
    return {
        "published": pub,
        "embargo_kst": f"{pub}T{emb.group(4)}:00+09:00",
        "reference_date": f"{emb.group(1)}-{int(ref.group(1)):02d}-{int(ref.group(2)):02d}",
        "weeks": weeks,
        "seoul": seoul,
        "groups": {g: {"sale": s[g], "jeonse": j[g]} for g in GROUPS},
        "gu": {g: {"sale": s[g], "jeonse": j[g]} for g in GU},
        "file": fname,
    }


def save(sn, fname=None, pages=None):
    if pages is None:
        fname, pages = fetch(sn)
    rel = parse(fname, pages)
    rel["source_url"] = INFO + sn
    rel["fetched_at"] = datetime.now(KST).strftime("%Y-%m-%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{rel['published']}.json"
    path.write_text(json.dumps(rel, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return rel, path


def load_all():
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(OUT_DIR.glob("*.json"))}


def check():
    """발표끼리 겹치는 주 값이 같은지, 10월 원문(PDF)에서 옮긴 값과 같은지 본다."""
    rels = load_all()
    errs, cells = [], 0
    seen = {}
    for pub, r in sorted(rels.items()):
        for g, kinds in list(r["gu"].items()) + list(r["groups"].items()) + [("서울", r["seoul"])]:
            for kind, d in kinds.items():
                for w, v in d["weekly"].items():
                    k = (g, kind, w)
                    if k in seen and seen[k][1] != v:
                        errs.append(f"수정됨 {k}: {seen[k][0]} {seen[k][1]} → {pub} {v}")
                    seen.setdefault(k, (pub, v))
                    cells += 1
    if OCT.exists():
        oct_ = json.loads(OCT.read_text(encoding="utf-8"))
        for o in oct_["releases"]:
            r = rels.get(o["published"])
            if not r:
                continue
            for g in o["gu"]:
                for kind in ("sale", "jeonse"):
                    if o["gu"][g][kind] != r["gu"][g][kind]:
                        errs.append(f"10월 원문과 다름 {o['published']} {g} {kind}")
            if o["seoul"] != r["seoul"] or o["groups"] != r["groups"]:
                errs.append(f"10월 원문과 다름 {o['published']} 서울·권역")
    return cells, errs


def main():
    ap = argparse.ArgumentParser(description="부동산원 주간 동향 수집")
    ap.add_argument("--sn", nargs="*", help="게시글 번호(nttSn)")
    ap.add_argument("--since", default="2026-07-27", help="이 기준일 이후 발표만 (YYYY-MM-DD)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--import-raw", metavar="DIR",
                    help="뷰어 텍스트 원본(JSON: nttSn·file·pages[항목 목록])을 따로 받아 둔 폴더에서 들인다")
    args = ap.parse_args()

    if args.import_raw:
        for p in sorted(Path(args.import_raw).glob("*.json")):
            raw = json.loads(p.read_text(encoding="utf-8"))
            rel, path = save(str(raw["nttSn"]), raw["file"], [page_lines(x) for x in raw["pages"]])
            print(f"  {raw['nttSn']} → {path.relative_to(REPO)} (기준 {rel['reference_date']})", flush=True)
    elif not args.check:
        targets = args.sn or [sn for sn, ref in sorted(board().items(), key=lambda x: x[1])
                              if f"{ref[:4]}-{ref[4:6]}-{ref[6:]}" >= args.since]
        have = {r.get("source_url", "").rsplit("=", 1)[-1] for r in load_all().values()}
        for sn in targets:
            if sn in have and not args.sn:
                continue
            try:
                rel, path = save(sn)
                print(f"  {sn} → {path.relative_to(REPO)} (기준 {rel['reference_date']}, 주 {rel['weeks'][0]}~{rel['weeks'][-1]})",
                      flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  [실패] {sn}: {exc}", file=sys.stderr, flush=True)
    cells, errs = check()
    print(f"\n대조 {cells}칸 · 어긋남 {len(errs)}건")
    for e in errs[:20]:
        print("  -", e)
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
