"""Domain-aligned Temporal task queues reusable beyond Dream Mode workflows."""

PLANNING_QUEUE = "alpha-planning-v1"
REVIEW_QUEUE = "alpha-review-v1"
EXECUTION_QUEUE = "alpha-execution-v1"
COST_TRACKING_QUEUE = "alpha-cost-tracking-v1"

DREAM_WORKFLOW_QUEUE = PLANNING_QUEUE

DREAM_ACTIVITY_QUEUES = {
    "plan": PLANNING_QUEUE,
    "review": REVIEW_QUEUE,
    "step_execute": EXECUTION_QUEUE,
    "flush_cleanup": COST_TRACKING_QUEUE,
}
