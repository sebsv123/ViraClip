"""
Jobs API routes for querying job status from ARQ queue.
"""

from fastapi import APIRouter, HTTPException
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job_status(job_id: str):
    """
    Get the status of a job from the ARQ queue.
    
    Returns job status: queued, in_progress, completed, failed, or not_found
    """
    try:
        import arq.connections
        from ...config import get_config
        
        config = get_config()
        
        # Connect to Redis and check job status
        pool = await arq.connections.create_pool(
            arq.connections.RedisSettings(
                host=config.redis_host,
                port=config.redis_port,
                password=config.redis_password or None
            )
        )
        
        # Try to get job info from Redis
        # ARQ stores job info in keys like "arq:job:{job_id}"
        # In ARQ 0.25+, the pool itself is the redis connection
        redis = pool
        
        # Check in-progress set
        in_progress = await redis.zscore("arq:in-progress", job_id)
        if in_progress:
            await pool.aclose()
            return {
                "job_id": job_id,
                "status": "in_progress",
                "progress": None,
                "result": None,
                "error": None
            }
        
        # Check queued jobs
        queued = await redis.zscore("arq:queue", job_id)
        if queued:
            await pool.aclose()
            return {
                "job_id": job_id,
                "status": "queued",
                "progress": None,
                "result": None,
                "error": None
            }
        
        # Check if job has results (completed or failed)
        job_key = f"arq:job:{job_id}"
        job_data = await redis.get(job_key)
        
        if job_data:
            import json
            try:
                job_info = json.loads(job_data)
                success = job_info.get("success", False)
                result = job_info.get("result")
                error = job_info.get("error")
                
                await pool.aclose()
                return {
                    "job_id": job_id,
                    "status": "completed" if success else "failed",
                    "progress": 100 if success else None,
                    "result": result,
                    "error": error
                }
            except json.JSONDecodeError:
                pass
        
        # Check for job result directly
        result_key = f"arq:result:{job_id}"
        result_data = await redis.get(result_key)
        if result_data:
            await pool.aclose()
            return {
                "job_id": job_id,
                "status": "completed",
                "progress": 100,
                "result": None,
                "error": None
            }
        
        await pool.aclose()
        
        # Job not found in any queue - might be an old job or invalid ID
        return {
            "job_id": job_id,
            "status": "not_found",
            "progress": None,
            "result": None,
            "error": "Job not found in queue"
        }
        
    except Exception as e:
        logger.error(f"Error checking job status: {e}")
        # Return a fallback response instead of error
        return {
            "job_id": job_id,
            "status": "unknown",
            "progress": None,
            "result": None,
            "error": str(e)
        }
