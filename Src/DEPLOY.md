# 인터넷 서버로 올리기

테스터가 아무것도 설치하지 않고 브라우저로 Helper를 써 볼 수 있게 올리는 방법입니다. 화면은 Vercel에, 엔진은 WebSocket을 받을 수 있는 서버(Google Cloud Run 또는 Render)에 올립니다.

## 지금 올라가 있는 것

2026년 11월 17일에 아래 순서대로 올렸습니다.

| 부분 | 주소 | 비고 |
|---|---|---|
| 보조 화면 | https://helper-ui-six.vercel.app | Vercel 프로젝트 `helper-ui` |
| 엔진 | https://helper-engine-353331924752.asia-northeast3.run.app | Cloud Run `helper-engine` (서울), Google Cloud 프로젝트 `helper-ossproj` |

접속 코드는 저장소에 적지 않고 팀 단톡방으로 공유합니다. 테스터에게는 `https://helper-ui-six.vercel.app/?code=<접속 코드>`처럼 코드를 붙인 주소를 보냅니다.

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

서울 리전이라 지연이 적고, 키 파일 없이 서비스 계정으로 Speech API를 부릅니다. 접속이 없으면 서버가 내려가서 비용이 거의 들지 않고, 처음 접속할 때 엔진이 다시 뜨는 데 몇 초 걸립니다. 그동안 화면에는 "연결 중"이 보이다가 저절로 연결됩니다.

아래 명령은 Windows PowerShell 기준입니다. 처음에 프로젝트 ID와 접속 코드를 변수에 넣어 두고 씁니다.

1. [gcloud CLI](https://cloud.google.com/sdk/docs/install?hl=ko)를 설치하고, 터미널을 새로 열어 로그인합니다.

   ```
   gcloud auth login
   $P = "프로젝트ID"
   $CODE = "접속코드"
   gcloud config set project $P
   ```

2. 서비스 계정 두 개를 만들고 각각 필요한 권한만 줍니다 (처음 한 번만).
   - `helper-engine`: 엔진이 실행될 때 쓰는 계정. 음성인식 권한만
   - `helper-build`: 이미지를 만들 때 쓰는 계정. Cloud Run 빌드 권한만

   ```
   gcloud iam service-accounts create helper-engine
   gcloud iam service-accounts create helper-build
   gcloud projects add-iam-policy-binding $P --member "serviceAccount:helper-engine@$P.iam.gserviceaccount.com" --role roles/speech.client --condition=None
   gcloud projects add-iam-policy-binding $P --member "serviceAccount:helper-build@$P.iam.gserviceaccount.com" --role roles/run.builder --condition=None
   ```

   빌드용 계정을 따로 두는 이유: 처음 올릴 때 기본 빌드 계정(Compute Engine 기본 계정)으로는 편집자 권한이 있는데도 "default service account is missing required IAM permissions" 오류로 빌드가 계속 막혔습니다. 빌드용 계정을 따로 지정하니 바로 됐습니다.

3. `Src` 폴더에서 배포합니다. 처음에는 Cloud Run, Cloud Build, Artifact Registry API를 켤지 물어보는데 `y`로 답합니다. 이미지를 만드는 데 몇 분 걸립니다.

   ```
   gcloud run deploy helper-engine --source . --region asia-northeast3 --build-service-account "projects/$P/serviceAccounts/helper-build@$P.iam.gserviceaccount.com" --service-account "helper-engine@$P.iam.gserviceaccount.com" --allow-unauthenticated --timeout 3600 --max-instances 1 --set-env-vars "GOOGLE_CLOUD_PROJECT=$P,HELPER_ACCESS_CODE=$CODE"
   ```

   - `--build-service-account`: 2번에서 만든 빌드용 계정으로 이미지를 만듭니다.
   - `--service-account`: 엔진은 음성인식 권한만 있는 계정으로 실행합니다.
   - `--allow-unauthenticated`: 테스터 브라우저가 바로 연결해야 해서 Google 로그인은 끕니다. 대신 접속 코드로 막습니다.
   - `--timeout 3600`: WebSocket 연결을 최대 1시간 유지합니다 (기본 5분이면 회차 중간에 끊김).
   - `--max-instances 1`: 회차 상태를 서버 메모리에 두기 때문에 서버는 한 대만 띄웁니다.

4. 끝나면 나오는 `Service URL` 뒤에 `/health`를 붙여 열어 봅니다. `{"ok":true,"stt":"google","inputs":["browser","text"]}`가 보이면 됩니다. 화면에 넣을 엔진 주소는 `https`를 `wss`로 바꾸고 `/ws`를 붙인 것입니다 (예: `wss://helper-engine-353331924752.asia-northeast3.run.app/ws`).

## 엔진 올리기 2. Render

Google Cloud 명령 없이 GitHub 저장소만 연결해서 올립니다. 무료 플랜은 15분 동안 접속이 없으면 잠들고, 다음 접속 때 깨어나는 데 1분쯤 걸립니다. 서버가 싱가포르에 있어서 Cloud Run보다 조금 느립니다.

1. Render에 로그인하고 **New > Blueprint**에서 이 저장소를 고릅니다. 저장소 맨 위의 `render.yaml`을 읽어서 `helper-engine` 서비스를 만듭니다.
2. `HELPER_ACCESS_CODE`와 `GOOGLE_CLOUD_PROJECT` 값을 넣습니다.
3. 서비스의 **Environment > Secret Files**에 `google-key.json` 이름으로 서비스 계정 키 내용을 붙여 넣습니다. 키는 음성인식 권한만 있는 계정으로 새로 만들어 씁니다.
4. **Manual Deploy**로 올리고 `https://helper-engine.onrender.com/health`를 열어 확인합니다 (주소는 Render가 정해 줌). 엔진 주소는 `wss://helper-engine.onrender.com/ws`입니다.

## 화면 올리기 (Vercel)

내 컴퓨터의 `Src/ui` 폴더를 Vercel 명령으로 바로 올립니다. 저장소 브랜치와 상관없이 지금 폴더 내용이 올라갑니다.

1. `Src/ui` 폴더에서 로그인합니다. 브라우저가 열리면 Vercel 계정으로 로그인합니다.

   ```
   npx vercel login
   ```

2. Vercel 프로젝트를 만들고 이 폴더와 연결합니다 (처음 한 번만).

   ```
   npx vercel link --yes --project helper-ui
   ```

   이때 `.vercel` 폴더와 `.env.local`(Vercel 토큰)이 생깁니다. 둘 다 `Src/ui/.gitignore`에 들어 있어서 저장소에 올라가지 않습니다.

3. 엔진 주소를 넣어서 배포합니다. 값마다 따옴표를 꼭 붙입니다 (PowerShell이 쉼표에서 값을 나눔).

   ```
   npx vercel deploy --prod --build-env "VITE_ENGINE_URL=wss://<엔진 주소>/ws" --build-env "VITE_INPUTS=browser-file,browser-mic,text" --build-env "VITE_NEED_CODE=1"
   ```

   | 이름 | 값 |
   |---|---|
   | `VITE_ENGINE_URL` | 엔진 주소 (`wss://.../ws`) |
   | `VITE_INPUTS` | 시작 화면에 보일 소리 입력 |
   | `VITE_NEED_CODE` | `1`이면 접속 코드 칸을 보여 줌 |

4. 끝나면 나오는 주소 중 짧은 것(예: `https://helper-ui-six.vercel.app`)이 테스터에게 줄 주소입니다. `npx vercel inspect <배포 주소>`의 Aliases에서도 볼 수 있습니다.

이 값들은 빌드할 때 들어가므로, 엔진 주소가 바뀌면 3번을 다시 실행해야 합니다.

## 다시 올릴 때

- 엔진 코드를 고쳤으면: `Src` 폴더에서 Cloud Run 3번 명령을 그대로 다시 실행합니다. 접속 코드를 바꿀 때도 `$CODE`만 바꿔서 같은 명령을 씁니다.
- 화면 코드를 고쳤으면: `Src/ui` 폴더에서 Vercel 3번 명령을 그대로 다시 실행합니다.
- 올리기 전에 저장소 main을 최신으로 받아 두고, 고친 내용은 PR로 합친 뒤에 올립니다.

## 발표 날 항상 켜 두기

평소에는 쉬다가 켜지는 방식이라 첫 접속 때 몇 초 기다립니다. 시연 중에 기다리지 않으려면 발표 전날 서버를 한 대 켜 둔 채로 바꿉니다.

```
gcloud run services update helper-engine --region asia-northeast3 --min-instances 1
```

발표가 끝나면 `--min-instances 0`으로 되돌립니다. 켜 두는 동안에는 쓰지 않아도 서버 요금이 나갑니다 (하루 몇백 원 정도).

## 테스터에게 알려 줄 것

- 주소: `https://helper-ui-six.vercel.app/?code=<접속 코드>`. 주소에 코드를 넣어 두면 따로 입력하지 않아도 됩니다.
- 큐 파일: `id, order, type, speaker, text` 열이 있는 CSV (`Src/ui/mock/sample_cues.csv` 참고). 형식이 다르면 `Src/tools/convert_cues.py`로 바꿉니다.
- 내 녹음 파일: wav, mp3, m4a처럼 브라우저가 열 수 있는 파일. 녹음을 틀면서 그 소리로 추적합니다.
- 내 마이크: Chrome이나 Edge에서 처음에 마이크 사용을 허용해야 합니다.
- 회차 1번에 10분까지, 동시에 3명까지 쓸 수 있습니다. 녹음이 끝나면 **회차 종료**를 눌러 주세요.

## 비용과 주의할 점

- 화면(Vercel)은 무료 플랜으로 충분합니다.
- 엔진(Cloud Run)은 쉬다가 켜지는 방식이라 테스트 정도는 매달 무료 사용량 안에 들어갑니다. 다만 프로젝트에 결제 계정이 연결되어 있어야 합니다.
- 돈이 실제로 나가는 곳은 음성인식(chirp_3)입니다. 보낸 소리 길이로 요금을 매기는데, 3초 조각을 1.5초마다 보내서 겹치므로 실제 소리의 약 2배가 사용량으로 잡힙니다.
- Google Cloud 콘솔의 **결제 > 예산 및 알림**에서 예산 알림을 걸어 둡니다.
- 배포할 때마다 이미지가 Artifact Registry에 쌓입니다. 무료 저장 용량을 넘으면 지난 이미지를 지웁니다.
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

`Src/ui/.env.development.local`에 아래 값을 적고 `npm run dev`로 화면을 엽니다. 이 파일은 `npm run dev`에서만 읽혀서 Vercel 배포에는 섞이지 않습니다.

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
