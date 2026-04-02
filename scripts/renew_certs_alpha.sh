#!/bin/zsh
# renew_certs_alpha.sh — Tailscale cert renewal for Brain (alpha)
# Same cert as jarvis-core — renews and restarts alpha services

set -euo pipefail

TAILSCALE=/opt/homebrew/bin/tailscale
HOSTNAME=jarvis-brain.tail40ed36.ts.net
CERT_DIR=/Users/jarvisbrain/jarvis/certs
LOG=/Users/jarvisbrain/jarvis-alpha/logs/certrenew.log
DAYS_THRESHOLD=30

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [certrenew-alpha] $*" | tee -a "$LOG"
}

log "=== Cert renewal check — Alpha Brain ==="

EXPIRY=$(/opt/homebrew/opt/openssl@3/bin/openssl x509 \
    -in "$CERT_DIR/brain.crt" \
    -noout -enddate 2>/dev/null | cut -d= -f2)

if [ -z "$EXPIRY" ]; then
    log "ERROR: Cannot read cert expiry from $CERT_DIR/brain.crt"
    exit 1
fi

DAYS_LEFT=$(python3 -c "
from datetime import datetime, timezone
expiry = '$EXPIRY'.strip()
dt = datetime.strptime(expiry, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
now = datetime.now(timezone.utc)
print((dt - now).days)
")

log "Cert expires: $EXPIRY ($DAYS_LEFT days remaining)"

if [ "$DAYS_LEFT" -gt "$DAYS_THRESHOLD" ]; then
    log "No renewal needed — $DAYS_LEFT days remaining"
    exit 0
fi

log "Renewal required — running tailscale cert"
$TAILSCALE cert \
    --cert-file "$CERT_DIR/$HOSTNAME.crt" \
    --key-file "$CERT_DIR/$HOSTNAME.key" \
    "$HOSTNAME"

cp "$CERT_DIR/$HOSTNAME.crt" "$CERT_DIR/brain.crt"
cp "$CERT_DIR/$HOSTNAME.key" "$CERT_DIR/brain.key"
chmod 644 "$CERT_DIR/brain.crt"
chmod 600 "$CERT_DIR/brain.key"

NEW_EXPIRY=$(/opt/homebrew/opt/openssl@3/bin/openssl x509 \
    -in "$CERT_DIR/brain.crt" \
    -noout -enddate | cut -d= -f2)
log "New cert expiry: $NEW_EXPIRY"

log "Restarting Alpha..."
bash /Users/jarvisbrain/jarvis-alpha/scripts/restart_alpha.sh

log "Renewal complete."
