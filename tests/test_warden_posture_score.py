from brain.services.warden_posture import build_warden_posture_score


def test_warden_posture_score_is_weighted_and_industry_aligned():
    result = build_warden_posture_score(
        jwt={"total": 10, "passing": 10, "failing": 0},
        rls={"total_tables": 62, "protected_tables": 62, "rls_enabled": 62},
        child={
            "profiles": [{"name": "child"}],
            "overall": "full",
            "recommendation": "Child controls enforced.",
        },
        perimeter={
            "ports": [
                {"reachable": True, "expected": True},
                {"reachable": False, "expected": False},
            ],
            "tailscale": {"active": True, "node_count": 4},
            "cors": {"locked": True},
        },
        certs=[{"days_remaining": 80}],
        keyturner={"counts": {"managed": 2, "healthy": 1, "attention": 1}},
        porchlight={
            "report": {
                "status": "warn",
                "counts": {"checks": 10, "passing": 8},
                "checks": [
                    {
                        "name": "backup_recovery",
                        "status": "pass",
                        "summary": "Latest restore drill passed 1.0h ago.",
                        "metadata": {
                            "age_hours": 1.0,
                            "run_id": "2026-06-05_170000",
                            "source_dump": "jarvis_alpha.dump.gpg",
                            "notification": {"event": "mm_notify_sent"},
                        },
                    }
                ],
            }
        },
        unifi_health={
            "tls": {
                "verification": "ca_cert+public_key_pin",
                "public_key_pin_configured": True,
            }
        },
        crew=[
            {"enabled": True, "status": "active", "needs_attention": False},
            {"enabled": True, "status": "active", "needs_attention": True},
        ],
        honeypot_hits_24h=0,
    )

    assert result["model"] == "warden_alpha_posture_v1"
    assert result["basis"] == "industry_aligned"
    assert result["not_certification"] is True
    assert result["total"] == 108
    assert 0 < result["score"] < 100
    controls = {control["id"]: control for control in result["controls"]}
    assert controls["tls.service_certs"]["owner_agent"] == "sweep"
    assert controls["tls.unifi_cert_pin"]["status"] == "pass"
    assert controls["secrets.key_rotation"]["status"] == "warn"
    assert controls["recovery.restore_drill"]["status"] == "pass"
    assert "notification mm_notify_sent" in controls["recovery.restore_drill"]["detail"]
    assert controls["monitoring.warden_crew"]["status"] == "warn"
    assert controls["monitoring.honeypot"]["owner_agent"] == "tripwire"
    assert result["top_gaps"][0]["status"] != "pass"


def test_warden_posture_score_uses_porchlight_rls_when_inventory_unavailable():
    result = build_warden_posture_score(
        jwt={"total": 1, "passing": 1},
        rls={"total_tables": 0},
        child={"profiles": [{"name": "child"}], "overall": "full"},
        perimeter={
            "ports": [],
            "tailscale": {"active": True, "node_count": 1},
            "cors": {"locked": True},
        },
        certs=[{"days_remaining": 80}],
        keyturner={"counts": {"managed": 1, "healthy": 1, "attention": 0}},
        porchlight={
            "report": {
                "status": "fail",
                "counts": {"checks": 1, "passing": 1},
                "checks": [
                    {
                        "name": "database_rls",
                        "status": "pass",
                        "summary": "RLS and FORCE RLS are enabled on 62 public tables.",
                        "metadata": {"total_tables": 62},
                    },
                    {
                        "name": "backup_recovery",
                        "status": "fail",
                        "summary": "Latest restore drill is stale.",
                        "metadata": {"age_hours": 300},
                    },
                ],
            }
        },
        unifi_health={
            "tls": {
                "verification": "public_key_pin",
                "public_key_pin_configured": True,
            }
        },
        crew=[],
        honeypot_hits_24h=0,
    )

    controls = {control["id"]: control for control in result["controls"]}
    assert controls["data.rls_force"]["status"] == "pass"
    assert controls["data.rls_force"]["earned"] == 14
    assert controls["data.rls_force"]["summary"] == "62/62 public tables protected"
    assert "Direct RLS inventory unavailable" in controls["data.rls_force"]["detail"]
    assert controls["recovery.restore_drill"]["status"] == "fail"
