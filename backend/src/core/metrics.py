"""
Custom Prometheus metrics for ViraClip.
Counters, Histograms and Gauges for pipeline observability.
"""
from prometheus_client import Counter, Histogram, Gauge

# Tasks
tasks_created_total = Counter(
    "viraclip_tasks_created_total",
    "Total tasks created",
    ["source_platform"],
)
tasks_completed_total = Counter(
    "viraclip_tasks_completed_total",
    "Total tasks completed successfully",
)
tasks_failed_total = Counter(
    "viraclip_tasks_failed_total",
    "Total tasks failed",
    ["error_type"],
)
tasks_processing_current = Gauge(
    "viraclip_tasks_processing_current",
    "Tasks currently being processed",
)

# Pipeline timing
pipeline_duration_seconds = Histogram(
    "viraclip_pipeline_duration_seconds",
    "Full pipeline duration per task",
    buckets=[30, 60, 120, 300, 600, 900, 1800],
)
pipeline_stage_duration_seconds = Histogram(
    "viraclip_pipeline_stage_seconds",
    "Duration of each pipeline stage",
    ["stage"],
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

# Clips
clips_generated_total = Counter(
    "viraclip_clips_generated_total",
    "Total clips generated",
)
clips_per_task = Histogram(
    "viraclip_clips_per_task",
    "Number of clips generated per task",
    buckets=[1, 2, 3, 5, 8, 10, 15, 20],
)

# LLM providers
llm_requests_total = Counter(
    "viraclip_llm_requests_total",
    "Total LLM API requests",
    ["provider", "operation"],
)
llm_tokens_total = Counter(
    "viraclip_llm_tokens_total",
    "Total tokens consumed",
    ["provider"],
)
llm_cost_usd_total = Counter(
    "viraclip_llm_cost_usd_total",
    "Total estimated LLM cost in USD",
    ["provider"],
)

# System
disk_free_gb = Gauge(
    "viraclip_disk_free_gb",
    "Free disk space in GB",
    ["directory"],
)
active_users_concurrent = Gauge(
    "viraclip_active_users_concurrent",
    "Users with at least one task currently processing",
)
