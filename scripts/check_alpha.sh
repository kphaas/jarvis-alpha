#!/bin/bash
# check_alpha.sh — Alpha health check
# Run from Brain: bash ~/jarvis-alpha/scripts/check_alpha.sh

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ALL_HEALTHY=true

check_service() {
    local node=$1
    local service=$2
    local url=$3
    local ssh_host=$4

    local process_ok=false
    local http_ok=false
    local status="unknown"
    local message=""

    if [[ "$ssh_host" == "local" ]]; then
        launchctl list | grep -q "$service" 2>/dev/null && process_ok=true
    else
        ssh "$ssh_host" "launchctl list | grep -q '$service'" 2>/dev/null && process_ok=true
    fi

    if [[ -n "$url" ]]; then
        http_code=$(curl -sk -o /dev/null -w "%{http_code}" -m 10 "$url" 2>/dev/null)
        [[ "$http_code" == "200" || "$http_code" == "401" ]] && http_ok=true
    fi

    if $process_ok && { $http_ok || [[ -z "$url" ]]; }; then
        status="healthy"
        message="OK"
    elif ! $process_ok; then
        status="down"
        message="Process not running"
        ALL_HEALTHY=false
    else
        status="degraded"
        message="Process running but HTTP unreachable"
        ALL_HEALTHY=false
    fi

    if [[ "$status" == "healthy" ]]; then
        echo -e "${GREEN}✓${NC} $node: $service - $message"
    elif [[ "$status" == "degraded" ]]; then
        echo -e "${YELLOW}⚠${NC} $node: $service - $message"
    else
        echo -e "${RED}✗${NC} $node: $service - $message"
    fi
}

echo "JARVIS Alpha Health Check"
echo "========================="
echo ""

check_service "Brain"    "com.jarvis.alpha.brain"   "https://100.64.166.22:8186/health"   "local"
check_service "Brain"    "com.jarvis.alpha.buddy"   ""                                     "local"
check_service "Brain"    "homebrew.mxcl.postgresql@16" ""                                  "local"
check_service "Brain"    "com.jarvis.ollama"         ""                                     "local"
check_service "Endpoint" "com.jarvis.nginx"          "https://jarvis-endpoint.tail40ed36.ts.net:4100" "jarvisendpoint@100.87.223.31"

echo ""
if $ALL_HEALTHY; then
    echo -e "${GREEN}Alpha Status: HEALTHY${NC}"
    exit 0
else
    echo -e "${RED}Alpha Status: DEGRADED${NC}"
    exit 1
fi
