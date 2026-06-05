"""Warden-owned security posture scoring.

The score is intentionally industry-aligned, not certification-grade. It maps
Alpha controls to SOC 2, CIS, and NIST categories while preserving local
ownership and operational detail.
"""

from __future__ import annotations

from typing import Any


def posture_control(
    *,
    control_id: str,
    title: str,
    category: str,
    owner_agent: str,
    status: str,
    weight: int,
    summary: str,
    detail: str = "",
    framework_refs: tuple[str, ...] = (),
    earned: float | None = None,
) -> dict[str, Any]:
    if earned is None:
        if status == "pass":
            earned = float(weight)
        elif status == "warn":
            earned = float(weight) * 0.5
        else:
            earned = 0.0
    earned = max(0.0, min(float(weight), float(earned)))
    return {
        "id": control_id,
        "title": title,
        "category": category,
        "owner_agent": owner_agent,
        "status": status,
        "weight": weight,
        "earned": round(earned, 1),
        "summary": summary,
        "detail": detail,
        "framework_refs": list(framework_refs),
    }


def fraction_status(passing: int, total: int) -> str:
    if total <= 0:
        return "unavailable"
    if passing == total:
        return "pass"
    if passing > 0:
        return "warn"
    return "fail"


def cert_control_status(certs: list[dict] | None) -> tuple[str, float, str]:
    if not certs:
        return "unavailable", 0.0, "Certificate inventory is unavailable."
    days = [int(cert.get("days_remaining") or 0) for cert in certs]
    shortest = min(days)
    if shortest < 15:
        return "fail", 0.0, f"Shortest service certificate expires in {shortest} days."
    if shortest < 30:
        return "warn", 0.5, f"Shortest service certificate expires in {shortest} days."
    return "pass", 1.0, f"Shortest service certificate has {shortest} days remaining."


def _porchlight_check(report: dict[str, Any], name: str) -> dict[str, Any] | None:
    checks = report.get("checks")
    if not isinstance(checks, list):
        return None
    for check in checks:
        if isinstance(check, dict) and check.get("name") == name:
            return check
    return None


def _rls_control_from_direct_inventory(rls: dict | None) -> dict[str, Any] | None:
    rls_total = int((rls or {}).get("total_tables") or 0)
    if rls_total <= 0:
        return None
    rls_protected = int(
        (rls or {}).get("protected_tables") or (rls or {}).get("rls_enabled") or 0
    )
    return posture_control(
        control_id="data.rls_force",
        title="Database RLS + FORCE coverage",
        category="Data protection",
        owner_agent="porchlight",
        status=fraction_status(rls_protected, rls_total),
        weight=14,
        earned=rls_protected / rls_total * 14,
        summary=f"{rls_protected}/{rls_total} public tables protected",
        framework_refs=("SOC2 CC6.6", "CIS v8 IG1 3"),
    )


def _rls_control_from_porchlight(porchlight: dict | None) -> dict[str, Any]:
    report = (porchlight or {}).get("report") or {}
    check = _porchlight_check(report, "database_rls") or {}
    status = str(check.get("status") or "unavailable")
    metadata = check.get("metadata") if isinstance(check.get("metadata"), dict) else {}
    total = int(metadata.get("total_tables") or metadata.get("tables") or 0)
    protected = int(metadata.get("protected_tables") or metadata.get("force_rls") or 0)
    if status == "pass" and total > 0 and protected == 0:
        protected = total
    if total > 0:
        summary = f"{protected}/{total} public tables protected"
        earned = protected / total * 14
    else:
        summary = str(
            check.get("summary") or check.get("detail") or "RLS inventory unavailable"
        )
        earned = 14.0 if status == "pass" else None
    return posture_control(
        control_id="data.rls_force",
        title="Database RLS + FORCE coverage",
        category="Data protection",
        owner_agent="porchlight",
        status=status if status in {"pass", "warn", "fail"} else "unavailable",
        weight=14,
        earned=earned,
        summary=summary,
        detail="Direct RLS inventory unavailable; using latest Porchlight database_rls check.",
        framework_refs=("SOC2 CC6.6", "CIS v8 IG1 3"),
    )


def _backup_recovery_control_from_porchlight(porchlight: dict | None) -> dict[str, Any]:
    report = (porchlight or {}).get("report") or {}
    check = _porchlight_check(report, "backup_recovery") or {}
    status = str(check.get("status") or "unavailable")
    metadata = check.get("metadata") if isinstance(check.get("metadata"), dict) else {}
    age_hours = metadata.get("age_hours")
    notification = metadata.get("notification")
    notify_event = (
        notification.get("event")
        if isinstance(notification, dict)
        else metadata.get("notification_event")
    )
    if status == "pass" and isinstance(age_hours, (float, int)):
        summary = f"Latest restore drill passed {float(age_hours):.1f}h ago"
    else:
        summary = str(
            check.get("summary")
            or check.get("detail")
            or "Restore-drill proof unavailable"
        )
    detail_parts = []
    if metadata.get("run_id"):
        detail_parts.append(f"run {metadata['run_id']}")
    if metadata.get("source_dump"):
        detail_parts.append(f"source {metadata['source_dump']}")
    if notify_event:
        detail_parts.append(f"notification {notify_event}")
    detail = "; ".join(detail_parts) or str(check.get("detail") or "")
    return posture_control(
        control_id="recovery.restore_drill",
        title="Backup restore drill freshness",
        category="Recovery readiness",
        owner_agent="porchlight",
        status=status if status in {"pass", "warn", "fail"} else "unavailable",
        weight=8,
        summary=summary,
        detail=detail,
        framework_refs=("SOC2 CC7.4", "CIS v8 IG1 11", "NIST CSF RC.RP"),
    )


def build_warden_posture_score(
    *,
    jwt: dict | None,
    rls: dict | None,
    child: dict | None,
    perimeter: dict | None,
    certs: list[dict] | None,
    keyturner: dict | None,
    porchlight: dict | None,
    unifi_health: dict | None,
    crew: list[dict],
    honeypot_hits_24h: int,
) -> dict[str, Any]:
    controls: list[dict[str, Any]] = []

    jwt_total = int((jwt or {}).get("total") or 0)
    jwt_passing = int((jwt or {}).get("passing") or 0)
    controls.append(
        posture_control(
            control_id="identity.jwt_route_auth",
            title="Authenticated route coverage",
            category="Identity and access",
            owner_agent="warden",
            status=fraction_status(jwt_passing, jwt_total),
            weight=10,
            earned=(jwt_passing / jwt_total * 10) if jwt_total else 0,
            summary=f"{jwt_passing}/{jwt_total} route checks passing"
            if jwt_total
            else "JWT route checks unavailable",
            framework_refs=("SOC2 CC6.1", "CIS v8 IG1 6"),
        )
    )

    controls.append(
        _rls_control_from_direct_inventory(rls)
        or _rls_control_from_porchlight(porchlight)
    )

    child_payload = child or {}
    child_status = "pass" if child_payload.get("overall") == "full" else "fail"
    if not child_payload.get("profiles"):
        child_status = "unavailable"
    controls.append(
        posture_control(
            control_id="data.child_isolation",
            title="Child profile isolation",
            category="Data protection",
            owner_agent="porchlight",
            status=child_status,
            weight=10,
            summary=child_payload.get("recommendation")
            or "Child profile controls unavailable",
            framework_refs=("SOC2 CC6.1", "SOC2 CC6.6", "NIST CSF PR.AA"),
        )
    )

    ports = (perimeter or {}).get("ports") or []
    ports_passing = sum(
        1 for port in ports if port.get("reachable") == port.get("expected")
    )
    controls.append(
        posture_control(
            control_id="network.expected_ports",
            title="Expected network exposure",
            category="Network perimeter",
            owner_agent="sweep",
            status=fraction_status(ports_passing, len(ports)),
            weight=8,
            earned=(ports_passing / len(ports) * 8) if ports else 0,
            summary=f"{ports_passing}/{len(ports)} port checks match expected state"
            if ports
            else "Port posture unavailable",
            framework_refs=("SOC2 CC6.7", "CIS v8 IG1 12"),
        )
    )

    tailscale = (perimeter or {}).get("tailscale") or {}
    controls.append(
        posture_control(
            control_id="network.tailscale_mesh",
            title="Private mesh active",
            category="Network perimeter",
            owner_agent="sweep",
            status="pass" if tailscale.get("active") else "fail",
            weight=6,
            summary=f"{tailscale.get('node_count', 0)} Tailscale node(s) visible",
            framework_refs=("SOC2 CC6.7", "NIST CSF PR.AA"),
        )
    )

    cors = (perimeter or {}).get("cors") or {}
    controls.append(
        posture_control(
            control_id="network.cors_locked",
            title="CORS locked to known origins",
            category="Network perimeter",
            owner_agent="sweep",
            status="pass" if cors.get("locked") else "fail",
            weight=6,
            summary="CORS is locked" if cors.get("locked") else "CORS is not locked",
            framework_refs=("SOC2 CC6.7", "CIS v8 IG1 4"),
        )
    )

    cert_status, cert_fraction, cert_summary = cert_control_status(certs)
    controls.append(
        posture_control(
            control_id="tls.service_certs",
            title="Service certificate freshness",
            category="TLS and certificates",
            owner_agent="sweep",
            status=cert_status,
            weight=8,
            earned=cert_fraction * 8,
            summary=cert_summary,
            framework_refs=("SOC2 CC6.7", "CIS v8 IG1 4"),
        )
    )

    unifi_tls = (unifi_health or {}).get("tls") or {}
    unifi_pinned = bool(unifi_tls.get("public_key_pin_configured"))
    unifi_verified = "public_key_pin" in str(unifi_tls.get("verification") or "")
    controls.append(
        posture_control(
            control_id="tls.unifi_cert_pin",
            title="UniFi certificate pinning",
            category="TLS and certificates",
            owner_agent="sweep",
            status="pass" if unifi_pinned and unifi_verified else "fail",
            weight=8,
            summary=(
                "UniFi TLS is verified with public-key pinning"
                if unifi_pinned and unifi_verified
                else "UniFi TLS pinning is not confirmed"
            ),
            framework_refs=("SOC2 CC6.7", "NIST CSF PR.DS"),
        )
    )

    kt_counts = (keyturner or {}).get("counts") or {}
    kt_managed = int(kt_counts.get("managed") or 0)
    kt_healthy = int(kt_counts.get("healthy") or 0)
    kt_attention = int(kt_counts.get("attention") or 0)
    controls.append(
        posture_control(
            control_id="secrets.key_rotation",
            title="Managed key rotation",
            category="Secrets and rotation",
            owner_agent="keyturner",
            status="pass"
            if kt_managed and kt_attention == 0
            else "warn"
            if kt_managed
            else "unavailable",
            weight=12,
            earned=(kt_healthy / kt_managed * 12) if kt_managed else 0,
            summary=f"{kt_healthy}/{kt_managed} managed secrets healthy"
            if kt_managed
            else "Keyturner inventory unavailable",
            framework_refs=("SOC2 CC6.1", "SOC2 CC6.6", "CIS v8 IG1 6"),
        )
    )

    report = (porchlight or {}).get("report") or {}
    report_counts = report.get("counts") or {}
    report_checks = int(report_counts.get("checks") or 0)
    report_passing = int(report_counts.get("passing") or 0)
    report_status = str(report.get("status") or "unavailable")
    controls.append(
        posture_control(
            control_id="monitoring.porchlight_sweep",
            title="Security sweep health",
            category="Monitoring and response",
            owner_agent="porchlight",
            status="pass"
            if report_status == "pass"
            else "warn"
            if report_status == "warn"
            else "fail"
            if report_status == "fail"
            else "unavailable",
            weight=8,
            earned=(report_passing / report_checks * 8) if report_checks else 0,
            summary=f"{report_passing}/{report_checks} Porchlight checks passing"
            if report_checks
            else "Porchlight report unavailable",
            framework_refs=("SOC2 CC7.2", "NIST CSF DE.CM"),
        )
    )

    controls.append(_backup_recovery_control_from_porchlight(porchlight))

    crew_healthy = sum(
        1
        for agent in crew
        if agent.get("enabled")
        and agent.get("status") == "active"
        and not agent.get("needs_attention")
    )
    controls.append(
        posture_control(
            control_id="monitoring.warden_crew",
            title="Security agent crew health",
            category="Monitoring and response",
            owner_agent="warden",
            status=fraction_status(crew_healthy, len(crew)),
            weight=6,
            earned=(crew_healthy / len(crew) * 6) if crew else 0,
            summary=f"{crew_healthy}/{len(crew)} managed security agents healthy"
            if crew
            else "No managed agents registered",
            framework_refs=("SOC2 CC7.2", "NIST CSF GV.RM"),
        )
    )

    if honeypot_hits_24h == 0:
        honeypot_status = "pass"
        honeypot_earned = 4
    elif honeypot_hits_24h <= 5:
        honeypot_status = "warn"
        honeypot_earned = 2
    else:
        honeypot_status = "fail"
        honeypot_earned = 0
    controls.append(
        posture_control(
            control_id="monitoring.honeypot",
            title="Tripwire honeypot activity",
            category="Monitoring and response",
            owner_agent="tripwire",
            status=honeypot_status,
            weight=4,
            earned=honeypot_earned,
            summary=f"{honeypot_hits_24h} honeypot hit(s) in the last 24h",
            framework_refs=("SOC2 CC7.2", "NIST CSF DE.CM"),
        )
    )

    earned = round(sum(control["earned"] for control in controls), 1)
    total = sum(int(control["weight"]) for control in controls)
    score = round((earned / total) * 100) if total else 0
    return {
        "model": "warden_alpha_posture_v1",
        "basis": "industry_aligned",
        "not_certification": True,
        "industry_alignment": [
            "SOC 2 Trust Services Criteria CC6/CC7",
            "CIS Controls v8 IG1",
            "NIST Cybersecurity Framework 2.0",
        ],
        "score": score,
        "earned": earned,
        "total": total,
        "reserved": 0,
        "controls_passing": sum(
            1 for control in controls if control["status"] == "pass"
        ),
        "controls_total": len(controls),
        "controls": controls,
        "top_gaps": [
            control
            for control in sorted(
                controls,
                key=lambda item: (
                    item["status"] == "pass",
                    -int(item["weight"]),
                    item["id"],
                ),
            )
            if control["status"] != "pass"
        ][:4],
    }
