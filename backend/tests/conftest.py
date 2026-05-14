import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# CRITICAL: must be declared at module level for pytest-asyncio to activate
pytest_plugins = ('pytest_asyncio',)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Also expose /app/src so tests using bare 'from services.xxx' or
# 'from video_processing.xxx' imports (without 'src.' prefix) continue to work.
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Create virtual 'backend' package so tests using
# 'from backend.src.xxx import yyy' work inside Docker
# (container has /app/src, not /app/backend/src)
if 'backend' not in sys.modules:
    _backend_pkg = types.ModuleType('backend')
    _backend_pkg.__path__ = [str(ROOT)]
    _backend_pkg.__package__ = 'backend'
    sys.modules['backend'] = _backend_pkg

from src.config import Config

# Try to import database and app factory — these may not exist in all environments
try:
    from src.database import configure_database, init_db, reset_database_state
except ImportError:
    configure_database = init_db = reset_database_state = None

try:
    from src.main_refactored import create_app
except ImportError:
    create_app = None

# Pre-load modules that tests import with bare names but have relative-import
# issues when Python re-imports them as top-level packages.
import importlib as _il
for _preload_path in [
    "src.video_processing.optical_flow_transitions",
    "src.services.viral_scorer_service",
    "src.services.vision_service",
    "src.workers.tasks",
    "src.workers.gpu_tasks",
    "src.services.viral_trend_service",
]:
    try:
        _il.import_module(_preload_path)
    except Exception:
        pass

# Alias every already-loaded src.* submodule to a bare name so that
# `from services.xxx import` and `from video_processing.xxx import`
# resolve to the already-loaded module object (no re-import, no broken
# relative imports).
_aliases = {
    k[4:]: v
    for k, v in list(sys.modules.items())
    if k.startswith("src.") and k[4:] not in sys.modules
}
sys.modules.update(_aliases)


class _FakeRedisPool:
    async def ping(self):
        return True


class FakeQueueAdapter:
    enqueued_jobs = []

    @classmethod
    async def get_pool(cls):
        return _FakeRedisPool()

    @classmethod
    async def close_pool(cls):
        return None

    @classmethod
    async def enqueue_processing_job(cls, function_name: str, processing_mode: str, *args, **kwargs):
        cls.enqueued_jobs.append(
          {
            "function_name": function_name,
            "processing_mode": processing_mode,
            "args": args,
            "kwargs": kwargs,
          }
        )
        return "job-test-1"


@pytest.fixture(scope="session")
def test_database_url():
    return os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@pytest.fixture(scope="session")
async def initialized_database(test_database_url):
    if not test_database_url:
        pytest.skip("DATABASE_URL or TEST_DATABASE_URL must be set for backend tests")

    engine = create_async_engine(test_database_url, poolclass=NullPool)
    configure_database(engine=engine)
    await init_db()
    yield engine
    await reset_database_state()


@pytest.fixture()
async def db_session(initialized_database):
    session_maker = async_sessionmaker(
        initialized_database,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


@pytest.fixture()
async def app(db_session):
    config = Config()
    config.self_host = True
    config.monetization_enabled = False
    config.redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
    config.redis_port = int(os.getenv("REDIS_PORT", "6379"))

    test_app = create_app(config=config, queue_adapter=FakeQueueAdapter)
    return test_app


@pytest.fixture()
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client


@pytest.fixture()
def auth_headers():
    return {"x-viraclip-user-id": "user-1"}


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def mock_redis_progress_emitter(monkeypatch):
    """
    Auto-mock Redis for all progress/event-bus code so tests never need a
    real Redis connection.

    Patches:
      - src.services.progress_emitter.redis  (legacy stub attr)
      - src.events.bus._get_redis            (EventBus async getter)
      - src.events.bus._redis_client         (EventBus singleton)
    """
    mock = MagicMock()
    mock.publish = AsyncMock(return_value=1)
    mock.ping = AsyncMock(return_value=True)
    mock.setex = AsyncMock(return_value=True)
    mock.get = AsyncMock(return_value=None)
    mock.execute_command = AsyncMock(return_value=["progress:test", 0])
    mock.aclose = AsyncMock(return_value=None)

    # pubsub mock — subscribe() returns a mock pubsub that never yields
    pubsub_mock = MagicMock()
    pubsub_mock.subscribe = AsyncMock()
    pubsub_mock.unsubscribe = AsyncMock()
    pubsub_mock.close = AsyncMock()
    pubsub_mock.listen = MagicMock(return_value=_empty_async_gen())
    mock.pubsub = MagicMock(return_value=pubsub_mock)

    # Patch legacy stub attribute on progress_emitter
    try:
        monkeypatch.setattr("src.services.progress_emitter.redis", mock)
    except (AttributeError, ImportError):
        pass

    # Patch EventBus Redis getter so EventBus.publish() never touches real Redis
    async def _fake_get_redis():
        return mock

    try:
        monkeypatch.setattr("src.events.bus._get_redis", _fake_get_redis)
        monkeypatch.setattr("src.events.bus._redis_client", mock)
    except (AttributeError, ImportError):
        pass

    return mock


async def _empty_async_gen():
    """Async generator that immediately stops — used by pubsub.listen() mock."""
    return
    yield  # make it a generator
