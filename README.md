# SmartPitch Backend

MLB 실시간 투구 데이터를 수신하고 DQN 모델로 다음 투구를 예측하는 FastAPI 백엔드 서버.

---

## 기술 스택

| 역할 | 기술 |
|------|------|
| API 서버 | FastAPI + Uvicorn |
| DB | MySQL 8.0 + SQLAlchemy + Alembic |
| 캐시 / 메시징 | Redis 7 |
| ML 모델 | stable-baselines3 DQN + PyTorch |
| 실시간 데이터 | MLB Stats API (statsapi.mlb.com) |
| 패키지 관리 | uv |
| 컨테이너 | Docker Compose |

---

## 아키텍처

```
MLB Stats API
    ↓ 10초마다 폴링
FastAPI 백엔드
    ├→ DQN 모델 추론 (투구 예측)
    ├→ MySQL (투구 이력 저장)
    └→ Redis Pub-Sub → WebSocket → 프론트엔드
```

---

## 사전 준비

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) 설치
- `SmartPitch_handoff/` 폴더가 이 레포 **내부**에 위치해야 함

```
backend/                  ← 이 레포
├── SmartPitch_handoff/   ← 모델 파일 폴더
│   ├── dqn_cease_2024_2025.zip
│   ├── dqn_gallen_2024_2025.zip
│   ├── best_transition_model_universal.pth
│   └── data/
│       └── batter_clusters_2023.csv
└── ...
```

---

## 실행 방법

### 1. 클론 및 환경 변수 설정

```bash
git clone https://github.com/Pitcheezy/backend.git
cd backend
cp .env.example .env
```

### 2. 빌드 및 시작

```bash
docker compose up --build
```

> 첫 빌드는 PyTorch 설치로 인해 10~20분 소요됩니다.

### 3. DB 마이그레이션 (최초 1회)

```bash
docker compose exec api uv run alembic upgrade head
```

### 4. 동작 확인

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/models
# → {"status":"ok","loaded_models":["cease","gallen"]}
```

자세한 실행 가이드는 [`docs/getting-started.md`](docs/getting-started.md)를 참고하세요.

---

## API 목록

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 |
| GET | `/health/db` | DB 연결 상태 |
| GET | `/health/models` | ML 모델 로딩 상태 |
| GET | `/api/games` | 오늘 경기 목록 |
| GET | `/api/games/{game_pk}` | 단건 경기 정보 |
| POST | `/api/predict` | 투구 예측 |
| POST | `/api/replay/start` | 과거 경기 재생 시작 |
| POST | `/api/replay/stop` | 재생 중지 |
| GET | `/api/replay/status` | 재생 실행 여부 |
| WS | `/ws/{game_pk}` | 실시간 경기 데이터 수신 |

전체 요청/응답 스키마는 [`docs/api-response.md`](docs/api-response.md)를 참고하세요.

### WebSocket 메시지 구조 (`GameStateMessage`)

```json
{
  "game_pk": 12345,
  "inning": 3,
  "half": "top",
  "outs": 1,
  "balls": 2,
  "strikes": 1,
  "on_1b": false,
  "on_2b": true,
  "on_3b": false,
  "batter_id": 123,
  "batter_name": "Juan Soto",
  "pitcher_id": 456,
  "pitcher_name": "Dylan Cease",
  "last_pitch": {
    "pitch_type": "4-Seam Fastball",
    "zone": 5,
    "velocity": 97.2,
    "result": "Ball"
  },
  "pitch_sequence": [
    { "pitch_type": "Slider", "zone": 14, "velocity": 88.1, "result": "Swinging Strike" },
    { "pitch_type": "4-Seam Fastball", "zone": 5, "velocity": 97.2, "result": "Ball" }
  ],
  "prediction": {
    "pitch_type": "Slider",
    "zone": 14,
    "action": 183,
    "batter_cluster": 2,
    "confidence": 0.38
  },
  "pitcher_stats": {
    "era": 3.45,
    "whip": 1.12,
    "k9": 10.8,
    "ip_season": 52.3,
    "pitches_today": 67,
    "pitch_mix": [
      { "pitch_type": "Four-Seam Fastball", "count": 28, "share": 0.42, "avg_velocity": 97.1 },
      { "pitch_type": "Slider", "count": 22, "share": 0.33, "avg_velocity": 87.4 }
    ],
    "velocity_trend": [97.2, 96.8, 97.5, 96.1, 95.8],
    "current_velocity": 95.8,
    "peak_velocity": 98.2,
    "inning_pitches": [
      { "inning": 1, "count": 18 },
      { "inning": 2, "count": 14 }
    ],
    "change_index": 42.5
  },
  "batter_stats": {
    "avg": 0.287,
    "ops": 0.875,
    "hr": 8,
    "rbi": 25
  }
}
```

- `pitch_sequence`: 현재 타석의 전체 투구 이력 (오래된 순)
- `last_pitch`: `pitch_sequence`의 마지막 요소와 동일
- `prediction.confidence`: 선택 액션 확률 / 상위 3개 액션 확률 합 (상위 후보 내 상대 신뢰도)
- `pitcher_stats`: 시즌 스탯(MLB Stats API) + 게임 내 누적 통계(실시간 계산)
- `batter_stats`: 시즌 스탯(MLB Stats API)
- WebSocket 연결 직후 Redis 캐시에서 최신 상태를 즉시 전송 (빈 화면 방지)

---

## ML 모델

| 투수 | 파일 | 구종 |
|------|------|------|
| Dylan Cease | `dqn_cease_2024_2025.zip` | Fastball, Slider, Changeup |
| Zac Gallen | `dqn_gallen_2024_2025.zip` | Fastball, Slider, Changeup, Curveball |
| Gerrit Cole | `smartpitch_dqn_final.zip` | Fastball, Slider, Curveball, Changeup |

- **입력:** `[balls, strikes, outs, on_1b, on_2b, on_3b, batter_cluster, pitcher_cluster]` (8차원)
- **출력:** `action → pitch_type (action // 13)`, `zone (action % 13)`
- Cole 모델은 W&B Artifact에서 별도 다운로드 필요 (`README.txt` 참고)

---

## CORS 허용 출처

개발 환경에서 아래 출처의 요청을 허용합니다.

| 출처 | 용도 |
|------|------|
| `http://localhost:5173` | Vite 개발 서버 (기본 포트) |
| `http://localhost:5174` | Vite 개발 서버 (5173 충돌 시 대체 포트) |
| `http://localhost:3000` | Next.js / CRA 개발 서버 |

프로덕션 배포 시 `main.py`의 `allow_origins` 목록을 실제 도메인으로 교체하세요.

---

## 프론트엔드 통합 실행

`docker-compose.yml`에 프론트엔드 서비스가 포함되어 있어 **Docker Desktop만 있으면** 백엔드·프론트엔드를 한 번에 실행할 수 있습니다.

```bash
# baseball-back/ 에서 실행
docker compose up --build
```

| 컨테이너 | 포트 | 설명 |
|----------|------|------|
| `smartpitch-api` | 8000 | FastAPI 백엔드 |
| `smartpitch-frontend` | 5173 | React 앱 (nginx) |
| `smartpitch-db` | 3306 | MySQL |
| `smartpitch-redis` | 6379 | Redis |

빌드 후 `http://localhost:5173` 접속, 아래 명령으로 리플레이 시작:

```bash
curl -X POST http://localhost:8000/api/replay/start \
  -H "Content-Type: application/json" \
  -d '{"game_pk": 825106, "interval": 4.0}'
```

> 프론트엔드 소스는 `../baseball-front/frontend`에서 빌드됩니다. 두 레포가 같은 상위 디렉터리에 있어야 합니다.

---

## 주요 변경 이력

### 2026-04-27

**`app/services/replay.py` — 리플레이 강화**
- MLB Stats API에서 투수·타자 시즌 스탯(ERA/WHIP/K9/IP, AVG/OPS/HR/RBI) 경기 시작 전 일괄 조회
- `_PitcherTracker`: 리플레이 진행 중 투수별 구종 믹스·구속 추이·이닝별 투구 수 실시간 누적
- `change_index` 실시간 계산 (투구 수 + 구속 낙폭 기반)
- 예외 발생 시 silent fail 대신 ERROR 로그 출력으로 수정

**`app/schemas/pitch.py` — 신규 스키마**
- `PitcherLiveStats`: 시즌 스탯 + 게임 내 누적 통계를 하나의 모델로 통합
- `HitterLiveStats`: 타자 시즌 스탯
- `PitchMixEntry`, `InningPitchCount` 서브 모델 추가
- `GameStateMessage`에 `pitcher_stats`, `batter_stats` 필드 추가

**`app/ml/inference.py` — confidence 계산 개선**
- 기존: 전체 액션(최대 39개) softmax → 균등분포 수렴으로 항상 2~3% 표시
- 변경: 선택 액션 확률 / 상위 3개 액션 확률 합 → 30~70%대의 의미있는 신뢰도

**`.env` — Redis URL 수정**
- `redis://localhost:6379` → `redis://cache:6379` (Docker 컨테이너 간 통신)

**`docker-compose.yml` — 프론트엔드 서비스 추가**
- `smartpitch-frontend` 컨테이너 추가 (nginx, 포트 5173)

**`app/main.py` — CORS**
- `http://localhost:5174` 추가 (Vite 포트 충돌 시 대체 포트 대응)

---

## 프로젝트 구조

```
backend/
├── app/
│   ├── main.py              # 서버 진입점 (lifespan: 모델 로딩 + 폴러 시작)
│   ├── config.py            # 환경 변수 관리
│   ├── db/session.py        # MySQL 비동기 세션
│   ├── models/pitch.py      # DB 테이블 (Game, Pitch)
│   ├── schemas/             # Pydantic 스키마
│   ├── ml/
│   │   ├── loader.py        # DQN 모델 + batter_clusters 로딩
│   │   └── inference.py     # 투구 예측 로직
│   ├── services/
│   │   ├── mlb_poller.py    # MLB API 폴링 → Redis 브로드캐스트
│   │   ├── predictor.py     # /api/predict 서비스
│   │   └── replay.py        # 과거 경기 재생
│   └── routers/
│       ├── health.py
│       ├── games.py
│       ├── predict.py
│       ├── replay.py
│       └── ws.py
├── alembic/                 # DB 마이그레이션
├── docs/
│   ├── getting-started.md   # 팀원 실행 가이드
│   └── api-response.md      # 프론트엔드 API 명세
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```
