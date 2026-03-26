#!/bin/bash

# 스크립트 위치 기준으로 프로젝트 루트 찾기
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# .env 파일 로드
set -a
source "$PROJECT_DIR/.env"
set +a

echo "🚀 Cloudflare 터널 시작 중..."

# 기존 cloudflared 프로세스 종료
EXISTING_PID=$(pgrep -f "cloudflared tunnel")
if [ -n "$EXISTING_PID" ]; then
    echo "기존 터널 종료 중... (PID: $EXISTING_PID)"
    kill $EXISTING_PID
    sleep 2
fi

# 로그 파일 초기화
> /tmp/cloudflared.log

# cloudflared 백그라운드 실행
cloudflared tunnel --url http://localhost:8000 --logfile /tmp/cloudflared.log 2>&1 &
CLOUDFLARED_PID=$!

echo "터널 연결 대기 중..."

# URL 나올 때까지 대기 (최대 30초)
TUNNEL_URL=""
for i in $(seq 1 30); do
    sleep 1
    TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' /tmp/cloudflared.log | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
    echo -n "."
done

echo ""

if [ -z "$TUNNEL_URL" ]; then
    echo "❌ 터널 URL을 가져오지 못했어요."
    cat /tmp/cloudflared.log
    exit 1
fi

echo "✅ 터널 URL: $TUNNEL_URL"

# 클립보드에 복사 (macOS)
echo "$TUNNEL_URL" | pbcopy
echo "📋 클립보드에 복사됐어요!"

# Callback URL 설정
CALLBACK_URL="${TUNNEL_URL}/webhook/strava"
echo "👉 Callback URL: $CALLBACK_URL"

echo ""

# 기존 구독 ID 동적으로 가져오기
echo "기존 Webhook 구독 확인 중..."
SUBSCRIPTION=$(curl -s -G https://www.strava.com/api/v3/push_subscriptions \
  -d client_id=$STRAVA_CLIENT_ID \
  -d client_secret=$STRAVA_CLIENT_SECRET)

SUBSCRIPTION_ID=$(echo $SUBSCRIPTION | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data[0]['id']) if data else print('')
")

# 기존 구독 삭제
if [ -n "$SUBSCRIPTION_ID" ]; then
    echo "기존 구독 삭제 중... (ID: $SUBSCRIPTION_ID)"
    curl -s -X DELETE "https://www.strava.com/api/v3/push_subscriptions/$SUBSCRIPTION_ID?client_id=$STRAVA_CLIENT_ID&client_secret=$STRAVA_CLIENT_SECRET"
    echo ""
    sleep 1
else
    echo "기존 구독 없음, 바로 등록할게요."
fi

# 새 URL로 Webhook 재등록
echo "새 URL로 Webhook 재등록 중..."
RESULT=$(curl -s -X POST https://www.strava.com/api/v3/push_subscriptions \
  -F client_id=$STRAVA_CLIENT_ID \
  -F client_secret=$STRAVA_CLIENT_SECRET \
  -F callback_url=$CALLBACK_URL \
  -F verify_token=$STRAVA_WEBHOOK_VERIFY_TOKEN)

echo $RESULT

NEW_ID=$(echo $RESULT | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('id', '실패'))
")

echo ""
echo "✅ 모든 설정 완료!"
echo "📡 터널 URL: $TUNNEL_URL"
echo "🔗 Webhook ID: $NEW_ID"
echo "🔧 터널 PID: $CLOUDFLARED_PID"
echo ""
echo "터널 종료하려면: kill $CLOUDFLARED_PID"