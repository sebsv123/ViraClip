"""
AI Metrics and Validation endpoints.

Provides insights into AI analysis quality:
- Tasks without clips (AI failed to find segments)
- Virality score distribution
- Anomaly detection (suspiciously uniform scores, etc.)
- LLM performance validation
"""

import logging
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, func
import statistics

from ...database import get_db
from ...admin_auth import require_admin_user
from ...config import get_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/ai-metrics", tags=["admin", "ai"])


@router.get("")
async def get_ai_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = 7
):
    """
    Get comprehensive AI analysis metrics.
    
    Includes:
    - Task success rate
    - Clips generation stats
    - Virality score distribution
    - Anomaly detection
    
    Args:
        days: Number of days to analyze (default: 7)
    """
    await require_admin_user(request, db, get_config())
    
    metrics = {
        "period": f"last_{days}_days",
        "summary": {},
        "virality_distribution": {},
        "anomalies": [],
        "recommendations": []
    }
    
    # 1. Task success rate
    task_stats = await db.execute(text("""
        SELECT 
            COUNT(*) as total_tasks,
            COUNT(*) FILTER (WHERE status = 'completed') as completed_tasks,
            COUNT(*) FILTER (WHERE status = 'failed') as failed_tasks,
            COUNT(DISTINCT CASE 
                WHEN status = 'completed' AND 
                     NOT EXISTS (SELECT 1 FROM generated_clips WHERE task_id = tasks.id)
                THEN tasks.id 
            END) as tasks_without_clips
        FROM tasks
        WHERE created_at > NOW() - INTERVAL :days DAY
    """), {"days": days})
    
    task_row = task_stats.fetchone()
    
    total_tasks = task_row[0] or 0
    completed_tasks = task_row[1] or 0
    failed_tasks = task_row[2] or 0
    tasks_without_clips = task_row[3] or 0
    
    metrics["summary"] = {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "failed_tasks": failed_tasks,
        "tasks_without_clips": tasks_without_clips,
        "success_rate": round((completed_tasks / total_tasks * 100) if total_tasks > 0 else 0, 2),
        "tasks_with_clips_rate": round(
            ((completed_tasks - tasks_without_clips) / completed_tasks * 100) 
            if completed_tasks > 0 else 0, 2
        )
    }
    
    # 2. Virality score distribution
    virality_stats = await db.execute(text("""
        SELECT 
            virality_score,
            COUNT(*) as count
        FROM generated_clips gc
        JOIN tasks t ON gc.task_id = t.id
        WHERE t.created_at > NOW() - INTERVAL :days DAY
        AND virality_score IS NOT NULL
        GROUP BY virality_score
        ORDER BY virality_score DESC
    """), {"days": days})
    
    score_distribution = {}
    all_scores = []
    
    for row in virality_stats.fetchall():
        score = row[0]
        count = row[1]
        score_distribution[str(score)] = count
        all_scores.extend([score] * count)
    
    if all_scores:
        metrics["virality_distribution"] = {
            "by_score": score_distribution,
            "statistics": {
                "mean": round(statistics.mean(all_scores), 2),
                "median": round(statistics.median(all_scores), 2),
                "stdev": round(statistics.stdev(all_scores), 2) if len(all_scores) > 1 else 0,
                "min": min(all_scores),
                "max": max(all_scores),
                "total_clips": len(all_scores)
            },
            "percentiles": {
                "p25": round(statistics.quantiles(all_scores, n=4)[0], 2) if len(all_scores) >= 4 else 0,
                "p50": round(statistics.median(all_scores), 2),
                "p75": round(statistics.quantiles(all_scores, n=4)[2], 2) if len(all_scores) >= 4 else 0,
                "p90": round(statistics.quantiles(all_scores, n=10)[8], 2) if len(all_scores) >= 10 else 0,
            }
        }
    
    # 3. Anomaly detection
    
    # Anomaly: Tasks without clips (AI failed)
    if tasks_without_clips > 0:
        no_clips_rate = (tasks_without_clips / completed_tasks * 100) if completed_tasks > 0 else 0
        if no_clips_rate > 10:  # >10% is concerning
            metrics["anomalies"].append({
                "type": "high_no_clips_rate",
                "severity": "high" if no_clips_rate > 25 else "medium",
                "value": round(no_clips_rate, 2),
                "description": f"{tasks_without_clips} tasks completed but no clips generated ({no_clips_rate:.1f}%)",
                "recommendation": "Check LLM service health and prompt quality. Review error logs."
            })
    
    # Anomaly: Suspiciously uniform scores (all same score)
    if all_scores:
        unique_scores = len(set(all_scores))
        if unique_scores <= 2 and len(all_scores) > 10:
            metrics["anomalies"].append({
                "type": "uniform_scores",
                "severity": "high",
                "value": unique_scores,
                "description": f"Only {unique_scores} unique virality scores across {len(all_scores)} clips",
                "recommendation": "LLM may be returning default values. Check prompt and validation logic."
            })
        
        # Anomaly: Very low variance (all scores clustered)
        if len(all_scores) > 10:
            stdev = statistics.stdev(all_scores)
            if stdev < 1.0:
                metrics["anomalies"].append({
                    "type": "low_variance",
                    "severity": "medium",
                    "value": round(stdev, 2),
                    "description": f"Very low score variance (σ={stdev:.2f}). Scores are too similar.",
                    "recommendation": "LLM may not be differentiating content quality well. Review prompt."
                })
    
    # Anomaly: High failure rate
    if total_tasks > 0:
        failure_rate = (failed_tasks / total_tasks * 100)
        if failure_rate > 20:  # >20% failures is bad
            metrics["anomalies"].append({
                "type": "high_failure_rate",
                "severity": "high" if failure_rate > 40 else "medium",
                "value": round(failure_rate, 2),
                "description": f"{failed_tasks} tasks failed ({failure_rate:.1f}%)",
                "recommendation": "Review error codes and logs. Check external API health (AssemblyAI, LLM)."
            })
    
    # 4. Recommendations based on metrics
    if not metrics["anomalies"]:
        metrics["recommendations"].append({
            "type": "all_good",
            "message": "No anomalies detected. AI analysis is performing well! 🎉"
        })
    else:
        high_severity = sum(1 for a in metrics["anomalies"] if a["severity"] == "high")
        if high_severity > 0:
            metrics["recommendations"].append({
                "type": "urgent_action",
                "message": f"{high_severity} high-severity issues detected. Immediate attention required."
            })
    
    # Check if LLM improved service is being used
    if all_scores and statistics.mean(all_scores) < 5:
        metrics["recommendations"].append({
            "type": "low_avg_score",
            "message": "Average virality score is low. Consider reviewing content quality or prompt tuning."
        })
    
    return metrics


@router.get("/tasks-without-clips")
async def get_tasks_without_clips(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = 20
):
    """
    Get detailed list of completed tasks that generated no clips.
    
    Useful for debugging why AI failed to find segments.
    """
    await require_admin_user(request, db, get_config())
    
    result = await db.execute(text("""
        SELECT 
            t.id,
            t.created_at,
            t.status,
            t.error_message,
            t.progress_message,
            s.title,
            s.url
        FROM tasks t
        LEFT JOIN sources s ON t.source_id = s.id
        WHERE t.status = 'completed'
        AND NOT EXISTS (
            SELECT 1 FROM generated_clips WHERE task_id = t.id
        )
        ORDER BY t.created_at DESC
        LIMIT :limit
    """), {"limit": limit})
    
    tasks = []
    for row in result.fetchall():
        tasks.append({
            "task_id": row[0],
            "created_at": row[1].isoformat() if row[1] else None,
            "status": row[2],
            "error_message": row[3],
            "progress_message": row[4],
            "video_title": row[5],
            "video_url": row[6]
        })
    
    return {
        "count": len(tasks),
        "tasks": tasks,
        "recommendation": (
            "Review these videos manually. Common causes: "
            "video too short, no speech detected, AI prompt not triggering, "
            "LLM timeout, transcript quality issues."
        )
    }


@router.get("/score-outliers")
async def get_score_outliers(
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = 7
):
    """
    Detect clips with outlier virality scores.
    
    Identifies:
    - Clips with suspiciously high scores (may be false positives)
    - Clips with very low scores (may need prompt tuning)
    """
    await require_admin_user(request, db, get_config())
    
    # Get mean and stdev
    stats_result = await db.execute(text("""
        SELECT 
            AVG(virality_score) as mean,
            STDDEV(virality_score) as stdev
        FROM generated_clips gc
        JOIN tasks t ON gc.task_id = t.id
        WHERE t.created_at > NOW() - INTERVAL :days DAY
        AND virality_score IS NOT NULL
    """), {"days": days})
    
    stats_row = stats_result.fetchone()
    if not stats_row or stats_row[0] is None:
        return {"outliers": [], "message": "Not enough data"}
    
    mean = float(stats_row[0])
    stdev = float(stats_row[1]) if stats_row[1] else 0
    
    # Find outliers (>2 standard deviations from mean)
    threshold_high = mean + (2 * stdev)
    threshold_low = mean - (2 * stdev)
    
    outliers_result = await db.execute(text("""
        SELECT 
            gc.id,
            gc.filename,
            gc.virality_score,
            gc.duration,
            gc.hook_title,
            t.id as task_id,
            s.title as video_title
        FROM generated_clips gc
        JOIN tasks t ON gc.task_id = t.id
        LEFT JOIN sources s ON t.source_id = s.id
        WHERE t.created_at > NOW() - INTERVAL :days DAY
        AND (
            virality_score > :threshold_high 
            OR virality_score < :threshold_low
        )
        ORDER BY ABS(virality_score - :mean) DESC
        LIMIT 50
    """), {"days": days, "threshold_high": threshold_high, "threshold_low": threshold_low, "mean": mean})
    
    outliers = []
    for row in outliers_result.fetchall():
        outliers.append({
            "clip_id": row[0],
            "filename": row[1],
            "virality_score": row[2],
            "duration": row[3],
            "hook_title": row[4],
            "task_id": row[5],
            "video_title": row[6],
            "deviation_from_mean": round(abs(row[2] - mean), 2),
            "type": "high" if row[2] > threshold_high else "low"
        })
    
    return {
        "statistics": {
            "mean": round(mean, 2),
            "stdev": round(stdev, 2),
            "threshold_high": round(threshold_high, 2),
            "threshold_low": round(threshold_low, 2)
        },
        "outliers": outliers,
        "count": len(outliers)
    }


@router.post("/validate-llm")
async def validate_llm_with_sample(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Validate LLM is working correctly with a sample transcript.
    
    Runs AI analysis on a known-good transcript and checks:
    - Response format is valid
    - Scores are in expected range
    - Segments are reasonable
    """
    await require_admin_user(request, db, get_config())
    
    # Sample transcript (known to have viral potential)
    sample_transcript = """
[00:00 - 00:15] I'm about to reveal a secret that billion-dollar companies don't want you to know.
[00:15 - 00:30] This simple trick changed my life completely. And it only takes 5 minutes a day.
[00:30 - 00:50] Most people spend years trying to figure this out, but I'm giving it to you for free.
[00:50 - 01:10] Here's exactly what you need to do. Step one is crucial - don't skip this part.
[01:10 - 01:30] If you implement this today, you could see results by tomorrow. I'm not kidding.
[01:30 - 01:50] The transformation is incredible. Watch what happens when you apply this method.
[01:50 - 02:10] This is the moment everything clicks. Pay close attention to what I'm about to say.
[02:10 - 02:30] That's it! That's the secret. Simple, right? But incredibly powerful.
"""
    
    try:
        from ...services.llm_service_improved import ImprovedLLMService
        from ...ai import get_most_relevant_parts_by_transcript
        
        llm_service = ImprovedLLMService()
        
        # Test 1: Basic connectivity
        test_results = {
            "timestamp": datetime.now().isoformat(),
            "tests": []
        }
        
        # Test LLM analysis
        logger.info("Running AI analysis validation...")
        result = await get_most_relevant_parts_by_transcript(sample_transcript, include_broll=False)
        
        # Validate results
        segments_found = len(result.most_relevant_segments) if result else 0
        
        test_results["tests"].append({
            "name": "AI Analysis Execution",
            "status": "pass" if segments_found > 0 else "fail",
            "details": f"Found {segments_found} segments"
        })
        
        if segments_found > 0:
            scores = [seg.virality_score for seg in result.most_relevant_segments]
            
            # Check score validity
            all_valid = all(1 <= score <= 10 for score in scores)
            test_results["tests"].append({
                "name": "Score Range Validation",
                "status": "pass" if all_valid else "fail",
                "details": f"Scores: {scores}, All in range 1-10: {all_valid}"
            })
            
            # Check score variance
            if len(scores) > 1:
                variance = statistics.variance(scores)
                test_results["tests"].append({
                    "name": "Score Variance",
                    "status": "pass" if variance > 0.5 else "warning",
                    "details": f"Variance: {variance:.2f} (should be >0.5 for diverse scoring)"
                })
            
            # Check segment durations
            durations = [seg.end_time - seg.start_time for seg in result.most_relevant_segments]
            avg_duration = statistics.mean(durations)
            
            test_results["tests"].append({
                "name": "Segment Duration",
                "status": "pass" if 10 <= avg_duration <= 60 else "warning",
                "details": f"Avg duration: {avg_duration:.1f}s (ideal: 10-60s)"
            })
        
        # Overall status
        failures = sum(1 for t in test_results["tests"] if t["status"] == "fail")
        warnings = sum(1 for t in test_results["tests"] if t["status"] == "warning")
        
        test_results["overall_status"] = "healthy" if failures == 0 else "unhealthy"
        test_results["summary"] = {
            "total_tests": len(test_results["tests"]),
            "passed": len([t for t in test_results["tests"] if t["status"] == "pass"]),
            "warnings": warnings,
            "failed": failures
        }
        
        return test_results
        
    except Exception as e:
        logger.error(f"LLM validation failed: {e}")
        return {
            "overall_status": "error",
            "error": str(e),
            "recommendation": "Check LLM service health, API keys, and network connectivity"
        }
