# Src

Helper의 소스 코드를 두는 폴더입니다. 1단계 개발(7\~10주차) 중이며, 엔진·서버·보조 화면의 첫 버전이 들어 있습니다.

## 구조

```
Src/
├── engine/          음성 처리와 대본 추적 (Python)
│   ├── cue_loader       ① 큐 시트 로더 (+ 정규화 · 자모 분해)
│   ├── audio_input      ② 오디오 입력 (녹음 파일 재생 · 마이크)
│   ├── vad              ② 음성 구간 감지 (Silero VAD, 소리 없는 조각은 음성인식에 안 보냄)
│   ├── stt/             ③ 음성인식 (faster-whisper / Google / CLOVA 스트리밍)
│   ├── aligner          ④ 대본 위치 추적
│   ├── deviation        ⑤ 대본 이탈 감지 (1차)
│   ├── protocol         엔진 → 화면 메시지 (ui/src/protocol.ts 와 같은 필드)
│   └── pipeline         ②~⑤ 연결 (재생 · 인식 · 상태 스레드)
├── server/          로컬 서버 (FastAPI, WebSocket ws://localhost:8000/ws)
├── ui/              보조 화면 (React, Vite, TypeScript)
├── eval/            성능 측정 (정답 라벨로 ±1큐 정확도 · 도달 지연)
├── tools/           convert_cues.py (큐 CSV → 화면 형식)
└── tests/           테스트 (pytest)
```

⑦ 회차 로그, 준비·설정 화면은 아직 없습니다. 2단계 ⑧ 송출 큐 연동과 3단계 ⑨ 자동 전진 제어는 송출 프로그램 연동 방식을 확인한 뒤 추가합니다.

## 개발 환경

- Python 3.11 이상
- Node.js 22.18 이상 (`ui/`의 모의 서버를 `node mock/server.ts`로 바로 실행하기 때문)

## 엔진 · 서버 실행

```powershell
cd Src
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # 데이터 폴더 · 음성인식 엔진 · 키 경로를 채운다
uvicorn server.main:app --port 8000
```

`.env`에서 정하는 것:

| 항목 | 설명 |
|---|---|
| `HELPER_DATA_DIR` | 공연 데이터 폴더 (저장소 밖). 화면에서 고른 큐 파일 이름을 이 폴더에서 찾는다 |
| `HELPER_AUDIO_FILE` | 파일 재생 모드로 틀 녹음. 비우면 큐 파일과 같은 폴더의 첫 `.wav` (16kHz 모노) |
| `HELPER_INPUT` | `file`(녹음 파일 재생, 기본) / `mic`(마이크. 녹음 파일이 필요 없음) |
| `HELPER_MIC_DEVICE` | 마이크 장치 번호 또는 이름 일부. 비우면 기본 장치 (`python -m engine.audio_input --list`로 확인) |
| `HELPER_STT` | `whisper`(로컬, 기본) / `google`(chirp_3 3초 조각) / `google_stream`(long 실시간) / `clova_stream` |
| `HELPER_CHUNK_SEC` / `HELPER_HOP_SEC` | 음성인식에 보내는 조각 길이 / 간격. 간격을 짧게 하면 조각이 겹쳐 반응이 빨라지지만 CPU · API 사용량이 늘어남 |
| `HELPER_STT_WORKERS` | 조각 인식 요청을 동시에 몇 개까지 보낼지. 비우면 엔진 기본값 (whisper 1 · google 3). 인식 한 번이 간격보다 오래 걸려도 (chirp_3 요청당 1~2초, p95 2.2초) 밀리지 않게 겹쳐 보냄 |
| `HELPER_HINTS` | `1`이면 현재 큐 + 다음 3큐를 음성인식에 힌트로 줌 (1차 실험에서 정확도가 가장 크게 오른 방법) |
| `HELPER_VAD` | `1`이면 조용하고 말소리도 없는 조각은 음성인식에 보내지 않음 (조각 방식 엔진만. API 비용 절약 · 무음에서 힌트를 지어내는 것 줄이기) |
| `HELPER_ALIGN` | 위치 추적기 설정 덮어쓰기 (보통은 비워 둠). 쉼표로 여러 개, 예: `ahead=10,lost_window=20`. 이름은 `engine/aligner.py`의 `Aligner` 참고, 틀린 이름이면 회차가 시작되지 않고 서버 로그에 "회차 시작 실패" |
| `DEVIATE_AFTER_SEC` | 말소리가 이 시간 동안 대본과 안 맞으면 이탈 알림 |

키(Google 서비스 계정 JSON, CLOVA Secret Key)와 공연 데이터는 저장소에 넣지 않습니다. `.env`, `keys/`, `*.wav`는 `.gitignore`에 들어 있습니다.

## 화면과 연결해서 보기

1. 엔진 서버를 켠다 (위). 모의 서버(`npm run mock`)는 끈다 — 같은 8000번 포트를 쓴다.
2. 큐 CSV가 화면 형식(`id, order, type, speaker, text`)이 아니면 바꾼다:
   `python tools/convert_cues.py <원본.csv> <HELPER_DATA_DIR 안의 새 파일.csv>`
3. `cd ui && npm run dev` → http://localhost:5173 → 바꾼 큐 파일을 고르고 **보조 화면 시작**
4. 엔진이 녹음을 실제 시간 속도로 재생하며 위치 · 이탈 알림을 보낸다

### 마이크로 실행

```powershell
python -m engine.audio_input --list      # 입력 장치 목록 (* = 기본 장치)
python -m engine.audio_input --test 3    # 3초 받아서 음량 표시 (소리는 저장하지 않음)
```

`.env`에 `HELPER_INPUT=mic`(기본 장치가 아니면 `HELPER_MIC_DEVICE`도)를 적고 서버를 켠 뒤, 위 3번처럼 큐 파일을 골라 시작한다. 녹음 파일 없이 마이크 소리로 추적하고, **회차 종료**까지 계속된다. 마이크는 16kHz 모노로 열고, 장치가 거절하면 장치 기본 주파수로 열어 16kHz로 바꾼다. 최근 60초만 메모리에 두고 저장하지 않는다.

`HELPER_VAD=1`은 Silero VAD(faster-whisper에 들어 있는 ONNX 모델, torch 없이)로 조용하고 말소리도 없는 조각만 건너뛴다. 1차 데이터에서 Silero 기본 설정(문턱 0.5)으로 거르면 음악 위 대사 · 노래를 놓쳐 chirp ±1큐 정확도가 83% → 55%(가사 88% → 38%)로 떨어져서, 문턱을 0.1로 낮추고 −40dBFS보다 큰 조각은 그대로 보낸다 (정확도 그대로, 건너뜀 1~2%: 공연 시작 전 무음).

## 화면(protocol.ts)과 맞춘 방식 · 팀에서 정할 것

| 항목 | 지금 엔진이 하는 방식 (임시) | 정할 것 |
|---|---|---|
| 큐 CSV 열 | 화면 형식과 1차 데이터 형식(`cue_id, act, scene, type, speaker, text_ko`) 둘 다 읽음 | 열 이름 하나로 통일 |
| 큐 파일 전달 | 화면이 보낸 파일 **이름**을 `HELPER_DATA_DIR`에서 찾음 | 업로드 주소 또는 내용 전송 |
| 이탈 유형 | 대본에 없는 말이 `DEVIATE_AFTER_SEC` 이어지면 시작 알림을 `adlib`으로 보내고, 복귀 알림에 진짜 유형(skip/repeat/adlib). 누락(안 들린 대사 2\~6줄을 건너뜀) · 반복(들었던 앞 대사로 되돌아감)은 기다리지 않고 복귀 큐를 채운 알림 하나로 보냄. 감지 상태(정상 · 의심 · 재탐색 · 이탈 · 노래 · 입력 없음)는 엔진 로그에만 남김 | 화면에 '미정' 유형 추가 (`engine/deviation.py`의 `START_TYPE`만 바꾸면 됨), 감지 상태를 화면에 보낼지 |
| 노래 구간 | 현재 위치 큐가 가사면 `segment: "song"`, 노래 구간에서는 이탈 알림을 보내지 않음 | 오퍼레이터가 노래 구간을 지정하는 메시지 |
| 상태 메시지 | `input.status`를 1초마다 보냄 (화면은 5초간 메시지가 없으면 '엔진 응답 없음') | — |
| 신뢰도 | 추적 점수(0~100)를 0~1로 바꿔 보냄 | — |
| 위치 맞추기 | 엔진에는 있음(`Aligner.jump_to`) | 화면 → 엔진 메시지 |
| 오류 알림 | 큐·녹음 파일을 못 찾으면 서버 로그에만 남김 | 오류 메시지 형식 |

## 성능 측정 (eval)

정답 라벨(Audacity 라벨 내보내기: `시작초<TAB>끝초<TAB>큐번호`)로 위치 추적 성능을 잰다. 큐 시트 · 라벨 · 녹음은 저장소 밖 경로로 준다.

```powershell
cd Src
# 실제 음성인식으로 처음부터 (대본 힌트가 추적 위치를 따라 바뀜, 실시간으로 기다리지 않음)
python -m eval.run_eval --cues <큐.csv> --labels <라벨.txt> --audio <녹음.wav> --engine whisper --chunk 3 --save <인식결과.jsonl>
# 실시간: 실제 Pipeline 을 녹음 길이만큼 돌려 화면에 보인 그대로 (처리 시간 · 동시 요청 · 건너뛴 조각까지 반영)
python -m eval.run_eval --cues <큐.csv> --labels <라벨.txt> --audio <녹음.wav> --engine google --hop 1.5 --realtime --workers 3 --save <기록.jsonl>
# 저장해 둔 인식 결과로 추적기만 다시 (몇 초)
python -m eval.run_eval --cues <큐.csv> --labels <라벨.txt> --results <인식결과.jsonl>
# 개선 전 추적기와 비교 / 설정 바꿔 보기
python -m eval.run_eval ... --baseline
python -m eval.run_eval ... --set accept=60 --set small_step=5
```

| 지표 | 뜻 |
|---|---|
| ±1큐 정확도 | 0.5초마다 화면 큐와 정답 큐를 비교, 1칸 이내면 정답 (대사 · 가사 따로도 냄) |
| 도달 지연 | 배우가 큐를 시작한 뒤 화면이 그 큐를 처음 보여 주기까지 (중앙값 · 90%) |
| 못감 | 끝까지 화면에 안 나온 큐 수 |
| 뒤로 · 큰점프 | 화면이 뒤로 가거나 3큐 이상 건너뛴 횟수 |

### 이탈 감지 (eval/deviation_eval.py)

이탈(누락 · 반복 · 애드리브)을 넣은 시험 녹음의 인식 결과를 위치 추적기 + 이탈 감지기에 다시 넣어 본다. 정답 JSON에는 이탈마다 유형 · 시작 시각 · 배우가 대본으로 돌아온 시각 · 복귀 큐를 적는다. 정답을 안 주면 이탈이 없는 녹음으로 보고, 나온 알림을 모두 잘못된 알림으로 센다.

```powershell
python -m eval.deviation_eval --cues <큐.csv> --run <이탈 녹음 인식결과.jsonl> <정답.json> --run <원본 인식결과.jsonl>
python -m eval.deviation_eval ... --baseline                         # 1차 감지기 설정
python -m eval.deviation_eval ... --set deviate_after_sec=3 --aset heard_score=55   # 감지기 / 추적기 설정
```

| 지표 | 뜻 |
|---|---|
| 찾음 · 유형 맞음 | 이탈 시작 \~ 복귀 + 10초 안에 알림이 나옴 / 마지막 알림의 유형이 정답과 같음 |
| 감지 지연 | 이탈 시작 → 첫 알림 (시계는 조각 끝 + 인식에 걸린 시간) |
| 복귀 표시 시간 | 배우가 대본으로 돌아온 시각 → 복귀 알림 (복귀 큐가 정답 ±1큐면 '복귀 큐 맞음') |
| 잘못된 알림 / 10분 | 정답 구간 밖 알림 (같은 since의 시작 · 복귀 알림은 한 건) |

## 테스트

```powershell
cd Src
python -m pytest
```

저장소에 있는 샘플 대본(`ui/mock/sample_cues.csv`)과 가짜 음성인식만 써서, 소리 · 키 · 공연 데이터 없이 돈다. `tests/test_protocol.py`는 엔진 메시지 필드가 `ui/src/protocol.ts`와 같은지 확인하므로, 화면 규약이 바뀌면 여기서 먼저 깨진다.

### 자동 테스트 (GitHub Actions)

PR을 올리거나 main에 합쳐지면 `.github/workflows/test.yml`이 자동으로 돈다. 결과는 PR 화면의 체크(✅ / ❌)와 저장소 **Actions** 탭에서 본다.

| 검사 | 하는 일 |
|---|---|
| 엔진 (pytest) | Python 3.11에 `requirements-test.txt`만 설치하고 `python -m pytest` |
| 화면 (lint · build) | Node 22에서 `npm ci` → `npm run lint` → `npm run build` |

`requirements-test.txt`는 테스트에 필요한 가벼운 패키지만 담는다 (음성인식 라이브러리 제외). 새 테스트가 다른 패키지를 쓰면 여기에도 추가한다.

## 올리지 않는 파일

- 공연 대본, 자막 큐 파일, 공연 음원: 제작사 자산이라 저장소에 올리지 않습니다. 테스트에는 직접 만든 예시 큐 파일을 씁니다.
- 음성인식 모델 파일, API 키, 가상환경 폴더
