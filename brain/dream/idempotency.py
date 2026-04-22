def dream_idempotency_key(workflow_id: str, activity_type: str, step_id: str) -> str:
    """Build a deterministic idempotency key for Dream Mode activity executions.

    Keys MUST be deterministic from a Temporal replay perspective, so this function
    derives the key only from stable identifiers instead of runtime values.

    Args:
        workflow_id: The Dream workflow instance identifier.
        activity_type: The logical activity type (for example, plan or review).
        step_id: The stable step identifier inside the workflow.

    Returns:
        A namespaced idempotency key suitable for deduplicating side effects.
    """
    return f"dream:{workflow_id}:{activity_type}:{step_id}"
