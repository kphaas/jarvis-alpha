# TLS Certificates in the Security UI

## Purpose

Use the Alpha Security UI to review, renew, and verify Tailscale TLS
certificates for the Alpha service nodes.

Sweep owns this workflow. Warden supervises Sweep and reports certificate
posture in the Security dashboard. Keyturner is for secrets and OAuth
credentials, not service TLS certificates.

## Where to Start

Open:

```text
https://jarvis-endpoint.tail40ed36.ts.net:4100/security
```

Use these tabs:

- **Overview**: posture score, Warden control gaps, shortest certificate state.
- **Sweep**: service TLS certificate inventory and Sweep responsibilities.
- **Warden**: owner routing and weekly security brief context.
- **Porchlight**: read-only security sweep checks after remediation.

## Status Rules

Certificate freshness is scored by days remaining:

| Days remaining | UI status | Action |
|---:|---|---|
| 30 or more | OK / pass | No action needed. |
| 15 to 29 | Warning | Plan renewal. Sweep should handle it. |
| Less than 15 | Fail | Renew and verify health. |

Sweep renewal result values:

| Result | Meaning |
|---|---|
| `ok` | Cert is above the threshold. No renewal was needed. |
| `would_renew` | Dry run says the cert is under the threshold. |
| `renewed` | Cert expiry moved forward and the local service was restarted if needed. |
| `renewal_pending` | Tailscale/ACME already has a replacement order pending. Wait and retry later. |
| `unchanged` | Renewal command returned, but the certificate expiry did not move forward. Treat as not renewed. |
| `error` | Renewal or verification failed. Inspect the node before retrying repeatedly. |

`renewal_pending` and `unchanged` require the Sweep TLS renewal hardening PR to
be merged and deployed. Before that deploy, the dashboard may show a generic
error for the same condition.

## UI Workflow

1. Open **Security > Overview**.
2. Check **Service certificate freshness** in Warden control gaps.
3. Open **Security > Sweep**.
4. Review **Service TLS certificates**.
5. Sort mentally by the lowest **Days** value. Renew the lowest-risk-expiring
   nodes first if multiple nodes are warning or failing.
6. Click **Run now** in the Sweep tab.
7. Wait for the run to finish. Do not click repeatedly while a run is active.
8. Refresh the Security page.
9. Re-open **Security > Sweep** and confirm certificate dates and status.
10. Open **Security > Warden** and confirm the certificate control moved to
    warn or pass.
11. Open **Security > Porchlight** and run a read-only sweep if needed.

## Expected Nodes

| Node | Domain | Service |
|---|---|---|
| Brain | `jarvis-brain.tail40ed36.ts.net` | Alpha Brain API |
| Gateway | `jarvis-gateway.tail40ed36.ts.net` | Alpha Gateway |
| Endpoint | `jarvis-endpoint.tail40ed36.ts.net` | Alpha UI / nginx |
| Sandbox | `jarvis-sandbox.tail40ed36.ts.net` | Sandbox API |

## Manual Fallback

Use the manual fallback only when the UI shows a warning/fail and Sweep cannot
complete the renewal from the dashboard.

Run the node-local command on the node that owns the certificate. Start with a
dry run:

```bash
ssh jarvisbrain@jarvis-brain.tail40ed36.ts.net 'cd ~/jarvis-alpha && python3 scripts/sweep_tls_cert_renewal.py --local --node brain --threshold-days 30 --dry-run --skip-registry'
```

If the dry run reports `would_renew`, run the real renewal:

```bash
ssh jarvisbrain@jarvis-brain.tail40ed36.ts.net 'cd ~/jarvis-alpha && python3 scripts/sweep_tls_cert_renewal.py --local --node brain --threshold-days 30 --skip-registry'
```

Other nodes:

```bash
ssh jarvisendpoint@jarvis-endpoint.tail40ed36.ts.net 'cd ~/jarvis-alpha && python3 scripts/sweep_tls_cert_renewal.py --local --node endpoint --threshold-days 30 --skip-registry'
```

```bash
ssh gate@jarvis-gateway.tail40ed36.ts.net 'cd ~/jarvis-alpha && python3 scripts/sweep_tls_cert_renewal.py --local --node gateway --threshold-days 30 --skip-registry'
```

```bash
ssh jarvissand@jarvis-sandbox.tail40ed36.ts.net 'cd ~/jarvis-alpha && python3 scripts/sweep_tls_cert_renewal.py --local --node sandbox --threshold-days 30 --skip-registry'
```

If node-local renewal used `--skip-registry`, the UI may not show updated
certificate dates until the central registry sync runs.

## Central Sweep Run

After the Sweep TLS renewal hardening is merged and deployed, prefer a central
run from Brain when possible:

```bash
ssh jarvisbrain@jarvis-brain.tail40ed36.ts.net 'cd ~/jarvis-alpha && python3 scripts/sweep_tls_cert_renewal.py --node all --threshold-days 30'
```

Use dry run first if you only want to inspect planned action:

```bash
ssh jarvisbrain@jarvis-brain.tail40ed36.ts.net 'cd ~/jarvis-alpha && python3 scripts/sweep_tls_cert_renewal.py --node all --threshold-days 30 --dry-run'
```

## Health Verification

After any real renewal, verify the affected service:

```bash
curl -sk https://jarvis-brain.tail40ed36.ts.net:8186/health
curl -sk https://jarvis-gateway.tail40ed36.ts.net:8283/health
curl -sk https://jarvis-endpoint.tail40ed36.ts.net:4100
curl -sk https://jarvis-sandbox.tail40ed36.ts.net:5001/api/health
```

If a service fails health after renewal, stop and inspect the LaunchAgent or
service logs before attempting another renewal.

## Do Not

- Do not delete certificate or key files manually.
- Do not edit certificate dates directly in the registry.
- Do not repeatedly retry when Tailscale/ACME reports a pending replacement
  order.
- Do not treat `unchanged` as a successful renewal.
- Do not rotate application secrets with Keyturner for a TLS certificate issue.

## Completion Checklist

- Security > Sweep shows each service certificate.
- The shortest certificate has at least 30 days remaining, or the remaining
  warning is understood as `renewal_pending`.
- Security > Warden no longer shows an unresolved certificate owner gap.
- Security > Porchlight has been re-run after remediation if the posture score
  still shows a security sweep failure.
- A Mattermost security alert was reviewed if Warden or Porchlight reported a
  fail condition.
