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

logger = logging.getLogger("z4j.agent.flask.extension")


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
# Engine and scheduler discovery
# ---------------------------------------------------------------------------


def _discover_engines(app: Flask) -> list[QueueEngineAdapter]:
    """Try to import every supported engine adapter and instantiate it.

    v1 supports ``z4j_celery`` only. Failure to import an adapter
    (because it is not installed) is silent.
    """
    engines: list[QueueEngineAdapter] = []

    celery_engine = _try_import_celery_engine(app)
    if celery_engine is not None:
        engines.append(celery_engine)

    if not engines:
        logger.warning(
            "z4j: no queue engine adapters installed; the agent will run but "
            "will not capture any task events. pip install z4j-celery to fix.",
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
