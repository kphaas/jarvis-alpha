"""Temporal workflow definitions for Dream Mode."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from brain.dream.activities import (
        flush_cleanup_activity,
        persist_plan_activity,
        plan_session_activity,
        review_plan_activity,
    )
    from brain.dream.idempotency import dream_idempotency_key
    from brain.dream.signals import HALT_SIGNAL_NAME
    from brain.dream.types import (
        CleanupSpec,
        DreamSessionInput,
        DreamSessionResult,
        PersistPlanSpec,
        PlanSessionSpec,
        ReviewPlanSpec,
    )


PLAN_START_TO_CLOSE = timedelta(minutes=5)
REVIEW_START_TO_CLOSE = timedelta(minutes=3)
PERSIST_PLAN_START_TO_CLOSE = timedelta(seconds=30)
FLUSH_CLEANUP_START_TO_CLOSE = timedelta(seconds=30)
LLM_ACTIVITY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=2,
)
FLUSH_CLEANUP_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=10),
    maximum_attempts=3,
)


@workflow.defn
class DreamSessionWorkflow:
    """One Temporal workflow execution per Dream session."""

    def __init__(self) -> None:
        self._halt_reason: str | None = None
        self._halt_severity: str | None = None

    @workflow.signal(name=HALT_SIGNAL_NAME)
    async def halt(self, reason: str, severity: str = "graceful") -> None:
        """Request a controlled halt.

        D3.4 wires external kill watchers to this signal. D3.3 stores the
        request so later workflow steps can choose the safest terminal state.
        """

        self._halt_reason = reason or "halt requested"
        self._halt_severity = severity or "graceful"

    @workflow.run
    async def run(self, session: DreamSessionInput) -> DreamSessionResult:
        workflow_id = workflow.info().workflow_id
        completed_steps: list[str] = []
        failed_steps: list[str] = []
        replan_count = 0
        revision_hint: str | None = None
        max_revisions = 0
        cleanup: CleanupSpec

        try:
            while True:
                if self._halt_reason:
                    cleanup = self._cleanup_spec(
                        session=session,
                        completed_steps=completed_steps,
                        failed_steps=failed_steps,
                        final_status=self._halt_final_status(),
                        briefing_summary=(
                            "Dream workflow halted before plan approval."
                        ),
                    )
                    break

                plan_spec = PlanSessionSpec(
                    session_id=session.session_id,
                    user_id=session.user_id,
                    goal_type=session.goal_type,
                    goal_text=session.prompt,
                    prompt_version=session.prompt_version,
                    recent_context=session.recent_context,
                    prior_lessons=session.prior_lessons,
                    revision_hint=revision_hint,
                )
                plan_result = await workflow.execute_activity(
                    plan_session_activity,
                    args=[
                        dream_idempotency_key(
                            workflow_id,
                            "plan",
                            f"{session.session_id}:{replan_count}",
                        ),
                        plan_spec,
                    ],
                    start_to_close_timeout=PLAN_START_TO_CLOSE,
                    retry_policy=LLM_ACTIVITY_RETRY_POLICY,
                )
                completed_steps.append(f"plan:{replan_count + 1}")
                max_revisions = int(plan_result.policy.get("max_revisions", 0))

                if self._halt_reason:
                    cleanup = self._cleanup_spec(
                        session=session,
                        completed_steps=completed_steps,
                        failed_steps=failed_steps,
                        final_status=self._halt_final_status(),
                        briefing_summary=(
                            "Dream workflow halted after planning and before review."
                        ),
                    )
                    break

                review_result = await workflow.execute_activity(
                    review_plan_activity,
                    args=[
                        dream_idempotency_key(
                            workflow_id,
                            "review",
                            f"{session.session_id}:{replan_count}",
                        ),
                        ReviewPlanSpec(
                            session_id=session.session_id,
                            user_id=session.user_id,
                            goal_type=session.goal_type,
                            plan=plan_result.plan,
                            prompt_version=session.prompt_version,
                        ),
                    ],
                    start_to_close_timeout=REVIEW_START_TO_CLOSE,
                    retry_policy=LLM_ACTIVITY_RETRY_POLICY,
                )
                completed_steps.append(f"review:{replan_count + 1}")

                review_payload = {
                    "verdict": review_result.verdict,
                    "reasoning": review_result.reasoning,
                    "issues": review_result.issues,
                    "revision_hint": review_result.revision_hint,
                }

                if self._halt_reason:
                    cleanup = self._cleanup_spec(
                        session=session,
                        completed_steps=completed_steps,
                        failed_steps=failed_steps,
                        final_status=self._halt_final_status(),
                        briefing_summary=(
                            "Dream workflow halted after review and before persistence."
                        ),
                    )
                    break

                if review_result.verdict == "APPROVED":
                    persist_result = await workflow.execute_activity(
                        persist_plan_activity,
                        args=[
                            dream_idempotency_key(
                                workflow_id,
                                "persist_plan",
                                session.session_id,
                            ),
                            PersistPlanSpec(
                                session_id=session.session_id,
                                plan=plan_result.plan,
                                review=review_payload,
                                replan_count=replan_count,
                            ),
                        ],
                        start_to_close_timeout=PERSIST_PLAN_START_TO_CLOSE,
                        retry_policy=FLUSH_CLEANUP_RETRY_POLICY,
                    )
                    completed_steps.append("persist_plan")
                    cleanup = self._cleanup_spec(
                        session=session,
                        completed_steps=completed_steps,
                        failed_steps=failed_steps,
                        final_status="completed",
                        briefing_summary=(
                            "Dream plan approved and persisted with "
                            f"{persist_result.step_count} steps. "
                            "Autonomous step execution remains disabled in this slice."
                        ),
                    )
                    break

                if review_result.verdict == "NEEDS_REVISION" and (
                    replan_count < max_revisions
                ):
                    revision_hint = review_result.revision_hint
                    replan_count += 1
                    continue

                failed_steps.append("review_plan")
                cleanup = self._cleanup_spec(
                    session=session,
                    completed_steps=completed_steps,
                    failed_steps=failed_steps,
                    final_status="failed",
                    briefing_summary=(
                        "Dream plan was not approved. "
                        f"Final reviewer verdict: {review_result.verdict}."
                    ),
                )
                break
        except Exception as exc:
            failed_steps.append("workflow")
            cleanup = self._cleanup_spec(
                session=session,
                completed_steps=completed_steps,
                failed_steps=failed_steps,
                final_status="failed",
                briefing_summary=f"Dream workflow failed before completion: {exc}",
            )

        await self._flush_cleanup(workflow_id, cleanup)

        return DreamSessionResult(
            session_id=session.session_id,
            status=cleanup.final_status,
            halt_reason=cleanup.halt_reason,
            steps_completed=len(cleanup.completed_steps),
            steps_failed=len(cleanup.failed_steps),
            total_cost_usd=0.0,
        )

    def _cleanup_spec(
        self,
        session: DreamSessionInput,
        completed_steps: list[str],
        failed_steps: list[str],
        final_status: str,
        briefing_summary: str,
    ) -> CleanupSpec:
        return CleanupSpec(
            session_id=session.session_id,
            completed_steps=completed_steps,
            failed_steps=failed_steps,
            final_status=final_status,
            halt_reason=self._halt_reason,
            halt_severity=self._halt_severity,
            briefing_summary=briefing_summary,
        )

    def _halt_final_status(self) -> str:
        if self._halt_severity == "killed":
            return "killed"
        if self._halt_severity == "aborted":
            return "aborted"
        return "halted"

    async def _flush_cleanup(
        self,
        workflow_id: str,
        cleanup: CleanupSpec,
    ) -> None:
        await workflow.execute_activity(
            flush_cleanup_activity,
            args=[
                dream_idempotency_key(
                    workflow_id,
                    "flush_cleanup",
                    cleanup.session_id,
                ),
                cleanup,
            ],
            start_to_close_timeout=FLUSH_CLEANUP_START_TO_CLOSE,
            retry_policy=FLUSH_CLEANUP_RETRY_POLICY,
        )
