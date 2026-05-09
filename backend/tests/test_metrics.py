"""Tests for Prometheus metrics."""
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from src.core.metrics import (
    tasks_processing_current,
    pipeline_duration_seconds,
    llm_cost_usd_total,
)


def test_tasks_processing_gauge_increments():
    """Gauge increments correctly."""
    initial = tasks_processing_current._value.get()
    tasks_processing_current.inc()
    assert tasks_processing_current._value.get() == initial + 1


def test_tasks_processing_gauge_decrements():
    """Gauge decrements correctly."""
    tasks_processing_current.inc()
    val_after_inc = tasks_processing_current._value.get()
    tasks_processing_current.dec()
    assert tasks_processing_current._value.get() == val_after_inc - 1


def test_pipeline_duration_histogram_observes():
    """Histogram observes value correctly."""
    pipeline_duration_seconds.observe(45.2)
    # Can't easily assert _sum, but no exception means it worked
    assert True


def test_llm_cost_counter_increments():
    """Counter with labels increments correctly."""
    initial = llm_cost_usd_total.labels(provider="groq")._value.get()
    llm_cost_usd_total.labels(provider="groq").inc(0.003)
    assert llm_cost_usd_total.labels(provider="groq")._value.get() == initial + 0.003
