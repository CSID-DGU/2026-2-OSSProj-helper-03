# ui

Helper의 화면(준비 화면, 보조 화면, 설정 화면)입니다. React + Vite + TypeScript.

엔진(로컬 서버)과는 WebSocket(`ws://localhost:8000/ws`) 하나로만 주고받습니다. 엔진이 아직 없을 때는 같은 주소에서 도는 **모의 서버**로 개발합니다.

## 실행

Node.js 20 이상이 필요합니다.

```bash
npm install
npm run mock   # 터미널 1: 모의 서버 (ws://localhost:8000/ws)
npm run dev    # 터미널 2: 화면 (http://localhost:5173)
```

시작 패널에서 **보조 화면 시작**을 누르면 모의 서버가 샘플 대본(`mock/sample_cues.csv`)으로 아래 순서의 시나리오를 보냅니다.

정상 진행 → 애드리브(#108 뒤) → 누락(#113 건너뜀) → 노래 구간(#115~118) → 반복(#121 다시) → 입력 끊김 → 정상 진행

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `MOCK_PORT` | `8000` | 모의 서버 포트 |
| `MOCK_TICK_MS` | `1500` | 메시지를 보내는 간격 (인식 주기 1~2초 가정) |
| `VITE_ENGINE_URL` | `ws://localhost:8000/ws` | 화면이 연결할 주소. `.env.local`에 적습니다 |

실서버(FastAPI)가 생기면 모의 서버를 끄고 실서버를 8000번 포트로 띄우면 화면은 그대로 동작합니다.

## 구조

```
ui/
├── mock/
│   ├── server.ts          모의 서버 (시나리오대로 메시지 전송)
│   └── sample_cues.csv    직접 만든 샘플 대본 30큐
└── src/
    ├── protocol.ts        WebSocket 메시지 타입 (수행계획서 기준)
    ├── cues.ts            큐 데이터 타입, 큐 CSV 읽기
    ├── settings.ts        화면 기준값 (불확실 기준, 복귀 표시 시간 등)
    ├── useEngine.ts       엔진 연결 훅 (자동 재연결, 받은 메시지 → 화면 상태)
    ├── StartPanel.tsx     임시 시작 패널 (준비 화면으로 교체 예정)
    └── assist/            보조 화면 (수행계획서 그림 4)
        ├── AssistScreen.tsx   화면 배치, ④ 입력 상태, ⑤ 인식 글자
        ├── ScriptList.tsx     ③ 대본 목록, ① 현재 위치·신뢰도
        ├── DeviationCard.tsx  ② 이탈 알림·복귀 큐
        ├── DeviationTimeline.tsx  이번 회차 이탈 기록
        └── EdgeFlash.tsx      화면 가장자리 깜빡임 (이탈·복귀)
```

## 보조 화면 동작

| 상황 | 알림 카드 | 대본 목록 |
|---|---|---|
| 정상 | 대본대로 진행 중 | 추정 위치 줄 강조, 가운데로 따라감 |
| 신뢰도가 기준(0.6) 미만 | 변화 없음 | 강조 줄이 점선, "불확실" |
| 이탈 중 | 빨간 카드: 유형, 경과 시간 | |
| 대본 복귀 | 밝은 카드: 복귀 큐 번호를 크게, 10초 뒤 "최근 복귀" 한 줄로 | 복귀 줄에 "복귀" 표시 |
| 노래 구간 / 입력 없음 | 알림 보류 카드 (노래 구간은 연두색 배지) | 추적을 멈추고 강조 줄을 흐리게 |
| 연결 끊김 / 5초간 메시지 없음 | 회색 카드 + 빨간 점선 테두리: 기존 방식대로 송출 | |

이탈이 시작되면 화면 가장자리가 빨강으로 3번(1.5초) 깜빡인 뒤 얇은 빨간 테두리가 남고, 복귀하면 파랑으로 3번 깜빡입니다. 오퍼레이터가 송출 프로그램을 보고 있어도 곁눈으로 알 수 있게 하기 위해서입니다. 운영체제의 "움직임 줄이기"가 켜져 있으면 깜빡이지 않고 한 번만 천천히 켜졌다 꺼집니다.

이탈 기록에는 이번 회차의 이탈이 최신순으로 남습니다 (시각, 유형, 걸린 시간, 복귀 큐). 회차를 종료하면 지워집니다.

대본 목록을 손으로 스크롤하면 5초 동안 따라가기를 멈추고, "현재 위치로" 버튼이 나옵니다. 기준값은 `src/settings.ts`에 있습니다.

## 메시지

수행계획서 (5) 엔진과 화면 사이 인터페이스를 그대로 따릅니다. 필드가 확정되거나 바뀌면 `src/protocol.ts`만 고치면 됩니다.

| 메시지 | 방향 | 필드 |
|---|---|---|
| `session.start` / `session.end` | 화면 → 엔진 | `show_id`, `cue_file` |
| `settings.update` | 화면 → 엔진 | `alert_threshold` |
| `position.update` | 엔진 → 화면 | `cue_id`, `confidence`, `latency_ms` |
| `deviation.alert` | 엔진 → 화면 | `deviation_type`, `since`, `return_cue_id` |
| `input.status` | 엔진 → 화면 | `audio_level`, `segment` |
| `cue.onair` (2단계) | 송출 프로그램 → 엔진 → 화면 | `cue_id`, `sent_at` |

모든 메시지는 `{"type": "position.update", "cue_id": 845, ...}`처럼 `type`에 메시지 이름을 넣은 JSON 하나입니다.

수행계획서와 다르게 정한 점 (엔진 담당과 맞춰야 함):

- `deviation.alert`의 이탈 유형 필드 이름을 `type` 대신 `deviation_type`으로 했습니다. `type`은 메시지 이름에 쓰기 때문입니다. 값은 `skip`(누락), `repeat`(반복), `adlib`(애드리브)입니다.
- 이탈하면 `return_cue_id: null`로 한 번, 대본으로 돌아오면 같은 `since`에 `return_cue_id`를 채워 한 번 더 보냅니다.
- 시각(`since`, `sent_at`)은 epoch 밀리초입니다.
- `input.status`는 음량 막대를 그려야 해서 모의 서버는 인식 주기마다 보냅니다. `audio_level`이 0이면 입력 없음으로 봅니다.
- 화면은 5초간 메시지가 없으면 "엔진 응답 없음"을 띄웁니다. 그래서 엔진도 `input.status`를 상태가 바뀔 때만이 아니라 주기적으로(1~2초) 보내 줘야 합니다.
- `position.update`에 `transcript`(인식 글자)를 추가했습니다. 수행계획서 화면 설계 ⑤ 인식 글자에는 있지만 메시지 표에는 없던 필드입니다.
- 보조 화면에 대본 목록을 띄우려면 화면도 큐 목록이 필요합니다. 지금은 화면이 큐 CSV를 직접 읽습니다. 엔진이 큐 목록을 보내 줄지 정해야 합니다.

## 큐 CSV (임시)

```
id,order,type,speaker,text
845,845,dialogue,지영,처음부터 다시 얘기해 줄래요?
```

`type`은 `dialogue/lyric/sound/blackout/notice`나 `대사/가사/음향/암전/안내` 둘 다 받습니다. 열 구성은 데이터 담당과 확정되면 `src/cues.ts`의 `CUE_CSV_COLUMNS`를 고칩니다.
