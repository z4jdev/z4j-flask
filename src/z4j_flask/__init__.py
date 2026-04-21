"""z4j-flask - Flask framework adapter for z4j.

Public API:

- :class:`Z4J` - Flask extension that manages the agent runtime.
  Supports both eager init (``Z4J(app)``) and the lazy application
  factory pattern (``z4j.init_app(app)``).
- :class:`FlaskFrameworkAdapter` - the framework adapter implementation.
- :func:`build_config_from_flask` - read ``app.config`` + env vars.

End users typically just create the extension and call ``init_app``::

    from flask import Flask
    from z4j_flask import Z4J

    app = Flask(__name__)
    z4j = Z4J(app)

Licensed under Apache License 2.0.
"""

from __future__ import annotations

from z4j_flask.config import build_config_from_flask
from z4j_flask.extension import Z4J
from z4j_flask.framework import FlaskFrameworkAdapter

# See z4j_fastapi.__init__ for the rationale. Importing z4j_celery
# (if installed) registers the worker_init signal so Flask apps
# that run Celery workers get first-class agent registration.
try:
    import z4j_celery  # noqa: F401  (imported for its side-effects)
except ImportError:
    pass

__version__ = "1.0.0"

__all__ = [
    "FlaskFrameworkAdapter",
    "Z4J",
    "__version__",
    "build_config_from_flask",
]
