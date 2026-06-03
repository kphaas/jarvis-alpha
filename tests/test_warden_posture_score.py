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
    assert result["total"] == 100
    assert 0 < result["score"] < 100
    controls = {control["id"]: control for control in result["controls"]}
    assert controls["tls.unifi_cert_pin"]["status"] == "pass"
    assert controls["secrets.key_rotation"]["status"] == "warn"
    assert controls["monitoring.warden_crew"]["status"] == "warn"
    assert result["top_gaps"][0]["status"] != "pass"
