# SmartPitch Backend — 실행 가이드

> 작성일: 2026-04-27

---

## 사전 준비

아래 두 가지가 설치되어 있어야 합니다.

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Git

---

## 폴더 구조 확인 (필수)

레포를 클론하기 전에 아래 구조를 맞춰야 합니다.  
`SmartPitch_handoff/`와 `backend/`가 **같은 위치**에 있어야 ML 모델이 로드됩니다.

```
Pitcheezy/
├── backend/              ← 이 레포
└── SmartPitch_handoff/   ← 별도 전달받은 모델 폴더
    ├── dqn_cease_2024_2025.zip
    ├── dqn_gallen_2024_2025.zip
    ├── best_transition_model_universal.pth
    └── data/
        ├── batter_clusters_2023.csv
        └── ...
```

---

## 최초 실행 (처음 한 번만)

### 1. 레포 클론

```bash
git clone https://github.com/Pitcheezy/backend.git
cd backend
```

### 2. 환경 변수 파일 생성

```bash
cp .env.example .env
```

`.env` 파일을 열어 비밀번호를 팀에서 공유한 값으로 수정합니다.

### 3. 컨테이너 빌드 및 시작

```bash
docker compose up --build
```

> ⚠️ 첫 빌드는 PyTorch 설치 때문에 **10~20분** 소요됩니다. 이후 재시작은 빠릅니다.

### 4. DB 마이그레이션 (다른 터미널에서)

컨테이너가 뜬 걸 확인하고 실행합니다.

```bash
docker compose exec api uv run alembic upgrade head
```

---

## 매번 실행할 때

```bash
# 시작
docker compose up

# 백그라운드로 시작
docker compose up -d

# 중지
docker compose down
```

---

## 동작 확인

서버가 뜨면 아래 명령어로 확인합니다.

```bash
# 서버 상태
curl http://localhost:8000/health

# ML 모델 로딩 확인
curl http://localhost:8000/health/models
# 정상: {"status":"ok","loaded_models":["cease","gallen"]}

# DB 연결 확인
curl http://localhost:8000/health/db

# 오늘 경기 목록
curl http://localhost:8000/api/games

# 투구 예측 테스트
curl -X POST http://localhost:8000/api/predict \
  -H "Content-Type: application/json" \
  -d '{"pitcher_key":"cease","batter_id":663728,"balls":1,"strikes":0,"outs":1}'
```

---

## 실시간 WebSocket 테스트

경기 시간이 아닐 때는 **Replay** 기능으로 과거 경기 데이터를 실시간처럼 재생할 수 있습니다.

### wscat 설치 (최초 1회)

```bash
npm install -g wscat
```

### Cease 경기 재생 (game_pk: 824046 / 2026-04-20)

```bash
# 터미널 1 — WebSocket 연결 (먼저 실행)
wscat -c ws://localhost:8000/ws/824046

# 터미널 2 — Replay 시작 (5초마다 한 투구씩 전송)
curl -X POST http://localhost:8000/api/replay/start \
  -H "Content-Type: application/json" \
  -d '{"game_pk": 824046, "interval": 5.0}'
```

### Gallen 경기 재생 (game_pk: 825106 / 2026-04-01)

```bash
# 터미널 1
wscat -c ws://localhost:8000/ws/825106

# 터미널 2
curl -X POST http://localhost:8000/api/replay/start \
  -H "Content-Type: application/json" \
  -d '{"game_pk": 825106, "interval": 5.0}'
```

### Replay 중지

```bash
curl -X POST http://localhost:8000/api/replay/stop
```

> 실제 MLB 경기 중에는 Replay 없이 자동으로 실시간 데이터가 흐릅니다.

---

## 문제 해결

### DB 접속 오류 (Access denied)

MySQL 볼륨이 오염된 경우입니다. 볼륨을 초기화하세요.

```bash
docker compose down -v
docker compose up --build
docker compose exec api uv run alembic upgrade head
```

### 모델이 로드되지 않음 (`loaded_models: []`)

`SmartPitch_handoff/` 폴더 위치를 확인하세요. `backend/`와 같은 레벨에 있어야 합니다.

### 포트 충돌

아래 포트가 사용 중인지 확인하세요.

| 포트 | 서비스 |
|------|--------|
| 8000 | FastAPI |
| 3306 | MySQL |
| 6379 | Redis |

---

## API 전체 목록

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 |
| GET | `/health/db` | DB 연결 상태 |
| GET | `/health/models` | ML 모델 로딩 상태 |
| GET | `/api/games` | 오늘 경기 목록 |
| GET | `/api/games/{game_pk}` | 단건 경기 정보 |
| POST | `/api/predict` | 투구 예측 |
| POST | `/api/replay/start` | Replay 시작 |
| POST | `/api/replay/stop` | Replay 중지 |
| GET | `/api/replay/status` | Replay 실행 여부 |
| WS | `/ws/{game_pk}` | 실시간 경기 데이터 수신 |

자세한 API 스키마는 [`docs/api-response.md`](api-response.md)를 참고하세요.
