# Src

Helper의 소스 코드를 두는 폴더입니다. 1단계 개발(7\~10주차) 중이며, 엔진·서버·보조 화면의 첫 버전이 들어 있습니다.

## 구조

```
Src/
├── engine/          음성 처리와 대본 추적 (Python)
│   ├── cue_loader       ① 큐 시트 로더 (+ 정규화 · 자모 분해)
│   ├── audio_input      ② 오디오 입력 (지금은 녹음 파일 재생 모드)
│   ├── stt/             ③ 음성인식 (faster-whisper / Google / CLOVA 스트리밍)
│   ├── aligner          ④ 대본 위치 추적
│   ├── deviation        ⑤ 대본 이탈 감지 (1차)
│   ├── protocol         엔진 → 화면 메시지 (ui/src/protocol.ts 와 같은 필드)
│   └── pipeline         ②~⑤ 연결 (재생 · 인식 · 상태 스레드)
├── server/          로컬 서버 (FastAPI, WebSocket ws://localhost:8000/ws)
├── ui/              보조 화면 (React, Vite, TypeScript)
├── tools/           convert_cues.py (큐 CSV → 화면 형식)
└── tests/           테스트 (pytest)
```

⑦ 회차 로그, 마이크 입력, 준비·설정 화면은 아직 없습니다. 2단계 ⑧ 송출 큐 연동과 3단계 ⑨ 자동 전진 제어는 송출 프로그램 연동 방식을 확인한 뒤 추가합니다.

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
| `HELPER_STT` | `whisper`(로컬, 기본) / `google`(chirp_3 3초 조각) / `google_stream`(long 실시간) / `clova_stream` |
| `HELPER_HINTS` | `1`이면 현재 큐 + 다음 3큐를 음성인식에 힌트로 줌 (1차 실험에서 정확도가 가장 크게 오른 방법) |
| `DEVIATE_AFTER_SEC` | 말소리가 이 시간 동안 대본과 안 맞으면 이탈 알림 |

키(Google 서비스 계정 JSON, CLOVA Secret Key)와 공연 데이터는 저장소에 넣지 않습니다. `.env`, `keys/`, `*.wav`는 `.gitignore`에 들어 있습니다.

## 화면과 연결해서 보기

1. 엔진 서버를 켠다 (위). 모의 서버(`npm run mock`)는 끈다 — 같은 8000번 포트를 쓴다.
2. 큐 CSV가 화면 형식(`id, order, type, speaker, text`)이 아니면 바꾼다:
   `python tools/convert_cues.py <원본.csv> <HELPER_DATA_DIR 안의 새 파일.csv>`
3. `cd ui && npm run dev` → http://localhost:5173 → 바꾼 큐 파일을 고르고 **보조 화면 시작**
4. 엔진이 녹음을 실제 시간 속도로 재생하며 위치 · 이탈 알림을 보낸다

## 화면(protocol.ts)과 맞춘 방식 · 팀에서 정할 것

| 항목 | 지금 엔진이 하는 방식 (임시) | 정할 것 |
|---|---|---|
| 큐 CSV 열 | 화면 형식과 1차 데이터 형식(`cue_id, act, scene, type, speaker, text_ko`) 둘 다 읽음 | 열 이름 하나로 통일 |
| 큐 파일 전달 | 화면이 보낸 파일 **이름**을 `HELPER_DATA_DIR`에서 찾음 | 업로드 주소 또는 내용 전송 |
| 이탈 유형 | 이탈 시작 알림은 `adlib`으로 보내고, 복귀 알림에 진짜 유형(skip/repeat/adlib) | 화면에 '미정' 유형 추가 (`engine/deviation.py`의 `START_TYPE`만 바꾸면 됨) |
| 노래 구간 | 현재 위치 큐가 가사면 `segment: "song"`, 노래 구간에서는 이탈 알림을 보내지 않음 | 오퍼레이터가 노래 구간을 지정하는 메시지 |
| 상태 메시지 | `input.status`를 1초마다 보냄 (화면은 5초간 메시지가 없으면 '엔진 응답 없음') | — |
| 신뢰도 | 추적 점수(0~100)를 0~1로 바꿔 보냄 | — |
| 위치 맞추기 | 엔진에는 있음(`Aligner.jump_to`) | 화면 → 엔진 메시지 |
| 오류 알림 | 큐·녹음 파일을 못 찾으면 서버 로그에만 남김 | 오류 메시지 형식 |

## 테스트

```powershell
cd Src
python -m pytest
```

저장소에 있는 샘플 대본(`ui/mock/sample_cues.csv`)과 가짜 음성인식만 써서, 소리 · 키 · 공연 데이터 없이 돈다. `tests/test_protocol.py`는 엔진 메시지 필드가 `ui/src/protocol.ts`와 같은지 확인하므로, 화면 규약이 바뀌면 여기서 먼저 깨진다.

## 올리지 않는 파일

- 공연 대본, 자막 큐 파일, 공연 음원: 제작사 자산이라 저장소에 올리지 않습니다. 테스트에는 직접 만든 예시 큐 파일을 씁니다.
- 음성인식 모델 파일, API 키, 가상환경 폴더
