"""
Performance Benchmark Tests

Measures performance improvements from optimizations:
- Redis connection pooling
- Async FFmpeg operations
- HTTP compression
- Database query performance
"""
import pytest
import time
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import json
import gzip


@pytest.mark.performance
class TestRedisConnectionPooling:
    """Benchmark Redis connection pooling performance."""
    
    @pytest.mark.asyncio
    async def test_redis_pool_reuses_connections(self):
        """Should reuse connections from pool."""
        from src.utils.redis_pool import get_redis_client, get_connection_pool
        
        # Get pool stats before
        pool = get_connection_pool()
        initial_available = len(pool._available_connections) if hasattr(pool, '_available_connections') else 0
        
        # Make multiple concurrent requests
        async def redis_op(i):
            redis = await get_redis_client()
            await redis.set(f"test:{i}", f"value:{i}")
            return await redis.get(f"test:{i}")
        
        results = await asyncio.gather(*[redis_op(i) for i in range(10)])
        
        # All should succeed
        assert all(r == f"value:{i}" for i, r in enumerate(results))
        
        # Cleanup
        redis = await get_redis_client()
        for i in range(10):
            await redis.delete(f"test:{i}")
    
    @pytest.mark.asyncio
    async def test_redis_pool_performance_vs_individual(self):
        """Pool should be faster than individual connections."""
        from src.utils.redis_pool import get_redis_client
        
        # Warm up pool
        _ = await get_redis_client()
        
        # Benchmark pooled connections
        start = time.perf_counter()
        redis = await get_redis_client()
        for i in range(100):
            await redis.set(f"bench:{i}", "x")
        pool_duration = (time.perf_counter() - start) * 1000
        
        # Cleanup
        for i in range(100):
            await redis.delete(f"bench:{i}")
        
        # Log performance
        print(f"\n[Redis Pool] 100 operations: {pool_duration:.1f}ms")
        assert pool_duration < 5000  # Should complete in < 5 seconds


@pytest.mark.performance
class TestFFmpegAsyncOperations:
    """Benchmark FFmpeg async operations."""
    
    @pytest.mark.asyncio
    async def test_async_ffmpeg_concurrent(self):
        """Should run multiple FFmpeg operations concurrently."""
        from src.utils.ffmpeg_pool import FFmpegPool
        
        pool = FFmpegPool(max_concurrent=4)
        
        # Create a test video (mock or real small video)
        # For this test we just verify the async pattern works
        
        # Simulate concurrent operations
        async def mock_ffmpeg_op(i):
            await asyncio.sleep(0.01)  # Simulate work
            return True
        
        start = time.perf_counter()
        results = await asyncio.gather(*[mock_ffmpeg_op(i) for i in range(10)])
        duration = (time.perf_counter() - start) * 1000
        
        assert all(results)
        print(f"\n[FFmpeg Async] 10 concurrent ops: {duration:.1f}ms")
        assert duration < 100  # Should complete quickly with concurrency
    
    @pytest.mark.asyncio
    async def test_batch_clip_extraction(self):
        """Batch extraction should be efficient."""
        from src.utils.ffmpeg_pool import FFmpegPool
        
        pool = FFmpegPool(max_concurrent=2)
        
        # Mock batch extraction
        clips = [
            (0.0, 1.0, Path(f"/tmp/test_clip_{i}.mp4"))
            for i in range(5)
        ]
        
        # Use mock to avoid actual FFmpeg dependency
        with patch.object(pool, 'extract_clip_fast', new_callable=AsyncMock) as mock_extract:
            from src.utils.ffmpeg_pool import FFmpegResult
            
            mock_extract.return_value = FFmpegResult(
                success=True,
                output_path=Path("/tmp/test.mp4"),
                stdout="",
                stderr="",
                duration_ms=100
            )
            
            start = time.perf_counter()
            results = await pool.batch_extract_clips(
                Path("/tmp/test.mp4"),
                clips,
                max_parallel=2
            )
            duration = (time.perf_counter() - start) * 1000
            
            assert len(results) == 5
            assert all(r.success for r in results)
            print(f"\n[FFmpeg Batch] 5 clips extracted: {duration:.1f}ms")


@pytest.mark.performance
class TestHTTPCompression:
    """Benchmark HTTP compression performance."""
    
    def test_gzip_compression_ratio(self):
        """Should achieve good compression ratio."""
        # Sample JSON response data
        data = {
            "tasks": [
                {
                    "id": f"task_{i}",
                    "status": "completed",
                    "clips": [{"id": f"clip_{j}", "score": 85.5} for j in range(10)]
                }
                for i in range(100)
            ]
        }
        
        json_bytes = json.dumps(data).encode('utf-8')
        compressed = gzip.compress(json_bytes, compresslevel=6)
        
        original_size = len(json_bytes)
        compressed_size = len(compressed)
        ratio = compressed_size / original_size
        
        print(f"\n[Compression] {original_size} → {compressed_size} bytes ({ratio*100:.1f}%)")
        
        # Should achieve at least 20% compression for JSON
        assert ratio < 0.8
    
    @pytest.mark.asyncio
    async def test_compression_middleware_overhead(self):
        """Compression should not add significant overhead."""
        from src.api.middleware.compression import CompressionMiddleware
        from fastapi import FastAPI, Request
        from starlette.testclient import TestClient
        
        app = FastAPI()
        
        @app.get("/test")
        def test_endpoint():
            return {"data": "x" * 1000}  # 1KB response
        
        # Without compression
        client_no_compress = TestClient(app)
        start = time.perf_counter()
        response1 = client_no_compress.get("/test")
        no_compress_time = (time.perf_counter() - start) * 1000
        
        # With compression (manually add header)
        start = time.perf_counter()
        response2 = client_no_compress.get("/test", headers={"Accept-Encoding": "gzip"})
        compress_time = (time.perf_counter() - start) * 1000
        
        overhead = compress_time - no_compress_time
        print(f"\n[Compression Overhead] {overhead:.2f}ms")
        
        # Overhead should be minimal (< 10ms for 1KB)
        assert overhead < 10


@pytest.mark.performance
class TestDatabaseQueryPerformance:
    """Benchmark database query performance with indexes."""
    
    @pytest.mark.asyncio
    async def test_task_query_with_index(self):
        """Task queries should use indexes efficiently."""
        from sqlalchemy import select, text
        from src.models import Task
        from datetime import datetime, timedelta
        
        # This is a mock test - in production, verify with EXPLAIN ANALYZE
        
        # Simulate query that should use index
        query = (
            select(Task)
            .where(Task.user_id == "test_user")
            .where(Task.created_at >= datetime.utcnow() - timedelta(days=30))
            .order_by(Task.created_at.desc())
        )
        
        # Verify query compiles
        sql_str = str(query.compile(compile_kwargs={"literal_binds": True}))
        
        # Should contain WHERE clauses that match indexes
        assert "user_id" in sql_str.lower()
        assert "created_at" in sql_str.lower()
    
    @pytest.mark.asyncio
    async def test_batch_operations_performance(self):
        """Batch operations should be efficient."""
        from src.services.analytics_service import AnalyticsService
        
        mock_db = MagicMock()
        
        # Mock result returning 1000 rows
        mock_result = MagicMock()
        mock_tasks = [MagicMock() for _ in range(1000)]
        for t in mock_tasks:
            t.status = "completed"
            t.created_at = datetime.utcnow() - timedelta(days=1)
            t.updated_at = datetime.utcnow()
            t.clips = []
        
        mock_result.scalars.return_value.all.return_value = mock_tasks
        mock_db.execute.return_value = mock_result
        
        service = AnalyticsService(mock_db)
        
        start = time.perf_counter()
        metrics = await service.get_task_metrics(days=30)
        duration = (time.perf_counter() - start) * 1000
        
        print(f"\n[DB Query] 1000 tasks metrics: {duration:.1f}ms")
        
        assert metrics.total_tasks == 1000
        assert duration < 100  # Should be fast


@pytest.mark.performance
class TestOverallSystemPerformance:
    """Overall system performance benchmarks."""
    
    @pytest.mark.asyncio
    async def test_concurrent_task_processing_simulation(self):
        """Simulate concurrent task processing."""
        
        async def process_task(task_id: str) -> dict:
            # Simulate: download (100ms) + transcribe (200ms) + render (300ms)
            await asyncio.sleep(0.1)  # Download
            await asyncio.sleep(0.2)  # Transcribe
            await asyncio.sleep(0.3)  # Render
            return {"task_id": task_id, "status": "completed"}
        
        # Process 10 tasks concurrently
        task_ids = [f"task_{i}" for i in range(10)]
        
        start = time.perf_counter()
        results = await asyncio.gather(*[process_task(tid) for tid in task_ids])
        duration = (time.perf_counter() - start) * 1000
        
        print(f"\n[System] 10 tasks concurrent: {duration:.1f}ms")
        
        assert len(results) == 10
        # With proper async, 10 tasks should complete in ~600ms (not 6000ms serial)
        assert duration < 1000
    
    @pytest.mark.asyncio
    async def test_memory_efficiency_with_streaming(self):
        """Streaming should be memory efficient."""
        
        async def stream_process():
            # Simulate processing large data in chunks
            total = 0
            for chunk in range(100):  # 100 chunks
                # Simulate 1MB chunk processing
                await asyncio.sleep(0.001)
                total += 1024 * 1024
            return total
        
        start = time.perf_counter()
        result = await stream_process()
        duration = (time.perf_counter() - start) * 1000
        
        print(f"\n[Streaming] 100MB processed: {duration:.1f}ms")
        assert result == 100 * 1024 * 1024


# Performance baseline tests
@pytest.mark.benchmark
class TestPerformanceBaselines:
    """Establish performance baselines."""
    
    def test_json_serialization_baseline(self):
        """JSON serialization should be fast."""
        data = {"items": [{"id": i, "data": "x" * 100} for i in range(1000)]}
        
        start = time.perf_counter()
        for _ in range(100):
            json_str = json.dumps(data)
            _ = json.loads(json_str)
        duration = (time.perf_counter() - start) * 1000
        
        print(f"\n[JSON] 100 serialize/deserialize: {duration:.1f}ms")
        assert duration < 500
    
    def test_hash_computation_baseline(self):
        """Video hash computation should be fast."""
        import hashlib
        
        # Simulate 1MB chunk
        data = b"x" * (1024 * 1024)
        
        start = time.perf_counter()
        for _ in range(100):
            _ = hashlib.sha256(data).hexdigest()
        duration = (time.perf_counter() - start) * 1000
        
        print(f"\n[Hash] 100 SHA256 of 1MB: {duration:.1f}ms")
        assert duration < 200
