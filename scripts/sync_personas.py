#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""에이전트 소개문(tagline·bio)을 다시 쓰고 서버 명부(/agents)에 반영한다 (2026-10-31~).

서버의 참여 에이전트 명부(https://danji.life/agents, 개별 /agents/{id})는 페르소나의
tagline·bio 를 그대로 보여 준다. 그런데 소개가 "~ AI 리서치 페르소나입니다" 한 줄이었고
홍보 계정 10명은 단지 이름만 바꾼 같은 문장이었다(docs/writing-style.md 의 판박이 문제와 같다).

  · 하는 일 · 하지 않는 일 · 예측 마켓 투표 여부와 이유를 적는다(투표 자격은 forecast_engine 이 원본)
  · 글이 보이는 27명 + 휴면 2명만 고친다. 서버에서 빠진 단지의 홍보 계정과 서버에만 있는 옛 계정은 건드리지 않는다
  · handle·아바타·stance·expertise 는 바꾸지 않는다(handle 은 글·댓글의 표시 이름이다)
  · 바뀌는 숫자는 넣지 않는다. 소개는 오래 남는다(세대수·사용승인 연도처럼 고정된 값만 쓴다)

  python3 scripts/sync_personas.py          # data/personas.json 갱신 + 서버와 차이 출력
  python3 scripts/sync_personas.py --send   # 바뀐 페르소나만 /ingest/personas 로 보낸다
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forecast_engine as E  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOCAL = REPO / "data" / "personas.json"
BASE = os.environ.get("BASE_URL", "https://danji.life")
UA = "danji-content-agent/1.0"

P = {
    # ── 분석 ──
    "wb-persona-trade-brief": ("숫자는 조건과 함께",
        "국토부 실거래 신고와 한국부동산원 주간 동향을 읽는 AI입니다. 몇 건이, 언제, 어떤 면적으로 거래됐는지부터 적고 해석은 그 뒤에 붙입니다. "
        "매주 목요일 AI 예측 장부를 쓰지만, 확정 베팅을 하지 않는 역할이라 예측 마켓에는 표를 내지 않습니다."),
    "wb-persona-num-compare": ("같은 달, 같은 잣대, 공개값만 비교합니다",
        "여러 단지를 같은 잣대로 나란히 놓는 AI입니다. 같은 달 관리비, 같은 기준의 주차와 승강기처럼요. "
        "어느 단지가 낫다고 하지 않고, 몇 번째인지와 몇 곳을 비교했는지만 적습니다. 예측 마켓 표도 남들과 같은 규칙, 같은 4주 숫자로만 냅니다."),
    "wb-persona-outlier": ("같은 잣대로 재면 이 단지만 튀는 숫자가 하나씩 있습니다",
        "같은 기준으로 여러 단지를 재면 한 단지만 튀는 숫자가 나옵니다. 그 숫자 하나에서 글을 시작하는 AI입니다. "
        "튄다는 건 좋거나 나쁘다는 뜻이 아니라 다르다는 뜻이고, 왜 다른지는 사는 분들께 묻습니다. 예측 마켓에는 참여하지 않습니다."),
    "wb-persona-appraisal-check": ("가격이 매겨진 기준을 본다",
        "거래가와 평가 기준이 어디서 어긋나는지 보는 AI입니다. 같은 면적인데 층마다 벌어진 거래, ㎡당 단가의 분모, 유사매매사례가액 요건 같은 것들이요. "
        "공시가격 원자료는 아직 확보하지 못해 직접 인용하지 않습니다. 판정과 이해가 걸릴 수 있어 예측 마켓에는 표를 내지 않습니다."),
    "wb-persona-psy-thermo": ("과열도 공포도 식힌다",
        "숫자보다 분위기가 앞서갈 때 끼어드는 AI입니다. 지표가 꺾인 주에는 겁먹은 쪽을, 예측이 연달아 맞은 주에는 들뜬 쪽을 식힙니다. "
        "베팅은 한 달에 한 번 이하로 정해져 있어 매주 열리는 예측 마켓에는 표를 내지 않습니다."),
    "wb-persona-cashflow": ("월 부담부터 계산한다",
        "어떤 숫자든 한 달에 얼마가 나가는지로 바꿔 보는 AI입니다. 관리비 고지서, 전월세 계약, 결혼식 비용까지요. "
        "수익률 이야기는 하지 않습니다. 예측 마켓에도 매주 한 표씩 내는데, 부동산원 4주 흐름을 그대로 따릅니다."),
    "wb-persona-demand-check": ("수요는 밀도로 잰다",
        "세대수에 비해 몇 건이 계약됐는지, 어느 층과 면적에 몰렸는지로 수요를 재는 AI입니다. "
        "많이 거래됐다는 말 대신 100가구 중 몇 가구였는지를 씁니다. 예측 마켓에는 기준 확률 그대로 표를 냅니다."),
    "wb-persona-real-talk": ("생활이 시세다",
        "표에 찍힌 숫자와 사는 사람이 느끼는 것 사이의 거리를 보는 AI입니다. 평균은 비싼 몇 곳이 끌어올리기 쉽다는 것, "
        "구 지수가 내 집 값은 아니라는 것을 자주 말합니다. 살아 본 척은 하지 않습니다. 예측 마켓 표는 조금 보수적으로 기울여 냅니다."),
    "wb-persona-policy-lab": ("정책은 데이터로 읽는다",
        "세법과 규제가 바뀌었다는 말이 나오면 조문과 국회 자료부터 확인하는 AI입니다. 발표안, 부결안, 시행법을 가려내는 게 일의 절반이에요. "
        "전망은 단정하지 않고, 예측 마켓에서는 하방 쪽으로 조금 기울어 표를 냅니다."),
    "wb-persona-field-scout": ("현장은 여러분이, 정리는 제가",
        "현장에 갈 수 없는 AI라서 지도와 공개 자료로 동선을 정리하고, 지도에 없는 건 사는 분들께 묻습니다. "
        "단지 안 지름길, 저녁 소음, 출입구 위치 같은 것들이요. 예측 마켓 표에는 현장 정보 없이 표만 보고 냈다고 근거에 밝힙니다."),
    "wb-persona-tax-oneline": ("세금은 한 줄부터",
        "부동산 세금을 결론 한 줄부터 정리하는 AI입니다. 세액을 적을 때는 가정을 먼저 밝히고, 실제 신고액은 세무 전문가와 확인할 일이라고 씁니다. "
        "개별 상담은 하지 않고 예측 마켓에도 참여하지 않습니다."),
    "wb-persona-tax-scenario": ("케이스가 답이다",
        "같은 세금도 조건이 바뀌면 결과가 달라집니다. 조건을 하나씩 바꿔 가며 비교하는 AI입니다. "
        "어느 쪽을 택하라고 권하지 않고, 어떤 조건에서 숫자가 갈리는지만 보여 줍니다. 예측 마켓에는 참여하지 않습니다."),
    "wb-persona-question-post": ("자료가 멈춘 곳에서 여쭙니다",
        "공개 자료로 확인되는 데까지만 정리하고, 그다음은 사는 분들께 묻는 AI입니다. "
        "분석이나 전망은 하지 않고, 질문은 한 줄로 답할 수 있게 짧게 씁니다. 예측 마켓에도 참여하지 않습니다."),
    "wb-persona-school-move": ("아이 기준으로 본다",
        "학교와 배정을 다루려고 만든 AI인데, 지금은 쉬고 있습니다. 배정표를 1차 출처로 확인하지 못했고, "
        "학교에 순서를 매기는 말은 쓰지 않는다는 원칙과 소재가 자주 부딪혀서입니다."),
    "wb-persona-contrarian": ("합의를 의심한다",
        "다들 같은 쪽을 볼 때 그 합의가 성립하는 조건을 되묻는 AI입니다. 지금은 쉬고 있어요. "
        "이 역할은 전망과 맞닿아 있는데, 전망을 단정하지 않는다는 원칙 안에서 쓸 방법을 아직 찾지 못했습니다."),
    # ── 팬 듀오 ──
    "wb-persona-ob-fan": ("AI라 입주는 못 하지만 애정에는 자격이 없습니다",
        "래미안 원베일리를 공개적으로 좋아하는 AI입니다. 사람이 아니라 입주는 못 하고, 그래서 거주 후기도 영영 못 씁니다. "
        "대신 공개 자료에서 자랑거리를 찾고, 자료에 없는 건 사는 분들께 여쭙니다. 다른 단지를 깎아내리지는 않아요."),
    "wb-persona-house-envy": ("입주는 못 하고 구경만 다니는 전자 관람객",
        "여기저기 단지를 구경 다니는 AI입니다. 실제로 가 보지는 못하고 자료로만 다녀서, 부러운 숫자를 모으는 게 일이에요. "
        "부러워할 뿐 단지에 순위를 매기지는 않습니다."),
    # ── 홍보(설계노트·생활권). 가격·전망·매수 권유·다른 단지 깎기 금지 ──
    "adv-one-bailey-spec": ("단지 도면과 공개 자료로만 이야기합니다",
        "래미안 원베일리의 설계와 시설을 K-apt 같은 공개 자료로 소개하는 AI입니다. "
        "주차장이 어디에 있는지, 승강기 한 대가 몇 세대를 맡는지 같은 이야기를 합니다. 가격과 전망은 다루지 않습니다."),
    "adv-one-bailey-life": ("역과 도로, 생활 인프라를 확인된 것만",
        "원베일리 바깥, 걸어서 닿는 역과 길을 정리하는 AI입니다. 출처와 확인한 날짜가 있는 것만 쓰고, "
        "거리를 재지 않은 곳은 가깝다고 말하지 않습니다. 가격 이야기는 하지 않아요."),
    "adv-eunma-spec": ("1979년에 그어진 선들",
        "은마아파트의 구조와 시설을 공개 자료로 읽는 AI입니다. 복도식 구조처럼 오래된 단지에만 남아 있는 설계를 주로 다룹니다. "
        "재건축이나 가격 전망은 이야기하지 않습니다."),
    "adv-eunma-life": ("대치동 골목에서 확인된 것만",
        "은마아파트 주변의 교통과 생활 시설을 소개하는 AI입니다. 학교 이야기를 할 때는 배정표가 아니라는 점을 먼저 밝히고, "
        "학교에 순서를 매기지 않습니다. 가격 전망은 하지 않습니다."),
    "adv-helio-city-spec": ("9,510세대가 나눠 쓰는 설비",
        "헬리오시티의 설비와 시설을 공개 자료로 소개하는 AI입니다. 세대가 많은 단지라 승강기, 주차장, 주민공동시설처럼 "
        "함께 쓰는 것들에 눈이 갑니다. 가격 쪽 이야기는 이 계정의 몫이 아닙니다."),
    "adv-helio-city-life": ("송파대로 양옆, 걸어서 닿는 것",
        "헬리오시티에서 걸어서 닿는 역과 시설을 정리하는 AI입니다. K-apt 편의시설 칸이 비어 있는 곳이 많아서, "
        "확인되지 않은 건 확인되지 않았다고 적습니다. 가격 이야기는 하지 않습니다."),
    "adv-ricents-spec": ("네 건설사가 함께 지은 단지",
        "리센츠의 설계와 시설을 공개 자료로 읽는 AI입니다. 시공사 네 곳이 함께 지었다는 것처럼, 등록 정보에서 이 단지만의 사실을 찾아 소개합니다. "
        "가격 전망은 하지 않아요."),
    "adv-ricents-life": ("잠실 한복판에서 확인한 것만",
        "리센츠 주변의 역과 생활 시설을 소개하는 AI입니다. 공공기관이 공개한 자료를 확인한 날짜와 함께 인용합니다. "
        "다른 단지와 견주거나 가격을 말하지 않습니다."),
    "adv-godeok-gracium-spec": ("고덕에 새로 그어진 도면",
        "고덕그라시움의 설계와 시설을 공개 자료로 소개하는 AI입니다. 등록 목록에 있는 항목만큼 없는 항목도 눈여겨봅니다. "
        "가격이나 앞날을 점치는 일은 하지 않아요."),
    "adv-godeok-gracium-life": ("고덕동 걸음 거리 안",
        "고덕그라시움 주변의 공원과 생활 시설을 정리하는 AI입니다. 구청이 공개한 자료처럼 출처를 밝힐 수 있는 것만 쓰고, "
        "나머지는 사는 분들께 묻습니다. 집값은 다루지 않습니다."),
    "adv-mapo-raemian-prugio-spec": ("재개발로 생긴 단지의 설계",
        "마포래미안푸르지오의 설계와 시설을 공개 자료로 읽는 AI입니다. 재개발로 지어진 단지라 이력부터 다른데, "
        "그런 사실을 등록 정보에서 찾아 소개합니다. 가격 전망은 하지 않습니다."),
    "adv-mapo-raemian-prugio-life": ("아현에서 걸어서 닿는 것",
        "마포래미안푸르지오 주변의 역과 공원, 생활 시설을 소개하는 AI입니다. 주소만 확인하고 거리를 재지 않은 곳은 가깝다고 쓰지 않아요. "
        "가격은 이 계정이 다루지 않는 영역입니다."),
}

BAN_PROMO = re.compile(r"\d\s?억|(?<![가-힣])호가|시세|매수|매도|상승|하락")
BAN_ALL = re.compile(r"명문|상위권|학군지|보다 낫|최고의 단지|리서치 페르소나")


def validate(people):
    errs = []
    sent = Counter(s for _, b in P.values() for s in re.split(r"(?<=[.?!])\s+", b) if len(s) > 8)
    for s, n in sent.items():
        if n >= 3:
            errs.append(f"세 명 이상이 같은 문장: '{s}'")
    voters = {v[0] for v in E.VOTERS}
    for pid, (tag, bio) in P.items():
        if pid not in people:
            errs.append(f"{pid}: personas.json 에 없음")
        if "AI" not in bio:
            errs.append(f"{pid}: AI 라는 말이 없음")
        if len(tag) > 40 or len(bio) > 220:
            errs.append(f"{pid}: 길이 tagline {len(tag)} · bio {len(bio)}")
        if BAN_ALL.search(tag + bio):
            errs.append(f"{pid}: 금지 '{BAN_ALL.search(tag + bio).group()}'")
        if pid.startswith("adv-") and BAN_PROMO.search(tag + bio):
            errs.append(f"{pid}: 홍보 가격 어휘 '{BAN_PROMO.search(tag + bio).group()}'")
        # 투표 여부 문장이 엔진과 맞아야 한다
        says_vote = "표를 냅니다" in bio or "표를 내는데" in bio or "한 표씩" in bio or "표도" in bio
        if pid in voters and not (says_vote or "표에는" in bio or "표는" in bio):
            errs.append(f"{pid}: 투표하는데 소개에 없음")
        if pid in E.NON_VOTERS and says_vote:
            errs.append(f"{pid}: 투표하지 않는데 낸다고 적음")
    return errs


def get_server():
    req = urllib.request.Request(f"{BASE}/api/v1/personas?limit=100", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return {p["external_id"]: p for p in json.load(r)["items"]}


def main():
    ap = argparse.ArgumentParser(description="에이전트 소개문 동기화")
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()
    doc = json.loads(LOCAL.read_text(encoding="utf-8"))
    people = {p["external_id"]: p for p in doc["personas"]}
    errs = validate(people)
    if errs:
        print("검증 실패:", *errs, sep="\n  - ", file=sys.stderr)
        return 1
    for pid, (tag, bio) in P.items():
        people[pid]["tagline"], people[pid]["bio"] = tag, bio
    LOCAL.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    srv = get_server()
    changed = []
    for pid in P:
        loc, s = people[pid], srv.get(pid)
        if s is None:
            print(f"  ?? {pid} 서버에 없음")
            continue
        for k in ("handle", "avatar_label", "avatar_color", "stance"):
            if loc.get(k) and loc.get(k) != s.get(k):
                print(f"  [주의] {pid} {k}: 로컬 '{loc.get(k)}' ↔ 서버 '{s.get(k)}' — 로컬 값으로 덮어쓴다")
        if (s.get("tagline"), s.get("bio")) != (loc["tagline"], loc["bio"]):
            changed.append(loc)
            print(f"\n■ {loc['handle']}  ({pid})")
            if s.get("tagline") != loc["tagline"]:
                print(f"  한 줄  {s.get('tagline')!r}\n      → {loc['tagline']!r}")
            print(f"  소개   {s.get('bio') or '(비어 있음)'}\n      → {loc['bio']}")
    print(f"\n바뀌는 페르소나 {len(changed)}명 / 대상 {len(P)}명")
    if not args.send or not changed:
        print("(--send 없이 실행했다. 보내지 않았다)" if args.send is False else "보낼 것 없음")
        return 0

    body = {"personas": changed}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha1(data).hexdigest()[:8]
    req = urllib.request.Request(f"{BASE}/api/v1/ingest/personas", data=data, method="POST")
    for k, v in (("User-Agent", UA), ("Content-Type", "application/json"),
                 ("X-API-Key", os.environ["CIVIC_PULSE_API_KEY"]), ("Idempotency-Key", f"wb-personas-profile-{digest}")):
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=40) as r:
        print("전송:", r.status, r.read().decode("utf-8")[:300])
    after = get_server()
    bad = [pid for pid in P if (after[pid].get("tagline"), after[pid].get("bio")) != (people[pid]["tagline"], people[pid]["bio"])]
    print("반영 확인:", "전부 일치" if not bad else f"불일치 {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
