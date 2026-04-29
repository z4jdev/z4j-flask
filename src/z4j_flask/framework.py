"""The :class:`FlaskFrameworkAdapter`.

Implements :class:`z4j_core.protocols.FrameworkAdapter` for Flask.
The adapter is constructed inside :meth:`extension.Z4J.init_app`,
which calls :func:`z4j_flask.config.build_config_from_flask` to
load configuration first, then hands the resulting Config to the
adapter and the agent runtime.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any
from uuid import UUID

from z4j_core.models import Config, DiscoveryHints, RequestContext, User

if TYPE_CHECKING:
    pass

logger = logging.getLogger("z4j.agent.flask.framework")

# ContextVar for the current Flask request - set by before_request,
# cleared by teardown_request in the extension. Flask's own
# ``flask.request`` proxy is available during request handling, but
# using a ContextVar gives us an explicit handle for the adapter.
_current_request: ContextVar["Any | None"] = ContextVar(
    "_z4j_flask_current_request", default=None,
)


class FlaskFrameworkAdapter:
    """Framework adapter for Flask.

    Implements the :class:`FrameworkAdapter` Protocol via duck typing
    (no inheritance - see ``docs/patterns.md``). Lifecycle hooks
    are stored as plain lists; :meth:`fire_startup` and
    :meth:`fire_shutdown` invoke them when called by the agent
    runtime or the extension.

    Attributes:
        name: Always ``"flask"``.
        _config: The resolved :class:`Config` for this Flask process.
    """

    name: str = "flask"

    #: Worker-first protocol (1.2.0+) role hint. Flask agents run
    #: in gunicorn / uwsgi / waitress; default role is "web".
    default_worker_role: str = "web"

    def __init__(self, config: Config) -> None:
        self._config = config
        self._startup_hooks: list[Callable[[], None]] = []
        self._shutdown_hooks: list[Callable[[], None]] = []

    # ------------------------------------------------------------------
    # FrameworkAdapter Protocol
    # ------------------------------------------------------------------

    def discover_config(self) -> Config:
        return self._config

    def discovery_hints(self) -> DiscoveryHints:
        """Return framework-specific hints for task discovery.

        Flask does not have an app registry like Django. We return
        minimal hints - engine adapters will fall back to their own
        discovery strategy (e.g. scanning CELERY_IMPORTS).
        """
        return DiscoveryHints(framework_name="flask")

    def current_context(self) -> RequestContext | None:
        """Return the current request context, if any.

        Uses Flask's ``flask.request`` proxy when available. Never
        raises - returns None on any error.
        """
        return _current_request_context()

    def current_user(self) -> User | None:
        """Return the currently authenticated user, if any.

        Flask does not have a built-in authentication system. We
        check for ``flask_login.current_user`` if flask-login is
        installed, otherwise return None.
        """
        return _current_user()

    def on_startup(self, hook: Callable[[], None]) -> None:
        self._startup_hooks.append(hook)

    def on_shutdown(self, hook: Callable[[], None]) -> None:
        self._shutdown_hooks.append(hook)

    def register_admin_view(self, view: Any) -> None:  # noqa: ARG002
        # No admin UI embed for Flask in v1.
        return None

    # ------------------------------------------------------------------
    # Internal helpers used by the extension
    # ------------------------------------------------------------------

    def fire_startup(self) -> None:
        """Invoke every registered startup hook in order.

        Called once after the agent runtime has connected. Exceptions
        from individual hooks are caught and logged so a single bad
        hook does not abort the others.
        """
        for hook in self._startup_hooks:
            try:
                hook()
            except Exception:  # noqa: BLE001
                logger.exception("z4j flask startup hook failed")

    def fire_shutdown(self) -> None:
        """Invoke every registered shutdown hook in order.

        Called once during process shutdown. Same exception
        semantics as :meth:`fire_startup`.
        """
        for hook in self._shutdown_hooks:
            try:
                hook()
            except Exception:  # noqa: BLE001
                logger.exception("z4j flask shutdown hook failed")


# ---------------------------------------------------------------------------
# Request context helpers
# ---------------------------------------------------------------------------


def set_current_request(request: Any) -> Any:
    """Store the current request in the ContextVar. Returns the token."""
    return _current_request.set(request)


def reset_current_request(token: Any) -> None:
    """Reset the ContextVar to its previous value."""
    _current_request.reset(token)


def _current_request_context() -> RequestContext | None:
    """Build a :class:`RequestContext` from the current Flask request.

    Returns None when there is no active request or when any error
    occurs while inspecting it.
    """
    try:
        from flask import has_request_context, request
    except ImportError:
        return None

    if not has_request_context():
        return None

    try:
        user_id = _resolve_user_id()
        tenant_id = _resolve_tenant_id(request)
        request_id = _resolve_request_id(request)
        trace_id = _resolve_trace_id(request)
    except Exception:  # noqa: BLE001
        logger.debug("z4j: failed to derive request context", exc_info=True)
        return None

    return RequestContext(
        user_id=user_id,
        tenant_id=tenant_id,
        request_id=request_id,
        trace_id=trace_id,
        extra={},
    )


def _current_user() -> User | None:
    """Return the authenticated user as a :class:`z4j_core.models.User`.

    Checks for flask-login's ``current_user`` proxy. Returns None
    when flask-login is not installed, no user is logged in, or the
    user object cannot be coerced.
    """
    try:
        from flask_login import current_user as fl_current_user
    except ImportError:
        return None

    try:
        if not fl_current_user or getattr(fl_current_user, "is_anonymous", True):
            return None

        user_id = getattr(fl_current_user, "id", None) or getattr(
            fl_current_user, "pk", None,
        )
        email = getattr(fl_current_user, "email", None)
        display_name = (
            getattr(fl_current_user, "display_name", None)
            or getattr(fl_current_user, "name", None)
            or getattr(fl_current_user, "username", None)
        )

        if user_id is None:
            return None

        return User(
            id=user_id if isinstance(user_id, UUID) else str(user_id),
            email=str(email) if email else "unknown@unknown",
            display_name=str(display_name) if display_name else None,
        )
    except Exception:  # noqa: BLE001
        logger.debug("z4j: failed to resolve flask user", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Internal helpers for request context fields
# ---------------------------------------------------------------------------


def _resolve_user_id() -> UUID | str | None:
    """Extract the user ID from flask-login's current_user, if available."""
    try:
        from flask_login import current_user as fl_current_user
    except ImportError:
        return None

    try:
        if not fl_current_user or getattr(fl_current_user, "is_anonymous", True):
            return None
        pk = getattr(fl_current_user, "id", None) or getattr(
            fl_current_user, "pk", None,
        )
        if pk is None:
            return None
        if isinstance(pk, UUID):
            return pk
        return str(pk)
    except Exception:  # noqa: BLE001
        return None


def _resolve_tenant_id(request: Any) -> UUID | str | None:
    """Look for tenant info on the request or Flask's ``g`` object."""
    try:
        from flask import g
    except ImportError:
        return None

    for attr in ("tenant", "organization", "org", "workspace"):
        # Check Flask's g object first (common pattern in Flask apps).
        value = getattr(g, attr, None)
        if value is not None:
            pk = getattr(value, "pk", getattr(value, "id", value))
            if pk is None:
                continue
            if isinstance(pk, UUID):
                return pk
            return str(pk)
    return None


def _resolve_request_id(request: Any) -> str | None:
    """Extract request ID from headers."""
    for header in ("X-Request-Id", "X-Correlation-Id", "X-Amzn-Trace-Id"):
        value = request.headers.get(header)
        if value:
            return str(value)[:100]
    return None


def _resolve_trace_id(request: Any) -> str | None:
    """W3C ``traceparent`` header -> trace id."""
    traceparent = request.headers.get("traceparent")
    if not traceparent:
        return None
    parts = traceparent.split("-")
    if len(parts) >= 2:
        return parts[1][:100]
    return None


__all__ = [
    "FlaskFrameworkAdapter",
    "reset_current_request",
    "set_current_request",
]
