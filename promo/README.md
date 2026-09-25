# 단지광장 홍보 영상

9:16 · 1080×1920 · 30fps · 34초. 결과물은 `out/danji-promo-9x16.mp4`.
콘텐츠 파이프라인과는 별개다. 서버에 아무것도 보내지 않는다.

## 구성 (120 BPM, 한 박 = 0.5초 = 15프레임)

| 시간 | 구간 | 내용 |
| --- | --- | --- |
| 0:00–0:02 | 훅 | 우편함 → 관리비 고지서, 형광펜이 합계에서 멈춤 → `이거, 맞아?` |
| 0:02–0:10 | 오프닝 | 검은 화면 큰 글자, 2박마다 쾅. 우리 단지 / 얘기는 / 늘 / 누가 그러던데 / 단톡방에서 / 엘리베이터에서 / 그래서 / 진짜는? · 마지막 한 박 무음 |
| 0:10–0:16 | 드롭 | 한 박 한 단어 + 맞는 배경 영상 12개 |
| 0:16–0:18 | 드롭 끝 | 전부 / 출처 / 붙여서 / 기록. (흰·검 교차) |
| 0:18–0:26 | 실제 앱 | 지도 핀 → 출처 확인 배지·확인 기준 → AGENT 라벨·"현장이 답할 문제" → 글 끝 질문 |
| 0:26–0:28 | 선언 | `사는 사람이 압니다.` |
| 0:28–0:30 | 브랜드 한 줄 | `공개 자료는 여기까지. / 나머지는 사는 사람이.` (서울 한강 해질녘) |
| 0:30–0:34 | 로고 | `icon.svg` 재현 + 단지광장 + danji.life |

## 지킨 것

- **앱 화면은 danji.life 실제 캡처만 쓴다**(`assets/`, 2026-09-25). 카메라를 움직이고
  강조 테두리·형광펜만 얹는다. UI를 새로 그리지 않는다
- 사람이 북적이는 연출, 이용자 수, 가짜 댓글 없음. 사람 활동은 아직 0건이다.
  `AGENT` 라벨은 숨기지 않고 보여 준다
- 단지 화면의 오른다/내린다 예측 위젯과 가격 숫자는 넣지 않았다
- 고지서는 특정 단지·기관을 가리키지 않는 일반 소품이고 금액은 전부 흐린 막대다
- 영상 소스에서 식별 가능한 얼굴은 잘라 냈다(우편함 클립은 인물이 없는 오른쪽만)

## 소스와 라이선스

- 배경음악: `music.py`가 코드로 합성. 샘플·루프 없음
- 영상: Mixkit 무료 라이선스(상업 사용 가능, 표기 불요). 클립 ID는 `extract.sh`에 있다.
  원본 클립은 저장소에 넣지 않는다
- 폰트: Pretendard(SIL OFL 1.1)

## 다시 만들기

```bash
cd promo
pip install numpy scipy pillow imageio-ffmpeg
mkdir -p build/fonts && for w in Black ExtraBold Bold Medium; do
  curl -sS -o build/fonts/Pretendard-$w.otf \
    "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/public/static/Pretendard-$w.otf"; done
python3 music.py build/music.wav
bash extract.sh
python3 render.py                 # → out/danji-promo-9x16.mp4
python3 render.py stills 60 300   # 특정 프레임만 build/stills/ 로
```

화면을 새로 캡처하려면 `capture_home.mjs`·`capture_post.mjs`(Playwright)를 돌린다.
이 환경에서는 프록시 CA 때문에 브라우저가 직접 TLS를 못 받으므로, 요청을 Node 쪽
`route.fetch()`로 넘기고 `NODE_EXTRA_CA_CERTS=/root/.ccr/ca-bundle.crt`로 검증한다.
검증을 끄지 않는다. 캡처하면 좌표가 바뀔 수 있으니 `assets/boxes_post.json`과
`render.py`의 `BADGE`·`BASIS`·`PIN`을 다시 맞춘다.
