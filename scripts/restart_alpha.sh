#!/bin/bash
set -uo pipefail

PORT=8186
HEALTH_URL="https://100.64.166.22:8186/health"
LOG_DIR="/Users/jarvisbrain/jarvis-alpha/logs"
SERVICE_DIR="/Users/jarvisbrain/jarvis-alpha"
BRAIN_PLIST="com.jarvis.alpha.brain"
BUDDY_PLIST="com.jarvis.alpha.buddy"

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
echo "│     Alpha Brain Restart — JARVIS        │"
echo "└─────────────────────────────────────────┘"
echo ""

echo "[1/6] Clearing Python cache..."
find "$SERVICE_DIR/brain" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo "      Cache cleared"
echo ""

echo "[2/6] Unloading Buddy..."
launchctl unload ~/Library/LaunchAgents/${BUDDY_PLIST}.plist 2>/dev/null || true
echo "      Unloaded: $BUDDY_PLIST"
echo ""

echo "[3/6] Unloading Alpha Brain..."
launchctl unload ~/Library/LaunchAgents/${BRAIN_PLIST}.plist 2>/dev/null || true
sleep 2
echo "      Unloaded: $BRAIN_PLIST"
echo ""

echo "[4/6] Killing stale process on port $PORT..."
pid=$(lsof -ti :$PORT 2>/dev/null) || true
if [ -n "$pid" ]; then
    kill $pid 2>/dev/null && echo "      Killed PID $pid on :$PORT" || true
else
    echo "      No stale process found"
fi
(sleep 3) &
spinner $! "Waiting for port to clear"
echo ""

echo "[5/6] Loading Alpha Brain + Buddy..."
launchctl load ~/Library/LaunchAgents/${BRAIN_PLIST}.plist
launchctl load ~/Library/LaunchAgents/${BUDDY_PLIST}.plist
echo "      Loaded: $BRAIN_PLIST + $BUDDY_PLIST"
(sleep 12) &
spinner $! "Waiting for Alpha Brain to start"
echo ""

echo "[6/6] Health check..."
echo ""
PASS=0
FAIL=0

for i in 1 2 3; do
    result=$(curl -sk --max-time 8 "$HEALTH_URL" 2>/dev/null)
    if echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('status')=='ok' else 1)" 2>/dev/null; then
        echo "  ✓ Alpha Brain :$PORT — OK"
        echo "$result" | python3 -m json.tool | sed 's/^/    /'
        PASS=$((PASS+1))
        break
    fi
    if [ $i -lt 3 ]; then
        (sleep 5) &
        spinner $! "Not ready, retry $i/3"
    else
        echo "  ✗ Alpha Brain :$PORT — NOT RESPONDING"
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
    echo "  Alpha Brain HTTPS OK ✓"
    exit 0
else
    echo "  Alpha Brain not responding — check $LOG_DIR/alpha_brain_error.log"
    exit 1
fi
