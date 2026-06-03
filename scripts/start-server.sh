#!/bin/bash
# 프로덕션 서버 시작 스크립트 (--reload 없음)
# 사용: bash scripts/start-server.sh

cd "$(dirname "$0")/.." || exit 1

echo "[FastAPI] 시작 중..."
uv run uvicorn app.main:app --port 8000 &
FASTAPI_PID=$!
echo "[FastAPI] PID: $FASTAPI_PID"

echo "[Streamlit] 시작 중..."
uv run streamlit run dashboard/main.py --server.port 8501 &
STREAMLIT_PID=$!
echo "[Streamlit] PID: $STREAMLIT_PID"

echo ""
echo "서버 실행 중"
echo "  FastAPI  → http://localhost:8000"
echo "  Dashboard → http://localhost:8501"
echo ""
echo "종료하려면 Ctrl+C"

trap "kill $FASTAPI_PID $STREAMLIT_PID 2>/dev/null; echo '서버 종료'" SIGINT SIGTERM
wait
