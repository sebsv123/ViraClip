"""
Plan limits for rate limiting by subscription tier.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanLimits:
    name: str
    tasks_per_day: int
    tasks_per_month: int
    max_video_duration_s: int
    max_file_size_mb: float
    max_clips_per_task: int
    max_concurrent_tasks: int
    generate_variants: bool
    priority_queue: bool
    api_access: bool


PLAN_LIMITS = {
    "free": PlanLimits(
        name="Free",
        tasks_per_day=3,
        tasks_per_month=30,
        max_video_duration_s=1800,
        max_file_size_mb=500,
        max_clips_per_task=3,
        max_concurrent_tasks=1,
        generate_variants=False,
        priority_queue=False,
        api_access=False,
    ),
    "pro": PlanLimits(
        name="Pro",
        tasks_per_day=20,
        tasks_per_month=400,
        max_video_duration_s=7200,
        max_file_size_mb=2048,
        max_clips_per_task=10,
        max_concurrent_tasks=3,
        generate_variants=True,
        priority_queue=False,
        api_access=True,
    ),
    "enterprise": PlanLimits(
        name="Enterprise",
        tasks_per_day=-1,
        tasks_per_month=-1,
        max_video_duration_s=28800,
        max_file_size_mb=10240,
        max_clips_per_task=25,
        max_concurrent_tasks=10,
        generate_variants=True,
        priority_queue=True,
        api_access=True,
    ),
}


def get_plan_limits(plan: str) -> PlanLimits:
    return PLAN_LIMITS.get(plan.lower(), PLAN_LIMITS["free"])
