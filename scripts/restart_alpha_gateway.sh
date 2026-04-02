#!/bin/bash
set -uo pipefail

PORT=8283
HEALTH_URL="https://jarvis-gateway.tail40ed36.ts.net:8283/health"
LOG_DIR="$HOME/jarvis-alpha/logs"
SERVICE_DIR="$HOME/jarvis-alpha"
GATEWAY_PLIST="com.jarvis.alpha.gateway"

spinner() {
    local pid=$1 msg=$2 delay=0.1 i=0
    local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  %s  %s..." "${frames[$((i % ${#frames[@]}))]}" "$msg"
        sleep $delay
        i=$((i + 1))
    done
    printf "\r                                          \r"
}

echo ""
echo "┌─────────────────────────────────────────┐"
echo "│   Alpha Gateway Restart — JARVIS        │"
echo "└─────────────────────────────────────────┘"
echo ""

echo "[1/5] Clearing Python cache..."
find "$SERVICE_DIR/gateway" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo "      Cache cleared"
echo ""

echo "[2/5] Unloading Alpha Gateway..."
launchctl unload ~/Library/LaunchAgents/${GATEWAY_PLIST}.plist 2>/dev/null || true
sleep 2
echo "      Unloaded: $GATEWAY_PLIST"
echo ""

echo "[3/5] Killing stale process on port $PORT..."
pid=$(lsof -ti :$PORT 2>/dev/null) || true
if [ -n "$pid" ]; then
    kill $pid 2>/dev/null && echo "      Killed PID $pid on :$PORT" || true
else
    echo "      No stale process found"
fi
(sleep 3) &
spinner $! "Waiting for port to clear"
echo ""

echo "[4/5] Loading Alpha Gateway..."
launchctl load ~/Library/LaunchAgents/${GATEWAY_PLIST}.plist
echo "      Loaded: $GATEWAY_PLIST"
(sleep 10) &
spinner $! "Waiting for Alpha Gateway to start"
echo ""

echo "[5/5] Health check..."
echo ""
PASS=0
FAIL=0

for i in 1 2 3; do
    result=$(curl -sk --max-time 8 "$HEALTH_URL" 2>/dev/null)
    if echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('status')=='ok' else 1)" 2>/dev/null; then
        echo "  ✓ Alpha Gateway :$PORT — OK"
        echo "$result" | python3 -m json.tool | sed 's/^/    /'
        PASS=$((PASS+1))
        break
    fi
    if [ $i -lt 3 ]; then
        (sleep 5) &
        spinner $! "Not ready, retry $i/3"
    else
        echo "  ✗ Alpha Gateway :$PORT — NOT RESPONDING"
        FAIL=$((FAIL+1))
    fi
done

echo ""
echo "──────────────────────────────────────────"
echo "  Result: $PASS passed · $FAIL failed"
echo ""
launchctl list | grep "com.jarvis.alpha" | awk '{printf "  %-40s PID=%-8s EXIT=%s\n", $3, $1, $2}' || true
echo ""

if [ $FAIL -eq 0 ]; then
    echo "  Alpha Gateway HTTPS OK ✓"
    exit 0
else
    echo "  Alpha Gateway not responding — check $LOG_DIR/alpha_gateway_error.log"
    exit 1
fi
