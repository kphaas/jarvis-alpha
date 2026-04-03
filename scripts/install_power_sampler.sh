#!/bin/bash
set -e

NODE=${JARVIS_NODE_NAME:-$(hostname)}
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$HOME/jarvis-alpha/logs"

if [[ "$NODE" == "Brain" ]] || [[ "$NODE" == *"jarvis-brain"* ]]; then
  PLIST="$HOME/jarvis-alpha/scripts/power_sampler_brain.plist"
  LABEL="com.jarvis.alpha.power.brain"
elif [[ "$NODE" == "Gateway" ]] || [[ "$NODE" == *"jarvis-gateway"* ]]; then
  PLIST="$HOME/jarvis-alpha/scripts/power_sampler_gateway.plist"
  LABEL="com.jarvis.alpha.power.gateway"
elif [[ "$NODE" == "Endpoint" ]] || [[ "$NODE" == *"jarvis-endpoint"* ]]; then
  PLIST="$HOME/jarvis-alpha/scripts/power_sampler_endpoint.plist"
  LABEL="com.jarvis.alpha.power.endpoint"
elif [[ "$NODE" == "Sandbox" ]] || [[ "$NODE" == *"sandbox"* ]] || [[ "$NODE" == *"jarvissand"* ]]; then
  PLIST="$HOME/jarvis-alpha/scripts/power_sampler_sandbox.plist"
  LABEL="com.jarvis.alpha.power.sandbox"
else
  echo "Unknown node: $NODE — set JARVIS_NODE_NAME env var"
  exit 1
fi

cp "$PLIST" "$LAUNCH_AGENTS_DIR/"
launchctl unload "$LAUNCH_AGENTS_DIR/$(basename $PLIST)" 2>/dev/null || true
launchctl load "$LAUNCH_AGENTS_DIR/$(basename $PLIST)"
echo "Installed and started: $LABEL"
launchctl list | grep "jarvis.alpha.power"
