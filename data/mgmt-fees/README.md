# 단지별 ㎡당 공용관리비 캐시

`scripts/kapt_fees.py`(공식 OpenAPI)와 `scripts/kapt_mirror.py`(보조 경로)가 쓰고,
콘텐츠 생성기가 읽는다. 파일 하나가 **단지 1곳**이고, 그 안에서 **월별**로 쌓인다.
경로는 `data/mgmt-fees/<slug>.json`.

## 현재 상태 (2026-08-16)

11개 단지 × 2026년 5~6월 = **22건 확보. 21건 완전, 19건 대조 일치.**

공용관리비 금액은 공공데이터포털 공식 OpenAPI에서 항목별 17개를 받아 합산한 값이다.
합산 결과가 K-apt 공개 총액과 일치하는지 매 건 대조하며, 원베일리 6월분은 차이 0원이었다.

부과면적도 공식 경로다(`area_source: official_api`). 기본 정보제공 서비스가 승인돼
`getAphusBassInfoV4`의 **`kaptMarea`(관리비부과면적)** 를 쓴다. 이 필드만 받는다 —
`kaptTarea`는 건축물대장 연면적(원베일리 673,553㎡), `privArea`는 전용면적합(270,686㎡)이라
잘못 집으면 ㎡당 단가가 통째로 틀어진다.

개별사용료와 장기수선충당금은 아직 [별도 서비스](https://www.data.go.kr/data/15059469/openapi.do)
미신청이라 공개 페이지 경유로 채운다(`breakdown`). 같은 호출로 받은 공개 총액은
공식 17항목 합산값을 검산하는 데도 쓴다(`crosscheck`).

```bash
export KAPT_SERVICE_KEY="발급받은_Decoding_키"   # .env 에 두고 커밋하지 않는다
python3 scripts/kapt_fees.py --month 202606
python3 scripts/kapt_fees.py --probe            # 키 없이 엔드포인트 점검
```

## 스키마

값 자리의 `<...>`는 타입 표기다. 실제 수치를 예시로 넣지 않는다 —
예시 숫자가 실측값으로 오인돼 본문에 인용되는 사고를 막기 위해서다.

```jsonc
{
  "slug": "one-bailey",
  "complex_name": "래미안 원베일리",
  "kapt_code": "<K-apt 단지코드>",
  "latest_period": "<보유한 가장 최근 YYYYMM>",
  "periods": {
    "202606": {
      "period": "202606",
      "area_m2": "<관리비부과면적 ㎡>",
      "area_m2_derived": "<같은 값. 생성기가 쓰는 이름>",
      "area_source": "official_api | public_mirror | unavailable",
      "common_fee_total_won": "<공용관리비 17항목 합계 원>",
      "per_m2_won": "<합계 ÷ 면적. 면적을 못 구하면 null>",
      "items": {
        "인건비": { "amount_won": "<원>", "detail": { "<세부비목>": "<원>" }, "op": "getHsmpLaborCostInfoV2" }
        // ... 17개 항목
      },
      "breakdown": {
        // 공용관리비 / 개별사용료 / 장기수선충당금 / 합계 — 각 total_won, per_m2_won
        // 개별사용료와 장기수선충당금은 별도 서비스라 공개 페이지 경유로 채운다
      },
      "crosscheck": {
        "official_common_fee_won": "<17항목 합산>",
        "mirror_common_fee_won": "<공개 총액>",
        "diff_won": "<차이>", "match": "<허용오차 안이면 true>"
      },
      "failures": {},        // 항목명 → 실패 사유. 비어 있어야 정상
      "complete": true,      // false면 본문 인용 금지
      "warning": "<있을 때만>",
      "fetched_at": "<ISO8601 조회 시각>"
    }
  },
  "failed_periods": {}
}
```

## 인용 규칙

1. **`complete: false`면 본문에 수치를 쓰지 않는다.** 17항목 중 하나라도 실패하면
   합계가 과소 계상되므로, 부분 합계를 전체처럼 인용하면 오보가 된다.
2. **`per_m2_won`이 null이면 ㎡당 단가를 인용하지 않는다.** 부과면적을 못 구한 경우다.
   금액 자체는 유효하므로 총액은 쓸 수 있다.
3. **`crosscheck.match`가 false면 인용 전에 확인한다.** 공식 합산과 공개 총액이
   어긋난다는 뜻이라, 어느 쪽이 맞는지 가려지기 전에는 쓰지 않는다.
4. **`fetched_at`과 `period`를 본문에 함께 적는다.** 관리비는 월별로 바뀌고
   K-apt 공개 시점도 단지마다 다르다. "언제 조회한 몇 월분인지" 없는 숫자는 쓸 수 없다.
5. **범위를 명시한다.** `per_m2_won`은 공용관리비만이다. 주민이 고지서에서 보는 총액은
   여기에 개별사용료와 장기수선충당금이 더해진 금액이다.
6. **단지 간 비교는 같은 `period`끼리만.** 계절 편차가 크다.

## 알아 둘 함정

**미공개 월은 0원으로 온다.** 포털은 자료가 없어도 200에 빈 item을 돌려주는데,
이때 `kaptCode`까지 null이다. 그대로 합산하면 "0원"이라는 실제 수치처럼 기록된다.
실제로 파크리오 2026-06에서 이 사고가 났고, 지금은 `_is_no_data()`가 걸러 `failures`에
남긴다. 공개 시점은 단지마다 달라서 같은 달이 어떤 단지엔 있고 어떤 단지엔 없다.

**서비스마다 활용신청이 따로다.** 키 하나로 모든 K-apt 서비스가 열리지 않는다.
공용관리비·기본정보는 승인됐지만 개별사용료는 아직 `SERVICE_KEY_IS_NOT_REGISTERED`가 돌아온다.

## 아직 안 되는 것

- 개별사용료 공식 조회 — [별도 서비스](https://www.data.go.kr/data/15059469/openapi.do) 활용신청 필요
- 장기수선충당금 공식 조회 — 위와 같음
- 공시가격 — 브이월드 API가 이 환경에서 접속 불가. `scripts/vworld_price.py` 참고
- 세대별·평형별 관리비 — K-apt OpenAPI는 단지 단위로만 공개한다
