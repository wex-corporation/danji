# danji — 단지광장 콘텐츠 에이전트

서울 아파트 단지별 커뮤니티에 AI 페르소나가 글과 관점 댓글을 올리는 콘텐츠 파이프라인.

작업을 시작하기 전에 [`CLAUDE.md`](./CLAUDE.md)와 [`docs/operating-spec-v1.1.md`](./docs/operating-spec-v1.1.md)를 읽으세요.

## 빠른 시작

```bash
cp .env.example .env        # CIVIC_PULSE_API_KEY 입력
set -a && . ./.env && set +a

cd scripts
python3 build_v3_pack.py                     # 팩 생성 + 검증
python3 publish.py ../content/top10-v3.json  # 게시
```

표준 라이브러리만 사용합니다. 별도 설치가 필요 없습니다.

## 구조

| 경로 | 내용 |
| --- | --- |
| `CLAUDE.md` | 작업 규칙, 현재 상태, 다음 할 일 |
| `docs/` | 운영 명세, 서버 연동 규격 |
| `data/` | 단지 마스터, 페르소나 정의 |
| `content/` | 생성된 콘텐츠 팩(게시 이력) |
| `scripts/` | 팩 생성기, 게시 스크립트 |

## 주의

- API 키는 `.env`에만 둡니다. 커밋하지 마세요.
- `external_id`는 업서트 키입니다. 같은 ID로 재전송하면 수정되므로 재전송이 안전합니다.
- 멱등키는 `같은 키 + 다른 본문 → 409`입니다. 내용을 고치면 키 버전을 올리세요.
