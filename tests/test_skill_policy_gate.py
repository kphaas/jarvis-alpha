from decimal import Decimal

import pytest

from brain.skills.policy_gate import SkillInvocation, SkillPolicyGate


def _agent(**overrides):
    row = {
        "agent_id": "network_watchdog",
        "status": "active",
        "enabled": True,
        "allowed_skills": ["unifi.wan_status"],
        "allowed_scopes": ["network.read"],
        "cost_daily_cap_usd": Decimal("0"),
    }
    row.update(overrides)
    return row


def _skill(**overrides):
    row = {
        "skill_name": "unifi.wan_status",
        "domain": "unifi",
        "approval_tier": "T1",
        "scope": "network.read",
        "status": "active",
        "mutates_state": False,
        "body_access": False,
        "idempotency_required": False,
        "metadata": {},
    }
    row.update(overrides)
    return row


def _decision(invocation=None, agent=None, skill=None, spent=Decimal("0")):
    gate = SkillPolicyGate()
    return gate.evaluate_rows(
        invocation=invocation
        or SkillInvocation(agent_id="network_watchdog", skill_name="unifi.wan_status"),
        agent_row=agent if agent is not None else _agent(),
        skill_row=skill if skill is not None else _skill(),
        spent_today_usd=spent,
    )


def test_allows_active_agent_to_call_allowlisted_t1_skill():
    decision = _decision()

    assert decision.allowed
    assert decision.reason == "policy_ok"


def test_denies_disabled_agent():
    decision = _decision(agent=_agent(enabled=False))

    assert decision.outcome == "deny"
    assert decision.reason == "agent_disabled"


def test_denies_planned_skill_until_adapter_is_active():
    decision = _decision(skill=_skill(status="planned"))

    assert decision.outcome == "deny"
    assert decision.reason == "skill_not_active"


def test_denies_enabled_agent_until_status_is_active():
    decision = _decision(agent=_agent(status="planned", enabled=True))

    assert decision.outcome == "deny"
    assert decision.reason == "agent_not_active"


def test_denies_skill_not_allowlisted_for_agent():
    invocation = SkillInvocation(
        agent_id="network_watchdog",
        skill_name="unifi.daughters_screentime",
        idempotency_key="abc",
    )
    decision = _decision(
        invocation=invocation,
        skill=_skill(
            skill_name="unifi.daughters_screentime",
            approval_tier="T4",
            mutates_state=True,
            idempotency_required=True,
        ),
    )

    assert decision.outcome == "deny"
    assert decision.reason == "skill_not_allowed_for_agent"


def test_denies_scope_not_allowlisted_for_agent():
    decision = _decision(skill=_skill(scope="network.firewall"))

    assert decision.outcome == "deny"
    assert decision.reason == "scope_not_allowed_for_agent"


def test_denies_body_access_without_body_scope():
    invocation = SkillInvocation(
        agent_id="inbox_watcher",
        skill_name="gmail.read_thread",
        body_access=True,
    )
    agent = _agent(
        agent_id="inbox_watcher",
        allowed_skills=["gmail.read_thread"],
        allowed_scopes=["email.read"],
        cost_daily_cap_usd=Decimal("0.50"),
    )
    skill = _skill(
        skill_name="gmail.read_thread",
        domain="gmail",
        scope="email.read",
        body_access=True,
    )

    decision = _decision(invocation=invocation, agent=agent, skill=skill)

    assert decision.outcome == "deny"
    assert decision.reason == "body_scope_not_allowed_for_agent"
    assert decision.body_scope == "email.body.read"


def test_allows_body_access_with_body_scope():
    invocation = SkillInvocation(
        agent_id="inbox_watcher",
        skill_name="gmail.read_thread",
        body_access=True,
    )
    agent = _agent(
        agent_id="inbox_watcher",
        allowed_skills=["gmail.read_thread"],
        allowed_scopes=["email.read", "email.body.read"],
        cost_daily_cap_usd=Decimal("0.50"),
    )
    skill = _skill(
        skill_name="gmail.read_thread",
        domain="gmail",
        scope="email.read",
        body_access=True,
    )

    decision = _decision(invocation=invocation, agent=agent, skill=skill)

    assert decision.allowed


def test_denies_mutating_skill_without_idempotency_key():
    invocation = SkillInvocation(
        agent_id="network_watchdog",
        skill_name="unifi.daughters_screentime",
    )
    agent = _agent(
        allowed_skills=["unifi.daughters_screentime"],
        allowed_scopes=["network.screentime"],
    )
    skill = _skill(
        skill_name="unifi.daughters_screentime",
        approval_tier="T4",
        scope="network.screentime",
        mutates_state=True,
        idempotency_required=True,
    )

    decision = _decision(invocation=invocation, agent=agent, skill=skill)

    assert decision.outcome == "deny"
    assert decision.reason == "idempotency_key_required"


def test_t4_skill_requires_approval_before_allowing():
    invocation = SkillInvocation(
        agent_id="network_watchdog",
        skill_name="unifi.daughters_screentime",
        idempotency_key="abc",
    )
    agent = _agent(
        allowed_skills=["unifi.daughters_screentime"],
        allowed_scopes=["network.screentime"],
    )
    skill = _skill(
        skill_name="unifi.daughters_screentime",
        approval_tier="T4",
        scope="network.screentime",
        mutates_state=True,
        idempotency_required=True,
    )

    decision = _decision(invocation=invocation, agent=agent, skill=skill)

    assert decision.requires_approval
    assert decision.reason == "t4_approval_required"


def test_t4_skill_allows_after_approval_granted():
    invocation = SkillInvocation(
        agent_id="network_watchdog",
        skill_name="unifi.daughters_screentime",
        idempotency_key="abc",
        approval_granted=True,
    )
    agent = _agent(
        allowed_skills=["unifi.daughters_screentime"],
        allowed_scopes=["network.screentime"],
    )
    skill = _skill(
        skill_name="unifi.daughters_screentime",
        approval_tier="T4",
        scope="network.screentime",
        mutates_state=True,
        idempotency_required=True,
    )

    decision = _decision(invocation=invocation, agent=agent, skill=skill)

    assert decision.allowed


def test_denies_when_estimated_cost_exceeds_daily_agent_cap():
    invocation = SkillInvocation(
        agent_id="inbox_watcher",
        skill_name="gmail.search_threads",
        estimated_cost_usd=Decimal("0.11"),
    )
    agent = _agent(
        agent_id="inbox_watcher",
        allowed_skills=["gmail.search_threads"],
        allowed_scopes=["email.read"],
        cost_daily_cap_usd=Decimal("0.50"),
    )
    skill = _skill(
        skill_name="gmail.search_threads",
        domain="gmail",
        scope="email.read",
    )

    decision = _decision(
        invocation=invocation,
        agent=agent,
        skill=skill,
        spent=Decimal("0.40"),
    )

    assert decision.outcome == "deny"
    assert decision.reason == "cost_cap_exceeded"


def test_denies_negative_estimated_cost():
    invocation = SkillInvocation(
        agent_id="network_watchdog",
        skill_name="unifi.wan_status",
        estimated_cost_usd=Decimal("-0.01"),
    )

    decision = _decision(invocation=invocation)

    assert decision.outcome == "deny"
    assert decision.reason == "invalid_estimated_cost"


@pytest.mark.asyncio
async def test_evaluate_fetches_registry_rows_and_agent_spend():
    class FakeConn:
        def __init__(self):
            self.queries = []

        async def fetchrow(self, query, *args):
            self.queries.append((query, args))
            if "FROM public.alpha_agents" in query:
                return _agent(cost_daily_cap_usd=Decimal("1.00"))
            if "FROM public.alpha_skill_registry" in query:
                return _skill()
            if "FROM public.alpha_agent_runs" in query:
                return {"spent_usd": Decimal("0.25")}
            raise AssertionError(query)

    conn = FakeConn()

    decision = await SkillPolicyGate().evaluate(
        conn,
        SkillInvocation(
            agent_id="network_watchdog",
            skill_name="unifi.wan_status",
            estimated_cost_usd=Decimal("0.10"),
        ),
    )

    assert decision.allowed
    assert decision.cost_spent_today_usd == Decimal("0.25")
    assert len(conn.queries) == 3
