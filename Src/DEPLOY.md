# 인터넷 서버로 올리기

테스터가 아무것도 설치하지 않고 브라우저로 Helper를 써 볼 수 있게 올리는 방법입니다. 화면은 Vercel에, 엔진은 WebSocket을 받을 수 있는 서버(Google Cloud Run 또는 Render)에 올립니다.

## 구성

| 부분 | 올리는 곳 | 비고 |
|---|---|---|
| 보조 화면 (`Src/ui`) | Vercel | 빌드한 정적 페이지 |
| 엔진 (`Src/engine`, `Src/server`) | Cloud Run 또는 Render | `Src/Dockerfile`로 만든 이미지 |
| 음성인식 | Google Speech-to-Text V2 (chirp_3) | 엔진이 호출 |

테스터 브라우저가 마이크 소리나 고른 녹음 파일 소리를 16kHz로 바꿔서 0.1초씩 엔진에 보냅니다. 큐 파일도 테스터가 시작 화면에서 고른 CSV 내용을 회차 시작 메시지에 담아 보냅니다. 그래서 서버에는 대본이나 녹음 파일을 미리 둘 필요가 없습니다.

서버는 소리와 큐 파일을 저장하지 않고, 회차 기록도 끕니다(`HELPER_LOG_DIR=off`). 서버 로그에는 공연 이름, 큐 파일 이름, 송출한 큐 번호, 임시 자막 글자, 오류가 남고 인식된 글자와 소리는 남지 않습니다.

## 엔진 설정 값

Dockerfile에 기본값이 들어 있어서 보통은 접속 코드와 프로젝트 ID만 넣으면 됩니다.

| 이름 | 값 | 설명 |
|---|---|---|
| `HELPER_ACCESS_CODE` | 직접 정함 | 화면이 연결할 때 확인하는 코드. 테스터에게만 알려 줌. 비우면 누구나 연결됨 |
| `GOOGLE_CLOUD_PROJECT` | 프로젝트 ID | Speech-to-Text를 켠 Google Cloud 프로젝트 |
| `GOOGLE_APPLICATION_CREDENTIALS` | 키 파일 경로 | Render에서만 씀. Cloud Run은 비워 둠 (서비스 계정이 붙어 있음) |
| `HELPER_STT` | `google` | 기본값 |
| `HELPER_INPUTS` | `browser,text` | 기본값. 서버에 마이크와 녹음이 없으므로 브라우저 소리와 대사 입력만 받음 |
| `HELPER_HOP_SEC` | `1.5` | 기본값. 3초 조각을 1.5초마다 보냄 |
| `HELPER_MAX_SESSION_SEC` | `600` | 기본값. 회차 1번에 10분까지 |
| `HELPER_MAX_SESSIONS` | `3` | 기본값. 동시에 3회차까지 |
| `HELPER_LOG_DIR` | `off` | 기본값. 회차 기록을 남기지 않음 |
| `GOOGLE_STT_HEDGE` | 비움 | `2`로 하면 인식이 느릴 때 빨라지지만 비용이 2배 |

## 엔진 올리기 1. Google Cloud Run (추천)

서울 리전이라 지연이 적고, 키 파일 없이 서비스 계정으로 Speech API를 부릅니다. 접속이 없으면 꺼져 있어서 비용이 거의 들지 않고, 처음 접속할 때 몇 초 기다립니다.

1. [gcloud CLI](https://cloud.google.com/sdk/docs/install)를 설치하고 로그인합니다.

   ```
   gcloud auth login
   gcloud config set project <프로젝트 ID>
   ```

2. 엔진용 서비스 계정을 만들고 음성인식 권한만 줍니다.

   ```
   gcloud iam service-accounts create helper-engine
   gcloud projects add-iam-policy-binding <프로젝트 ID> --member serviceAccount:helper-engine@<프로젝트 ID>.iam.gserviceaccount.com --role roles/speech.client
   ```

3. `Src` 폴더에서 배포합니다. 처음에는 Cloud Build, Artifact Registry API를 켤지 물어보는데 `y`로 답합니다.

   ```
   gcloud run deploy helper-engine --source . --region asia-northeast3 --service-account helper-engine@<프로젝트 ID>.iam.gserviceaccount.com --allow-unauthenticated --timeout 3600 --max-instances 1 --set-env-vars GOOGLE_CLOUD_PROJECT=<프로젝트 ID>,HELPER_ACCESS_CODE=<접속 코드>
   ```

   - `--allow-unauthenticated`: 테스터 브라우저가 바로 연결해야 해서 Google 로그인은 끕니다. 대신 접속 코드로 막습니다.
   - `--timeout 3600`: WebSocket 연결을 최대 1시간 유지합니다 (기본 5분이면 회차 중간에 끊김).
   - `--max-instances 1`: 회차 상태를 서버 메모리에 두기 때문에 서버는 한 대만 띄웁니다.

4. 끝나면 나오는 주소 뒤에 `/health`를 붙여 열어 봅니다. `{"ok":true,"stt":"google","inputs":["browser","text"]}`가 보이면 됩니다. 화면에 넣을 엔진 주소는 `https`를 `wss`로 바꾸고 `/ws`를 붙인 것입니다 (예: `wss://helper-engine-xxxx.asia-northeast3.run.app/ws`).

인식할 때 권한 오류가 나면 2번의 역할을 `roles/speech.editor`로 바꿔 봅니다.

## 엔진 올리기 2. Render

Google Cloud 명령 없이 GitHub 저장소만 연결해서 올립니다. 무료 플랜은 15분 동안 접속이 없으면 잠들고, 다음 접속 때 깨어나는 데 1분쯤 걸립니다. 서버가 싱가포르에 있어서 Cloud Run보다 조금 느립니다.

1. Render에 로그인하고 **New > Blueprint**에서 이 저장소를 고릅니다. 저장소 맨 위의 `render.yaml`을 읽어서 `helper-engine` 서비스를 만듭니다.
2. `HELPER_ACCESS_CODE`와 `GOOGLE_CLOUD_PROJECT` 값을 넣습니다.
3. 서비스의 **Environment > Secret Files**에 `google-key.json` 이름으로 서비스 계정 키 내용을 붙여 넣습니다. 키는 음성인식 권한만 있는 계정으로 새로 만들어 씁니다.
4. **Manual Deploy**로 올리고 `https://helper-engine.onrender.com/health`를 열어 확인합니다 (주소는 Render가 정해 줌). 엔진 주소는 `wss://helper-engine.onrender.com/ws`입니다.

## 화면 올리기 (Vercel)

1. Vercel에 로그인하고 **Add New > Project**에서 이 저장소를 고릅니다.
2. **Root Directory**를 `Src/ui`로 바꿉니다. Vite로 자동 인식되어 빌드 명령(`npm run build`)과 결과 폴더(`dist`)는 그대로 둡니다.
3. **Environment Variables**에 아래 세 개를 넣습니다.

   | 이름 | 값 |
   |---|---|
   | `VITE_ENGINE_URL` | 위에서 확인한 엔진 주소 (`wss://.../ws`) |
   | `VITE_INPUTS` | `browser-file,browser-mic,text` |
   | `VITE_NEED_CODE` | `1` |

4. **Deploy**를 누릅니다. 이 값들은 빌드할 때 들어가므로 나중에 바꾸면 다시 배포해야 합니다.

## 테스터에게 알려 줄 것

- 주소: `https://<화면 주소>/?code=<접속 코드>`. 주소에 코드를 넣어 두면 따로 입력하지 않아도 됩니다.
- 큐 파일: `id, order, type, speaker, text` 열이 있는 CSV (`Src/ui/mock/sample_cues.csv` 참고). 형식이 다르면 `Src/tools/convert_cues.py`로 바꿉니다.
- 내 녹음 파일: wav, mp3, m4a처럼 브라우저가 열 수 있는 파일. 녹음을 틀면서 그 소리로 추적합니다.
- 내 마이크: Chrome이나 Edge에서 처음에 마이크 사용을 허용해야 합니다.
- 회차 1번에 10분까지, 동시에 3명까지 쓸 수 있습니다.

## 비용과 주의할 점

- chirp_3는 보낸 소리 길이로 요금을 매깁니다. 3초 조각을 1.5초마다 보내서 겹치므로 실제 소리의 약 2배가 사용량으로 잡힙니다.
- Google Cloud 콘솔의 **결제 > 예산 및 알림**에서 예산 알림을 걸어 둡니다.
- 테스트 기간이 끝나면 접속 코드를 바꾸거나 서비스를 멈춥니다 (Render는 Suspend, Cloud Run은 서비스 삭제).
- 테스터에게는 자기가 쓸 수 있는 대본과 녹음만 올리도록 안내합니다.

## 올리기 전에 내 컴퓨터에서 확인

`Src/.env`에 아래 값을 적고 엔진을 켭니다 (키 파일 경로와 프로젝트는 원래 쓰던 값).

```
HELPER_STT=google
HELPER_HOP_SEC=1.5
HELPER_INPUTS=browser,text
HELPER_ACCESS_CODE=test
HELPER_MAX_SESSION_SEC=600
HELPER_MAX_SESSIONS=3
HELPER_LOG_DIR=off
```

```
uvicorn server.main:app --port 8000
```

`Src/ui/.env.local`에 아래 값을 적고 `npm run dev`로 화면을 엽니다.

```
VITE_ENGINE_URL=ws://localhost:8000/ws
VITE_INPUTS=browser-file,browser-mic,text
VITE_NEED_CODE=1
```

시작 화면에 접속 코드 `test`를 넣고, 큐 파일과 녹음 파일을 고른 뒤 **내 녹음 파일**로 시작해서 위치가 따라가는지 봅니다.

Docker가 있으면 이미지도 미리 확인할 수 있습니다 (`Src` 폴더에서).

```
docker build -t helper-engine .
docker run -p 8000:8000 -e GOOGLE_CLOUD_PROJECT=<프로젝트 ID> -e GOOGLE_APPLICATION_CREDENTIALS=/key.json -e HELPER_ACCESS_CODE=test -v <키 파일 경로>:/key.json helper-engine
```
