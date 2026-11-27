# Helper 엔진 인터넷 서버. Src 폴더에서 빌드한다:  docker build -t helper-engine .
# 테스터는 브라우저에서 소리를 보내므로(HELPER_INPUTS=browser,text) 서버에 녹음 · 마이크가 없어도 된다.
# 설정 값은 DEPLOY.md 참고. 키 파일은 이미지에 넣지 않는다 (.dockerignore).
# 배포본은 빠른 설정: 2.5초 조각을 1초마다, 같은 요청 2번 (도달이 빠름). 회차 하나가 인식 요청을 분당 120번 써서
# 프로젝트 한도(분당 201번) 안에서는 동시에 1회차만 연다. 3초를 1.5초마다로 돌리려면 HELPER_CHUNK_SEC=3, HELPER_HOP_SEC=1.5, HELPER_MAX_SESSIONS=2
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    HELPER_STT=google \
    HELPER_INPUTS=browser,text \
    HELPER_LOG_DIR=off \
    HELPER_MAX_SESSION_SEC=600 \
    HELPER_CHUNK_SEC=2.5 \n    HELPER_HOP_SEC=1 \n    HELPER_MAX_SESSIONS=1

WORKDIR /app
COPY requirements-server.txt .
RUN pip install -r requirements-server.txt

COPY engine ./engine
COPY server ./server

# Cloud Run · Render 가 PORT 를 정해 준다. 없으면 8000
CMD ["sh", "-c", "exec uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
