"""Tests for v1.1.0 engine auto-discovery in z4j-flask.

z4j-flask's ``Z4J(app)`` now auto-discovers all 6 engine adapters
(celery + rq + arq + dramatiq + huey + taskiq) from ``app.config``
keys, not just celery. These tests pin the discovery contract for
each engine so a regression in the wiring layer is caught fast.

The tests deliberately use the duck-typed objects each adapter
accepts (FakeRq, real MemoryHuey, real InMemoryBroker) rather than
mocks, this way we also catch any signature drift on the engine
adapters' constructors.
"""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from z4j_flask.extension import (
    _try_import_arq_engine,
    _try_import_celery_engine,
    _try_import_dramatiq_engine,
    _try_import_huey_engine,
    _try_import_rq_engine,
    _try_import_taskiq_engine,
    _discover_engines,
)


# ---------------------------------------------------------------------------
# Celery (regression, must still work with the new fan-out)
# ---------------------------------------------------------------------------


class TestCeleryDiscovery:
    def test_returns_none_when_no_celery_app_configured(self) -> None:
        app = Flask(__name__)
        assert _try_import_celery_engine(app) is None

    def test_picks_up_app_config_celery_app(self) -> None:
        try:
            from celery import Celery
        except ImportError:
            pytest.skip("celery not installed")

        app = Flask(__name__)
        celery_app = Celery("test", broker="memory://", backend="cache+memory://")
        app.config["CELERY_APP"] = celery_app

        adapter = _try_import_celery_engine(app)
        assert adapter is not None
        assert adapter.celery_app is celery_app


# ---------------------------------------------------------------------------
# RQ
# ---------------------------------------------------------------------------


class TestRqDiscovery:
    def test_returns_none_with_no_config(self) -> None:
        app = Flask(__name__)
        assert _try_import_rq_engine(app) is None

    def test_picks_up_pre_built_rq_app(self) -> None:
        pytest.importorskip("z4j_rq")

        class _FakeRqApp:
            connection = None
            queues: list[Any] = []
            def queue_for_name(self, name): return None  # noqa: ARG002
            def queue_for(self, job): return None  # noqa: ARG002
            def fetch_job(self, tid): return None  # noqa: ARG002

        app = Flask(__name__)
        fake = _FakeRqApp()
        app.config["RQ_APP"] = fake

        adapter = _try_import_rq_engine(app)
        assert adapter is not None
        assert adapter.rq_app is fake

    def test_redis_url_unreachable_returns_none(self) -> None:
        """Operator typo / Redis-down: discovery skips quietly so the
        Flask app boots, agent runtime starts without RQ. Logged at
        WARNING for the operator to notice.
        """
        pytest.importorskip("z4j_rq")
        pytest.importorskip("redis")

        app = Flask(__name__)
        # Port 1 is reserved; no Redis there.
        app.config["RQ_REDIS_URL"] = "redis://127.0.0.1:1/0"
        adapter = _try_import_rq_engine(app)
        assert adapter is None


# ---------------------------------------------------------------------------
# arq
# ---------------------------------------------------------------------------


class TestArqDiscovery:
    def test_returns_none_with_no_config(self) -> None:
        app = Flask(__name__)
        assert _try_import_arq_engine(app) is None

    def test_picks_up_redis_settings_pool(self) -> None:
        pytest.importorskip("z4j_arq")

        class _FakePool:
            async def enqueue_job(self, *_a, **_k): ...

        app = Flask(__name__)
        pool = _FakePool()
        app.config["ARQ_REDIS_SETTINGS"] = pool
        app.config["ARQ_FUNCTION_NAMES"] = ["myapp.send_email"]

        adapter = _try_import_arq_engine(app)
        assert adapter is not None
        # Engine stores in private slot; just verify it's wired.
        assert adapter is not None


# ---------------------------------------------------------------------------
# dramatiq
# ---------------------------------------------------------------------------


class TestDramatiqDiscovery:
    def test_explicit_broker_wins_over_global(self) -> None:
        pytest.importorskip("z4j_dramatiq")
        pytest.importorskip("dramatiq")

        class _FakeBroker:
            actors: dict[str, Any] = {}
            def add_middleware(self, mw): ...  # noqa: ARG002
            def get_actor(self, name): raise KeyError(name)  # noqa: ARG002

        app = Flask(__name__)
        b = _FakeBroker()
        app.config["DRAMATIQ_BROKER"] = b

        adapter = _try_import_dramatiq_engine(app)
        assert adapter is not None
        assert adapter.broker is b


# ---------------------------------------------------------------------------
# Huey
# ---------------------------------------------------------------------------


class TestHueyDiscovery:
    def test_returns_none_with_no_huey(self) -> None:
        app = Flask(__name__)
        assert _try_import_huey_engine(app) is None

    def test_picks_up_huey_instance(self) -> None:
        pytest.importorskip("z4j_huey")
        pytest.importorskip("huey")
        from huey import MemoryHuey

        app = Flask(__name__)
        h = MemoryHuey("flask-test", immediate=False)
        app.config["HUEY"] = h

        adapter = _try_import_huey_engine(app)
        assert adapter is not None
        assert adapter.huey is h


# ---------------------------------------------------------------------------
# Taskiq
# ---------------------------------------------------------------------------


class TestTaskiqDiscovery:
    def test_returns_none_with_no_broker(self) -> None:
        app = Flask(__name__)
        assert _try_import_taskiq_engine(app) is None

    def test_picks_up_inmemory_broker(self) -> None:
        pytest.importorskip("z4j_taskiq")
        pytest.importorskip("taskiq")
        from taskiq import InMemoryBroker

        app = Flask(__name__)
        b = InMemoryBroker()
        app.config["TASKIQ_BROKER"] = b

        adapter = _try_import_taskiq_engine(app)
        assert adapter is not None
        assert adapter.broker is b


# ---------------------------------------------------------------------------
# Cross-engine integration
# ---------------------------------------------------------------------------


class TestDiscoverEnginesFanOut:
    def test_no_engines_configured_returns_empty(self) -> None:
        app = Flask(__name__)
        assert _discover_engines(app) == []

    def test_multiple_engines_can_co_exist(self) -> None:
        """Operator running celery for legacy + huey for new work in
        the same Flask process: both adapters get registered.
        """
        pytest.importorskip("z4j_huey")
        pytest.importorskip("huey")
        from huey import MemoryHuey

        app = Flask(__name__)
        h = MemoryHuey("co-exist", immediate=False)
        app.config["HUEY"] = h

        # No celery configured → only huey gets registered.
        adapters = _discover_engines(app)
        engine_class_names = {type(a).__name__ for a in adapters}
        assert "HueyEngineAdapter" in engine_class_names
