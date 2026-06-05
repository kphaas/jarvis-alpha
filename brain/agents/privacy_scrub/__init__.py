"""Privacy-Scrub Agent — guarded public-data removal for adults + minors.

P1 scope: foundational types, storage DAL, policy engine.
Future phases: inventory scan (P2), HTTP routes (P3), opt-out workflows (P4),
notify alerts (P5), Georgia court module (P6).

Pattern: mirrors brain/agents/buddy_agent.py — callable runner plugged into
Buddy's _maybe_run_managed_agents() tuple. P1 runner is a no-op stub.
"""

__version__ = "0.1.0"
