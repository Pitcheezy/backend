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
    "confidence": 0.82
  }
}
```

- `pitch_sequence`: 현재 타석의 전체 투구 이력 (오래된 순)
- `last_pitch`: `pitch_sequence`의 마지막 요소와 동일
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
| `http://localhost:5173` | Vite 개발 서버 |
| `http://localhost:3000` | Next.js / CRA 개발 서버 |

프로덕션 배포 시 `main.py`의 `allow_origins` 목록을 실제 도메인으로 교체하세요.

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
