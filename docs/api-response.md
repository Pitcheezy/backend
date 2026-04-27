# SmartPitch Backend API 응답 명세

> 작성일: 2026-04-27  
> 작성: 백엔드 팀  
> 대상: 프론트엔드 팀

---

## 우선순위별 처리 결과

| 우선순위 | 항목 | 결과 |
|---|---|---|
| 🔴 필수 | `GameStateMessage` JSON 스키마 | ✅ 아래 확정 스키마 참고 |
| 🔴 필수 | `GET /api/games` 엔드포인트 | ✅ 구현 완료 |
| 🟡 중요 | `GET /api/games/{game_pk}` | ✅ 구현 완료 |
| 🟡 중요 | `pitcher_key` WS 메시지 포함 | ✅ 구현 완료 |
| 🟡 중요 | `pitcher_id` 기반 predict 지원 | ✅ 구현 완료 (옵션 A+B 모두) |
| 🟡 중요 | `prediction.confidence` | ✅ 구현 완료 (Q-value softmax) |
| 🟡 중요 | `batter_name` WS 포함 | ✅ 기존에도 포함됨 |
| 🟡 중요 | `away_score`, `home_score` | ✅ 구현 완료 |
| 🟡 중요 | `inning`, `half` | ✅ 구현 완료 (`half` 필드명 확정) |
| 🟡 중요 | `away_team_id`, `home_team_id` | ✅ `away_team.id`, `home_team.id` 로 제공 |
| 🟡 중요 | `inning_line` | ✅ 구현 완료 |
| 🟡 중요 | `last_pitch` | ✅ 구현 완료 |
| 🟢 나중 | pitches DB 저장 → 통계 API | ❌ 추후 스프린트 |
| 🟢 나중 | condition[] / changeIndex 모델 | ❌ 추후 스프린트 |

---

## 응답 Envelope

REST 엔드포인트(`/api/games`, `/api/games/{game_pk}`)는 모두 아래 구조로 반환합니다.

```json
{
  "status": "ok",
  "updated_at": "2026-04-27T10:00:00Z",
  "data": { ... },
  "error": null
}
```

에러 시:
```json
{
  "status": "error",
  "updated_at": "2026-04-27T10:00:00Z",
  "data": null,
  "error": { "code": "MLB_API_ERROR", "message": "설명" }
}
```

---

## 1. WebSocket — `GameStateMessage` 확정 스키마

**엔드포인트:** `WS /ws/{game_pk}`  
**전송 주기:** 10초마다 (Live 경기), replay 시 설정한 interval

```json
{
  "game_pk": 824046,
  "inning": 4,
  "half": "bottom",
  "away_score": 2,
  "home_score": 1,
  "away_team": {
    "id": 141,
    "name": "Toronto Blue Jays",
    "code": "TOR"
  },
  "home_team": {
    "id": 108,
    "name": "Los Angeles Angels",
    "code": "LAA"
  },
  "inning_line": {
    "away": [0, 1, 0, 1],
    "home": [0, 0, 1, null]
  },
  "batter_id": 660271,
  "batter_name": "Mike Trout",
  "pitcher_id": 656302,
  "pitcher_name": "Dylan Cease",
  "pitcher_key": "cease",
  "balls": 1,
  "strikes": 2,
  "outs": 1,
  "on_1b": true,
  "on_2b": false,
  "on_3b": false,
  "last_pitch": {
    "pitch_type": "Slider",
    "zone": 6,
    "velocity": 88.5,
    "result": "Called Strike"
  },
  "prediction": {
    "pitcher_key": "cease",
    "pitch_type": "Fastball",
    "zone": 8,
    "batter_cluster": 3,
    "action": 7,
    "confidence": 0.4231
  }
}
```

### 필드 설명

| 필드 | 타입 | 설명 |
|---|---|---|
| `game_pk` | int | MLB 경기 고유 ID |
| `inning` | int \| null | 현재 이닝 (1~9+) |
| `half` | `"top"` \| `"bottom"` \| null | 이닝 전/후반 |
| `away_score` | int \| null | 원정팀 득점 |
| `home_score` | int \| null | 홈팀 득점 |
| `away_team.id` | int | MLB 팀 ID |
| `away_team.name` | string | 팀 풀네임 |
| `away_team.code` | string | 팀 약어 (e.g. `"NYY"`) |
| `home_team` | 위와 동일 | 홈팀 정보 |
| `inning_line.away` | int[] | 이닝별 득점 (index=이닝-1, null=미플레이) |
| `inning_line.home` | int[] | 이닝별 득점 |
| `batter_id` | int \| null | 현재 타자 MLB ID |
| `batter_name` | string \| null | 현재 타자 이름 |
| `pitcher_id` | int \| null | 현재 투수 MLB ID |
| `pitcher_name` | string \| null | 현재 투수 이름 |
| `pitcher_key` | `"cease"` \| `"gallen"` \| `"cole"` \| null | 모델 보유 투수만 값 있음, 나머지 null |
| `balls` | int | 볼 카운트 (0~3) |
| `strikes` | int | 스트라이크 카운트 (0~2) |
| `outs` | int | 아웃 카운트 (0~2) |
| `on_1b` | bool | 1루 주자 여부 |
| `on_2b` | bool | 2루 주자 여부 |
| `on_3b` | bool | 3루 주자 여부 |
| `last_pitch.pitch_type` | string \| null | 직전 투구 구종 |
| `last_pitch.zone` | int \| null | 직전 투구 존 번호 |
| `last_pitch.velocity` | float \| null | 직전 투구 구속 (mph) |
| `last_pitch.result` | string \| null | 직전 투구 결과 (예: `"Called Strike"`, `"Ball"`) |
| `prediction` | object \| null | `pitcher_key`가 null이면 prediction도 null |
| `prediction.pitch_type` | string | 예측 구종 |
| `prediction.zone` | int | 예측 존 번호 (1~9, 11~14) |
| `prediction.confidence` | float \| null | 예측 신뢰도 0~1 (Q-value softmax) |

> `prediction`은 cease / gallen / cole 이 마운드에 있을 때만 포함됩니다.  
> confidence는 모델 내부 Q-value를 softmax 변환한 값으로, 절대적 확률이 아닌 상대적 선호도입니다.

---

## 2. GET /api/games

오늘 경기 목록 반환.

```
GET /api/games
GET /api/games?status=live
GET /api/games?status=scheduled
GET /api/games?status=final
GET /api/games?date=2026-04-26        ← 특정 날짜 조회 가능
```

**Response `200`**

```json
{
  "status": "ok",
  "updated_at": "2026-04-27T10:00:00Z",
  "data": [
    {
      "game_pk": 824046,
      "status": "live",
      "inning": 5,
      "half": "top",
      "away_team": { "id": 141, "name": "Toronto Blue Jays", "code": "TOR" },
      "home_team": { "id": 108, "name": "Los Angeles Angels", "code": "LAA" },
      "away_score": 2,
      "home_score": 1,
      "starts_at": "2026-04-20T20:07:00Z",
      "venue": "Angel Stadium"
    }
  ],
  "error": null
}
```

**status 값**

| 값 | 의미 |
|---|---|
| `"live"` | 현재 진행 중 |
| `"scheduled"` | 경기 예정 |
| `"final"` | 종료 |
| `"cancelled"` | 취소 |
| `"postponed"` | 연기 |

---

## 3. GET /api/games/{game_pk}

단건 경기 조회. data 구조는 위와 동일.

```
GET /api/games/824046
```

**Response `200`**
```json
{
  "status": "ok",
  "updated_at": "...",
  "data": { "game_pk": 824046, ... },
  "error": null
}
```

**Response `404`**
```
HTTP 404 Not Found
```

---

## 4. POST /api/predict

`pitcher_key` (문자열) 또는 `pitcher_id` (MLB ID 숫자) 둘 다 허용합니다.

```json
// pitcher_key 방식 (기존)
{
  "pitcher_key": "cease",
  "batter_id": 663728,
  "balls": 1,
  "strikes": 0,
  "outs": 1
}

// pitcher_id 방식 (신규)
{
  "pitcher_id": 656302,
  "batter_id": 663728,
  "balls": 1,
  "strikes": 0,
  "outs": 1
}
```

**Response `200`**
```json
{
  "pitcher_key": "cease",
  "pitch_type": "Fastball",
  "zone": 8,
  "batter_cluster": 3,
  "action": 7,
  "confidence": 0.4231
}
```

**pitcher_id ↔ pitcher_key 매핑표**

| pitcher_id | pitcher_key | 선수 |
|---|---|---|
| 543243 | `"cole"` | Gerrit Cole |
| 656302 | `"cease"` | Dylan Cease |
| 668678 | `"gallen"` | Zac Gallen |

---

## 5. Replay (개발/테스트용)

경기가 없을 때 과거 경기 데이터를 실시간처럼 재생합니다.  
WebSocket 엔드포인트는 동일하게 사용합니다.

```
POST /api/replay/start
{ "game_pk": 824046, "interval": 5.0 }

POST /api/replay/stop

GET /api/replay/status
→ { "running": true }
```

---

## Mock으로 유지할 데이터 (변경 없음)

아래 데이터는 백엔드에 구현되지 않았습니다. 프론트 MSW mock 유지 바랍니다.

- 선수 시즌 성적 (ERA, AVG, OPS, WHIP 등)
- 구종 비율 (pitchMix), 구속 추이 (velocityTrend)
- 이닝별 투구수 (inningPitches)
- 투수 컨디션 지표 (condition[], changeIndex)
- 타구 분포 (spray chart)

---

## 존 번호 참고

```
포수 시점 기준
┌───┬───┬───┐
│ 1 │ 2 │ 3 │
├───┼───┼───┤
│ 4 │ 5 │ 6 │
├───┼───┼───┤
│ 7 │ 8 │ 9 │
└───┴───┴───┘
아웃사이드: 11(좌상) 12(우상) 13(좌하) 14(우하)
```
