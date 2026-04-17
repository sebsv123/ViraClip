"""
Concurrency and Parallelism Optimizer
Manages concurrent processing with resource-aware scheduling.
"""

import asyncio
import logging
from typing import Callable, Any, List, Dict, Optional, Awaitable
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from dataclasses import dataclass
from enum import Enum
import time

logger = logging.getLogger(__name__)

def _get_psutil():
    """Lazy import psutil to avoid import errors in worker initialization."""
    import psutil
    return psutil


class TaskPriority(Enum):
    """Priority levels for task scheduling."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


@dataclass
class TaskSpec:
    """Task specification for scheduling."""
    id: str
    priority: TaskPriority
    func: Callable[..., Awaitable[Any]]
    args: tuple = ()
    kwargs: dict = None
    estimated_duration: float = 30.0  # seconds
    cpu_intensive: bool = False
    memory_mb: int = 500

    def __post_init__(self):
        if self.kwargs is None:
            self.kwargs = {}


class ConcurrencyOptimizer:
    """
    Manages concurrent task execution with system resource awareness.
    Dynamically adjusts worker pools based on system load.
    """
    
    def __init__(self, max_workers: int = None):
        psutil = _get_psutil()
        self.max_workers = max_workers or (psutil.cpu_count() or 4)
        self.thread_pool = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="viraclip_worker_"
        )
        self.process_pool: Optional[ProcessPoolExecutor] = None
        
        # Resource tracking
        self._active_tasks = 0
        self._semaphore = asyncio.Semaphore(self.max_workers * 2)
        self._task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._running = False
        
        # Performance tracking
        self._task_times: Dict[str, List[float]] = {}
    
    async def start(self):
        """Start the task scheduler."""
        self._running = True
        asyncio.create_task(self._scheduler_loop())
        logger.info(f"Concurrency optimizer started with {self.max_workers} workers")
    
    async def stop(self):
        """Stop the scheduler and cleanup."""
        self._running = False
        self.thread_pool.shutdown(wait=True)
        if self.process_pool:
            self.process_pool.shutdown(wait=True)
        logger.info("Concurrency optimizer stopped")
    
    async def submit(self, task: TaskSpec) -> asyncio.Future:
        """Submit a task for execution."""
        future = asyncio.Future()
        await self._task_queue.put((task.priority.value, task.id, task, future))
        return future
    
    async def _scheduler_loop(self):
        """Main scheduler loop."""
        while self._running:
            try:
                # Check system resources
                psutil = _get_psutil()
                cpu_percent = psutil.cpu_percent(interval=0.1)
                memory = psutil.virtual_memory()
                
                # Adjust concurrency based on load
                if cpu_percent > 80 or memory.percent > 85:
                    await asyncio.sleep(0.5)  # Back off when loaded
                    continue
                
                # Get next task
                try:
                    priority, task_id, task, future = await asyncio.wait_for(
                        self._task_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Execute with semaphore
                asyncio.create_task(self._execute_task(task, future))
                
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(1)
    
    async def _execute_task(self, task: TaskSpec, future: asyncio.Future):
        """Execute a task with resource management."""
        async with self._semaphore:
            self._active_tasks += 1
            start = time.time()
            
            try:
                # Use process pool for CPU-intensive tasks
                if task.cpu_intensive and self.process_pool:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        self.process_pool,
                        task.func,
                        *task.args
                    )
                else:
                    # Use thread pool for I/O-bound tasks
                    if asyncio.iscoroutinefunction(task.func):
                        result = await task.func(*task.args, **task.kwargs)
                    else:
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(
                            self.thread_pool,
                            task.func,
                            *task.args
                        )
                
                future.set_result(result)
                
            except Exception as e:
                future.set_exception(e)
                logger.error(f"Task {task.id} failed: {e}")
            
            finally:
                self._active_tasks -= 1
                duration = time.time() - start
                
                # Track timing
                if task.id not in self._task_times:
                    self._task_times[task.id] = []
                self._task_times[task.id].append(duration)
    
    def get_optimal_concurrency(self) -> int:
        """Calculate optimal concurrent tasks based on system state."""
        psutil = _get_psutil()
        cpu_count = psutil.cpu_count() or 4
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        
        # Base concurrency on CPU count
        optimal = cpu_count
        
        # Reduce if system is under load
        if cpu_percent > 70:
            optimal = max(1, optimal - 2)
        if memory.percent > 80:
            optimal = max(1, optimal - 1)
        
        return optimal
    
    def get_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        return {
            "max_workers": self.max_workers,
            "active_tasks": self._active_tasks,
            "queue_size": self._task_queue.qsize() if hasattr(self._task_queue, 'qsize') else 'unknown',
            "average_task_times": {
                k: sum(v) / len(v) if v else 0
                for k, v in self._task_times.items()
            },
        }


class ParallelBatchProcessor:
    """Process batches of items with controlled parallelism."""
    
    def __init__(self, max_concurrent: int = 4):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_batch(
        self,
        items: List[Any],
        processor: Callable[[Any], Awaitable[Any]],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[Any]:
        """
        Process a batch of items with controlled concurrency.
        
        Args:
            items: List of items to process
            processor: Async function to process each item
            progress_callback: Called with (completed, total) updates
        
        Returns:
            List of results in the same order as input
        """
        results = [None] * len(items)
        completed = 0
        
        async def process_one(index: int, item: Any):
            nonlocal completed
            async with self._semaphore:
                try:
                    result = await processor(item)
                    results[index] = result
                except Exception as e:
                    logger.error(f"Failed to process item {index}: {e}")
                    results[index] = e
                finally:
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(items))
        
        # Start all tasks
        tasks = [
            asyncio.create_task(process_one(i, item))
            for i, item in enumerate(items)
        ]
        
        # Wait for completion
        await asyncio.gather(*tasks, return_exceptions=True)
        
        return results
    
    async def process_chunks(
        self,
        items: List[Any],
        chunk_size: int,
        processor: Callable[[List[Any]], Awaitable[List[Any]]]
    ) -> List[Any]:
        """Process items in chunks for efficiency."""
        chunks = [
            items[i:i + chunk_size]
            for i in range(0, len(items), chunk_size)
        ]
        
        results = []
        for chunk in chunks:
            async with self._semaphore:
                chunk_results = await processor(chunk)
                results.extend(chunk_results)
        
        return results


class AdaptiveThrottler:
    """
    Adaptive rate limiter that adjusts based on system load
    and external service response times.
    """
    
    def __init__(
        self,
        initial_rate: float = 10.0,  # requests per second
        min_rate: float = 1.0,
        max_rate: float = 100.0,
        window_size: int = 10
    ):
        self.current_rate = initial_rate
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.window_size = window_size
        
        self._last_request_times: List[float] = []
        self._response_times: List[float] = []
        self._error_count = 0
    
    async def acquire(self):
        """Wait for rate limit slot."""
        now = time.time()
        
        # Clean old entries
        cutoff = now - self.window_size
        self._last_request_times = [
            t for t in self._last_request_times if t > cutoff
        ]
        
        # Calculate wait time
        if len(self._last_request_times) >= self.current_rate:
            oldest = self._last_request_times[0]
            wait_time = (oldest + 1.0 / self.current_rate) - now
            if wait_time > 0:
                await asyncio.sleep(wait_time)
        
        self._last_request_times.append(time.time())
    
    def record_success(self, response_time: float):
        """Record successful request for adaptation."""
        self._response_times.append(response_time)
        
        # Keep only recent measurements
        if len(self._response_times) > self.window_size:
            self._response_times.pop(0)
        
        # Increase rate if responding well
        avg_response = sum(self._response_times) / len(self._response_times)
        if avg_response < 0.5 and self.current_rate < self.max_rate:
            self.current_rate = min(self.max_rate, self.current_rate * 1.1)
    
    def record_error(self):
        """Record error for adaptation."""
        self._error_count += 1
        
        # Decrease rate on errors
        if self._error_count > 3:
            self.current_rate = max(self.min_rate, self.current_rate * 0.7)
            self._error_count = 0


# Global optimizer instance
_optimizer: Optional[ConcurrencyOptimizer] = None


async def get_optimizer() -> ConcurrencyOptimizer:
    """Get or create global concurrency optimizer."""
    global _optimizer
    if _optimizer is None:
        _optimizer = ConcurrencyOptimizer()
        await _optimizer.start()
    return _optimizer


async def parallel_map(
    items: List[Any],
    func: Callable[[Any], Awaitable[Any]],
    max_concurrent: int = 4
) -> List[Any]:
    """Map function over items with parallel execution."""
    processor = ParallelBatchProcessor(max_concurrent)
    return await processor.process_batch(items, func)


async def run_with_timeout(
    coro: Awaitable[Any],
    timeout: float,
    task_name: str = "unnamed"
) -> Any:
    """Run coroutine with timeout and proper cleanup."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(f"Task {task_name} timed out after {timeout}s")
        raise


# Decorators for easy application
def parallel(max_concurrent: int = 4):
    """Decorator to run function with parallel batch processing."""
    def decorator(func):
        async def wrapper(items: List[Any], **kwargs):
            processor = ParallelBatchProcessor(max_concurrent)
            
            async def processor_wrapper(item):
                return await func(item, **kwargs)
            
            return await processor.process_batch(items, processor_wrapper)
        return wrapper
    return decorator
