"""Flask extension for z4j.

Provides the :class:`Z4J` extension class that integrates the z4j
agent runtime into a Flask application. Supports both eager and lazy
initialization patterns:

Eager::

    app = Flask(__name__)
    z4j = Z4J(app)

Lazy (application factory pattern)::

    z4j = Z4J()

    def create_app():
        app = Flask(__name__)
        z4j.init_app(app)
        return app

The extension:

1. Reads configuration from ``app.config`` (flat ``Z4J_*`` keys or
   nested ``Z4J`` dict)
2. Constructs a :class:`FlaskFrameworkAdapter`
3. Discovers engine and scheduler adapters (e.g. ``z4j-celery``)
4. Constructs and starts an :class:`AgentRuntime`
5. Registers ``before_request`` / ``teardown_request`` hooks to
   capture request context
6. Registers an ``atexit`` handler to stop the runtime on shutdown

The entire startup flow is wrapped in try/except so z4j can never
crash the Flask application. The host app is more important than
our observability tool.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flask import Flask

    from z4j_core.models import Config
    from z4j_core.protocols import QueueEngineAdapter, SchedulerAdapter

    from z4j_bare.runtime import AgentRuntime

    from z4j_flask.framework import FlaskFrameworkAdapter

logger = logging.getLogger("z4j.host.flask.extension")


class Z4J:
    """Flask extension that manages the z4j agent runtime.

    Attributes:
        app: The Flask app this extension is bound to, or None if
             using the lazy init pattern.
        _runtime: The running agent runtime, if any.
        _framework: The framework adapter, if initialized.
        _init_lock: Per-instance double-init guard. Flask can be
            served by threaded WSGI servers (gunicorn with gthread,
            waitress, ...) where multiple threads might race
            through init_app on the SAME Z4J instance. The lock is
            per-instance (not module-global) so two different Z4J
            instances - common in multi-app deployments and in
            test suites that build/tear down apps in parallel - do
            not serialise on each other.
    """

    def __init__(self, app: Flask | None = None) -> None:
        self._runtime: AgentRuntime | None = None
        self._framework: FlaskFrameworkAdapter | None = None
        self._config: Config | None = None
        self._init_lock = threading.Lock()

        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """Initialize the z4j extension with a Flask app.

        This method:

        1. Stores the extension on ``app.extensions['z4j']``
        2. Registers request context hooks
        3. Builds configuration from Flask app config + env vars
        4. Discovers engine and scheduler adapters
        5. Creates and starts the agent runtime

        The entire flow is wrapped in try/except - if z4j fails
        to start, Flask keeps running normally.

        Args:
            app: The Flask application instance.
        """
        # Allow tests and tooling to disable the autostart entirely.
        if os.environ.get("Z4J_DISABLED", "").lower() in ("1", "true", "yes", "on"):
            logger.info("z4j: Z4J_DISABLED is set; skipping agent startup")
            app.extensions["z4j"] = self
            return

        # Check Flask config for disabled flag as well.
        if app.config.get("Z4J_DISABLED"):
            logger.info("z4j: Z4J_DISABLED is set in Flask config; skipping agent startup")
            app.extensions["z4j"] = self
            return

        with self._init_lock:
            if self._runtime is not None:
                # Already initialized - just register on this app.
                app.extensions["z4j"] = self
                return

            try:
                self._do_init(app)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "z4j: failed to start agent runtime; continuing without it",
                )
                self._runtime = None
                self._framework = None
                self._config = None

        # Always register the extension, even on failure, so
        # app.extensions['z4j'] is available for health checks.
        app.extensions["z4j"] = self

    def _do_init(self, app: Flask) -> None:
        """Internal init logic, called under self._init_lock."""
        from z4j_bare.runtime import AgentRuntime

        from z4j_flask.config import build_config_from_flask
        from z4j_flask.framework import FlaskFrameworkAdapter

        config = build_config_from_flask(app)
        self._config = config

        framework = FlaskFrameworkAdapter(config)
        self._framework = framework

        engines = _discover_engines(app)
        schedulers = _discover_schedulers(app)

        runtime = AgentRuntime(
            config=config,
            framework=framework,
            engines=engines,
            schedulers=schedulers,
        )

        # Cooperate with other install paths in the same process
        # (typically ``celery.signals.worker_init`` when this Flask
        # app also drives a Celery worker). The first one to register
        # wins; we drop our local copy if we lost the race.
        from z4j_bare._process_singleton import try_register
        active = try_register(runtime, owner="z4j_flask.extension")
        self._runtime = active

        # Register request context hooks (always - even if we lost
        # the race, the Flask app still needs its request-context
        # shims for the existing runtime's redaction / audit paths).
        _register_request_hooks(app)

        # Register the `flask z4j-reconcile` CLI command and (if the
        # operator opts in) run the declarative reconciler now.
        _register_reconcile_cli(app)
        if app.config.get("Z4J_RECONCILE_AUTORUN", False):
            _autorun_reconcile(app)

        if active is not runtime:
            logger.info(
                "z4j: flask extension reused an existing runtime; "
                "skipping start() (another install path won the race)",
            )
            return

        # Start the runtime if autostart is enabled.
        if config.autostart:
            runtime.start()
            framework.fire_startup()

        # Register atexit handler for clean shutdown.
        atexit.register(self._shutdown)

        logger.info("z4j: agent runtime started for flask")

    def _shutdown(self) -> None:
        """Atexit handler that flushes the buffer and stops the runtime."""
        runtime = self._runtime
        framework = self._framework
        if runtime is None:
            return
        try:
            if framework is not None:
                framework.fire_shutdown()
        except Exception:  # noqa: BLE001
            logger.exception("z4j: error during shutdown hooks")
        try:
            runtime.stop(timeout=5.0)
        except Exception:  # noqa: BLE001
            logger.exception("z4j: error during runtime shutdown")
        finally:
            self._runtime = None

    @property
    def runtime(self) -> AgentRuntime | None:
        """Return the running agent runtime, if any.

        Useful for tests and manual buffer flushing.
        """
        return self._runtime

    @property
    def framework(self) -> FlaskFrameworkAdapter | None:
        """Return the framework adapter, if initialized."""
        return self._framework

    @property
    def config(self) -> Config | None:
        """Return the resolved config, if initialized."""
        return self._config


# ---------------------------------------------------------------------------
# Request context hooks
# ---------------------------------------------------------------------------


def _register_request_hooks(app: Flask) -> None:
    """Register before_request and teardown_request hooks on the Flask app.

    These hooks capture the current request in a ContextVar so the
    framework adapter can enrich events with user/tenant/request info.
    """
    from z4j_flask.framework import reset_current_request, set_current_request

    @app.before_request
    def _z4j_before_request() -> None:
        from flask import request
        try:
            token = set_current_request(request._get_current_object())
            # Stash the token on the request's environ so teardown can
            # retrieve it. Using environ avoids adding attributes to
            # the request object itself.
            request.environ["_z4j_context_token"] = token
        except Exception:  # noqa: BLE001
            pass

    @app.teardown_request
    def _z4j_teardown_request(exc: BaseException | None) -> None:  # noqa: ARG001
        from flask import request
        try:
            token = request.environ.pop("_z4j_context_token", None)
            if token is not None:
                reset_current_request(token)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Declarative reconciler hooks
# ---------------------------------------------------------------------------


def _register_reconcile_cli(app: Flask) -> None:
    """Register the ``flask z4j-reconcile`` CLI command on the app.

    The command runs the same code path as
    :func:`reconcile_from_flask_app` and prints a short summary
    (or JSON if ``--json`` is set). Exit codes mirror the Django
    management command:

    - ``0`` - success (or no-op when nothing is configured)
    - ``1`` - the brain rejected the import (HTTP/validation)
    - ``2`` - missing required Flask config
    """
    import click

    @app.cli.command("z4j-reconcile")
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Preview the diff without writing audit rows.",
    )
    @click.option(
        "--json",
        "as_json",
        is_flag=True,
        help="Emit machine-readable JSON instead of text.",
    )
    def z4j_reconcile(dry_run: bool, as_json: bool) -> None:
        """Reconcile Z4J_SCHEDULES (+ optional CELERY_BEAT_SCHEDULE)."""
        import json

        from flask import current_app

        from z4j_flask.declarative import reconcile_from_flask_app

        # Use Click's idiomatic exit so
        # cleanup callbacks fire and the test runner doesn't see a
        # bare ``SystemExit``. Falls back to sys.exit if no Click
        # context is active (defensive, should never happen here).
        ctx = click.get_current_context(silent=True)

        def _exit(code: int) -> None:
            if ctx is not None:
                ctx.exit(code)
            else:
                import sys
                sys.exit(code)

        result = reconcile_from_flask_app(current_app, dry_run=dry_run)

        if result is None:
            msg = (
                "z4j-reconcile: no schedules configured. "
                "Set Z4J_SCHEDULES or Z4J_RECONCILE_CELERY_BEAT=True."
            )
            if as_json:
                click.echo(
                    json.dumps({"ok": True, "skipped": True, "reason": msg}),
                )
            else:
                click.echo(msg)
            _exit(0)
            return

        if as_json:
            click.echo(
                json.dumps(
                    {
                        "ok": result.failed == 0,
                        "dry_run": result.dry_run,
                        "inserted": result.inserted,
                        "updated": result.updated,
                        "unchanged": result.unchanged,
                        "failed": result.failed,
                        "deleted": result.deleted,
                        "errors": result.errors,
                    },
                ),
            )
        else:
            mode = "DRY-RUN " if result.dry_run else ""
            click.echo(f"z4j-reconcile {mode}summary:")
            click.echo(f"  inserted:  {result.inserted}")
            click.echo(f"  updated:   {result.updated}")
            click.echo(f"  unchanged: {result.unchanged}")
            click.echo(f"  deleted:   {result.deleted}")
            if result.failed:
                click.echo(f"  failed:    {result.failed}", err=True)
                for idx, err in result.errors.items():
                    click.echo(f"    [{idx}] {err}", err=True)
            else:
                click.echo("  failed:    0")

        _exit(1 if result.failed else 0)


def _autorun_reconcile(app: Flask) -> None:
    """Call the reconciler once during ``init_app``.

    Best-effort: failures are logged but never block app startup.
    Operators who set ``Z4J_RECONCILE_AUTORUN=True`` accept that
    every Flask process boot writes audit rows; reconcile-from-CI
    is the recommended pattern for production.
    """
    from z4j_flask.declarative import reconcile_from_flask_app

    try:
        result = reconcile_from_flask_app(app)
    except Exception:  # noqa: BLE001
        logger.exception("z4j-flask: reconcile autorun failed")
        return
    if result is None:
        return
    logger.info(
        "z4j-flask: reconcile autorun: inserted=%d updated=%d "
        "unchanged=%d deleted=%d failed=%d",
        result.inserted, result.updated, result.unchanged,
        result.deleted, result.failed,
    )


# ---------------------------------------------------------------------------
# Engine and scheduler discovery
# ---------------------------------------------------------------------------


def _discover_engines(app: Flask) -> list[QueueEngineAdapter]:
    """Try to import every supported engine adapter and instantiate it.

    v1.1.0 supports auto-discovery of ``z4j_celery`` (Celery),
    ``z4j_rq`` (RQ), ``z4j_arq`` (arq), ``z4j_dramatiq``, ``z4j_huey``,
    and ``z4j_taskiq``. Each adapter is wired through Flask config
    keys (e.g. ``app.config["RQ_REDIS_URL"]`` or
    ``app.config["TASKIQ_BROKER"]``). Failure to import an adapter
    (because it is not installed) is silent. Failure to find the
    handle in ``app.config`` is logged at WARNING for the engines
    where it is needed.

    Multiple engines may co-exist in one Flask process, e.g. a
    legacy Celery codepath alongside a new RQ codepath.
    """
    engines: list[QueueEngineAdapter] = []

    for try_import in (
        _try_import_celery_engine,
        _try_import_rq_engine,
        _try_import_arq_engine,
        _try_import_dramatiq_engine,
        _try_import_huey_engine,
        _try_import_taskiq_engine,
    ):
        adapter = try_import(app)
        if adapter is not None:
            engines.append(adapter)

    if not engines:
        logger.warning(
            "z4j: no queue engine adapters installed; the agent will run but "
            "will not capture any task events. pip install z4j-celery (or "
            "z4j-rq / z4j-arq / z4j-dramatiq / z4j-huey / z4j-taskiq) to fix.",
        )
    return engines


def _try_import_celery_engine(app: Flask) -> Any:
    """Best-effort import of CeleryEngineAdapter, wired to the Celery app.

    For Flask+Celery projects, the Celery app is typically created in
    the application factory or a dedicated module. We look for it via:

    1. ``app.config['CELERY_APP']`` - explicit reference
    2. ``app.extensions['celery']`` - if using Flask-Celery-Helper or similar
    3. ``celery_app`` attribute on the Flask app (some patterns store it there)
    """
    try:
        from z4j_celery.engine import CeleryEngineAdapter
    except ImportError:
        return None

    celery_app = _resolve_celery_app(app)
    if celery_app is None:
        logger.warning(
            "z4j-celery is installed but no Celery app could be located; "
            "set app.config['CELERY_APP'] to your celery.app instance.",
        )
        return None
    return CeleryEngineAdapter(celery_app=celery_app)


def _resolve_celery_app(app: Flask) -> Any:
    """Locate the Celery app via several common Flask conventions.

    Returns None if no app can be found.
    """
    # 1. Explicit config reference.
    candidate = app.config.get("CELERY_APP")
    if candidate is not None:
        if isinstance(candidate, str):
            candidate = _resolve_import_path(candidate)
        if candidate is not None:
            return candidate

    # 2. Flask extensions dict.
    candidate = app.extensions.get("celery")
    if candidate is not None:
        # Some Flask-Celery integrations store the Celery app directly,
        # others wrap it in an object that has a ``celery`` attribute.
        actual = getattr(candidate, "celery", candidate)
        if actual is not None:
            return actual

    # 3. Attribute on the Flask app object.
    candidate = getattr(app, "celery_app", None)
    if candidate is not None:
        return candidate

    return None


def _try_import_rq_engine(app: Flask) -> Any:
    """Best-effort import of :class:`RqEngineAdapter`.

    Resolution order:

    1. ``app.config["RQ_APP"]``, pre-built rq_app object (or import path).
    2. ``app.config["RQ_REDIS_URL"]``, Redis URL; we wrap it in a
       minimal duck-typed rq_app that satisfies the adapter's
       interface.

    Either gets the adapter wired up. If neither is set, RQ
    discovery is skipped silently (operator may be running the
    agent without RQ).
    """
    try:
        from z4j_rq.engine import RqEngineAdapter
    except ImportError:
        return None

    rq_app = _resolve_rq_app(app)
    if rq_app is None:
        return None
    return RqEngineAdapter(rq_app=rq_app)


def _resolve_rq_app(app: Flask) -> Any:
    candidate = app.config.get("RQ_APP")
    if candidate is not None:
        if isinstance(candidate, str):
            candidate = _resolve_import_path(candidate)
        if candidate is not None:
            return candidate

    redis_url = app.config.get("RQ_REDIS_URL")
    if redis_url:
        return _build_minimal_rq_app(redis_url)

    return None


def _build_minimal_rq_app(redis_url: str) -> Any:
    """Wrap a Redis URL in the duck-typed object RqEngineAdapter expects.

    Mirrors :func:`z4j_rq.worker_bootstrap._build_rq_app` (which is
    private). We re-implement here rather than import a private
    helper so z4j-flask's surface stays self-contained. The shape
    is documented in :class:`RqEngineAdapter`'s docstring.
    """
    try:
        import redis
        from rq import Queue
        from rq.job import Job
    except ImportError:
        logger.warning(
            "z4j: RQ_REDIS_URL set but `redis` / `rq` not installed",
        )
        return None

    try:
        connection = redis.Redis.from_url(redis_url)
        connection.ping()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "z4j: cannot reach Redis at RQ_REDIS_URL=%s (%s)",
            redis_url, str(exc)[:200],
        )
        return None

    class _FlaskRqApp:
        def __init__(self, conn: Any) -> None:
            self.connection = conn

        @property
        def queues(self) -> list[Any]:
            try:
                return list(Queue.all(connection=self.connection))
            except Exception:  # noqa: BLE001
                return []

        def queue_for(self, job: Any) -> Any:
            return Queue(name=getattr(job, "origin", "default"),
                         connection=self.connection)

        def queue_for_name(self, name: str) -> Any:
            return Queue(name=name, connection=self.connection)

        def fetch_job(self, task_id: str) -> Any:
            try:
                return Job.fetch(task_id, connection=self.connection)
            except Exception:  # noqa: BLE001
                return None

    return _FlaskRqApp(connection)


def _try_import_arq_engine(app: Flask) -> Any:
    """Best-effort import of :class:`ArqEngineAdapter`.

    Reads ``app.config["ARQ_REDIS_SETTINGS"]`` (an arq pool /
    RedisSettings, or an import path) and the optional
    ``app.config["ARQ_FUNCTION_NAMES"]`` list. Without
    ``ARQ_REDIS_SETTINGS`` we skip silently.
    """
    try:
        from z4j_arq import ArqEngineAdapter
    except ImportError:
        return None

    settings = app.config.get("ARQ_REDIS_SETTINGS")
    if isinstance(settings, str):
        settings = _resolve_import_path(settings)
    if settings is None:
        return None

    function_names = app.config.get("ARQ_FUNCTION_NAMES", ())
    queue_name = app.config.get("ARQ_QUEUE_NAME", "arq:queue")
    return ArqEngineAdapter(
        redis_settings=settings,
        function_names=function_names,
        queue_name=queue_name,
    )


def _try_import_dramatiq_engine(app: Flask) -> Any:
    """Best-effort import of :class:`DramatiqEngineAdapter`.

    Resolution:

    1. ``app.config["DRAMATIQ_BROKER"]``, explicit broker (or import path).
    2. ``dramatiq.get_broker()``, the process-global broker, IFF
       at least one actor has been registered. Without the actor
       check we'd pick up Dramatiq's default StubBroker (auto-
       created on first import) in projects that never opted into
       Dramatiq, polluting the agent's engine list.

    If neither yields a configured broker we skip silently.
    """
    try:
        from z4j_dramatiq.engine import DramatiqEngineAdapter
    except ImportError:
        return None

    broker = app.config.get("DRAMATIQ_BROKER")
    if isinstance(broker, str):
        broker = _resolve_import_path(broker)
    if broker is None:
        try:
            import dramatiq
            candidate = dramatiq.get_broker()
            # Only adopt the global broker if something has been
            # registered against it. ``actors`` is the canonical
            # registry on every Broker subclass.
            actors = getattr(candidate, "actors", None) or {}
            if actors:
                broker = candidate
        except Exception:  # noqa: BLE001
            return None
    if broker is None:
        return None
    return DramatiqEngineAdapter(broker=broker)


def _try_import_huey_engine(app: Flask) -> Any:
    """Best-effort import of :class:`HueyEngineAdapter`.

    Reads ``app.config["HUEY"]`` (the Huey instance, or an import
    path). Skips silently if not set.
    """
    try:
        from z4j_huey import HueyEngineAdapter
    except ImportError:
        return None

    huey = app.config.get("HUEY")
    if isinstance(huey, str):
        huey = _resolve_import_path(huey)
    if huey is None:
        return None
    return HueyEngineAdapter(huey=huey)


def _try_import_taskiq_engine(app: Flask) -> Any:
    """Best-effort import of :class:`TaskiqEngineAdapter`.

    Reads ``app.config["TASKIQ_BROKER"]`` (the taskiq broker, or an
    import path). Skips silently if not set.
    """
    try:
        from z4j_taskiq import TaskiqEngineAdapter
    except ImportError:
        return None

    broker = app.config.get("TASKIQ_BROKER")
    if isinstance(broker, str):
        broker = _resolve_import_path(broker)
    if broker is None:
        return None
    return TaskiqEngineAdapter(broker=broker)


def _discover_schedulers(app: Flask) -> list[SchedulerAdapter]:
    """Try to import every supported scheduler adapter."""
    schedulers: list[SchedulerAdapter] = []

    beat = _try_import_celerybeat_scheduler(app)
    if beat is not None:
        schedulers.append(beat)

    return schedulers


def _try_import_celerybeat_scheduler(app: Flask) -> Any:
    try:
        from z4j_celerybeat.scheduler import CeleryBeatSchedulerAdapter
    except ImportError:
        return None
    celery_app = _resolve_celery_app(app)
    return CeleryBeatSchedulerAdapter(celery_app=celery_app)


def _resolve_import_path(path: str) -> Any:
    """Resolve ``"module.path:attribute"`` to the actual object.

    Supports two forms:
    - ``"myapp.celery:app"`` (colon-separated module + attribute)
    - ``"myapp.celery.app"`` (dot-separated, last segment is the attribute)
    """
    import importlib

    try:
        if ":" in path:
            module_path, attr_name = path.rsplit(":", 1)
        elif "." in path:
            module_path, attr_name = path.rsplit(".", 1)
        else:
            return None
        module = importlib.import_module(module_path)
        return getattr(module, attr_name, None)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "z4j: failed to resolve CELERY_APP=%r: %s: %s",
            path,
            type(exc).__name__,
            exc,
        )
        return None


__all__ = ["Z4J"]
