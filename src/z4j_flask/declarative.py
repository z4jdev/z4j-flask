"""Flask config shim for the declarative scheduler reconciler (1.2.2+).

The reconciler logic lives in ``z4j_bare.declarative`` so all
framework adapters share it. This module is the Flask-specific
glue: it reads ``Z4J_SCHEDULES`` (and optional
``CELERY_BEAT_SCHEDULE`` if ``Z4J_RECONCILE_CELERY_BEAT=True``)
from ``app.config`` and runs one reconcile pass.

Config keys the operator can supply:

- ``Z4J_SCHEDULES``: dict of ``{name: {task, kind, expression, ...}}``
  in z4j-native shape.
- ``Z4J_RECONCILE_CELERY_BEAT`` (default ``False``): also read
  ``CELERY_BEAT_SCHEDULE`` and add the translated specs.
- ``Z4J_SCHEDULE_DEFAULT_ENGINE`` (default ``"celery"``).
- ``Z4J_SCHEDULE_OWNER`` (optional): override the project's
  ``default_scheduler_owner`` for THIS reconciler's writes.
- ``Z4J_RECONCILE_SOURCE_TAG`` (default ``"declarative:flask"``):
  the ``source`` label written on each reconciled schedule. Must
  be a value in the brain's
  ``_REPLACE_FOR_SOURCE_ALLOWLIST``. Used by
  ``mode=replace_for_source`` so the reconciler only deletes
  schedules it owns.

The reconciler is invoked:

- Manually via ``flask z4j-reconcile [--dry-run]`` (see
  :mod:`z4j_flask.cli`).
- Optionally automatically from
  :meth:`Z4J.init_app` if ``Z4J_RECONCILE_AUTORUN=True`` is set in
  ``app.config``. Auto-run is OFF by default because reconciling
  on every Flask process boot writes audit rows N times. The right
  pattern for production is reconcile from a deploy hook OR from CI.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

# Re-export the shared types for backward compatibility / convenience.
from z4j_bare.declarative import (
    ReconcileResult,
    ScheduleReconciler,
    _spec_to_brain_payload,
    _z4j_native_schedules_to_specs,
)

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger("z4j.host.flask.reconcile")


def reconcile_from_flask_app(
    app: Flask,
    *,
    dry_run: bool = False,
) -> ReconcileResult | None:
    """Read Flask ``app.config`` and run one reconcile pass.

    Returns ``None`` when no schedules are configured (silent no-op
    so we don't spam logs from a host that doesn't use the feature).

    Required config (flat or nested under ``Z4J``):
    - ``Z4J_BRAIN_URL`` / ``Z4J["brain_url"]``
    - ``Z4J_TOKEN`` / ``Z4J["token"]`` (project API key with ADMIN scope)
    - ``Z4J_PROJECT_ID`` / ``Z4J["project_id"]``

    Optional config (defaults shown):
    - ``Z4J_SCHEDULES = {}``
    - ``Z4J_RECONCILE_CELERY_BEAT = False``
    - ``Z4J_SCHEDULE_DEFAULT_ENGINE = "celery"``
    - ``Z4J_SCHEDULE_OWNER = None``  # falls back to project default
    - ``Z4J_RECONCILE_SOURCE_TAG = "declarative:flask"``
    """
    z4j_schedules = app.config.get("Z4J_SCHEDULES") or {}
    reconcile_celery = app.config.get("Z4J_RECONCILE_CELERY_BEAT", False)
    celery_beat_schedules = (
        app.config.get("CELERY_BEAT_SCHEDULE") or {}
        if reconcile_celery
        else None
    )

    if not z4j_schedules and not celery_beat_schedules:
        return None

    brain_url, api_key, project_slug = _read_brain_settings(app)
    if not (brain_url and api_key and project_slug):
        logger.warning(
            "z4j-flask reconcile: Z4J_SCHEDULES configured but "
            "brain_url, token, or project_id missing; skipping reconcile.",
        )
        return None

    engine = app.config.get("Z4J_SCHEDULE_DEFAULT_ENGINE", "celery")
    scheduler = app.config.get("Z4J_SCHEDULE_OWNER")
    source = app.config.get("Z4J_RECONCILE_SOURCE_TAG", "declarative:flask")

    reconciler = ScheduleReconciler(
        brain_url=brain_url,
        api_key=api_key,
        project_slug=project_slug,
    )
    return reconciler.reconcile(
        z4j_schedules=z4j_schedules,
        celery_beat_schedules=celery_beat_schedules,
        engine=engine,
        scheduler=scheduler,
        source=source,
        dry_run=dry_run,
    )


def _read_brain_settings(app: Flask) -> tuple[str | None, str | None, str | None]:
    """Resolve brain_url/token/project_id from flat or nested Flask config.

    Mirrors :func:`z4j_flask.config._read_flask_config`: flat keys
    win over nested ``Z4J`` dict entries.
    """
    nested = app.config.get("Z4J")
    nested = nested if isinstance(nested, dict) else {}

    brain_url = app.config.get("Z4J_BRAIN_URL") or nested.get("brain_url")
    token = app.config.get("Z4J_TOKEN") or nested.get("token")
    project_id = app.config.get("Z4J_PROJECT_ID") or nested.get("project_id")
    return brain_url, token, project_id


__all__ = [
    "ReconcileResult",
    "ScheduleReconciler",
    "_spec_to_brain_payload",
    "_z4j_native_schedules_to_specs",
    "reconcile_from_flask_app",
]
