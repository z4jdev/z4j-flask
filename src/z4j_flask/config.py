"""Build a :class:`z4j_core.models.Config` from Flask app config + env vars.

Resolution priority (highest first):

1. ``Z4J_*`` environment variables
2. ``app.config['Z4J_*']`` flat keys (idiomatic Flask)
3. ``app.config['Z4J']`` nested dict (optional)
4. Defaults declared on :class:`z4j_core.models.Config`

Why env vars beat Flask config: production deployments typically inject
secrets via the environment. Flask config is the place to declare
*defaults*; the environment is where production values land.

1.5: this module previously held ~250 lines of env-var parsing that
duplicated the same logic in z4j-django, z4j-fastapi, and z4j-bare.
The resolver now lives in :mod:`z4j_core.config.resolver`; this file
is a thin shim that flattens Flask's flat-keys + nested-dict shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from z4j_core.config import resolve_agent_config
from z4j_core.errors import ConfigError
from z4j_core.models import Config

if TYPE_CHECKING:
    from flask import Flask


# Mapping of flat ``Z4J_<UPPER_FIELD>`` keys to Config field names.
# Flask convention is uppercase keys directly on ``app.config``; we
# accept those as well as the nested dict form.
_FLAT_KEY_MAP: dict[str, str] = {
    "Z4J_BRAIN_URL": "brain_url",
    "Z4J_TOKEN": "token",
    "Z4J_PROJECT_ID": "project_id",
    "Z4J_HMAC_SECRET": "hmac_secret",
    "Z4J_AGENT_NAME": "agent_name",
    "Z4J_AGENT_ID": "agent_id",
    "Z4J_ENVIRONMENT": "environment",
    "Z4J_TRANSPORT": "transport",
    "Z4J_LOG_LEVEL": "log_level",
    "Z4J_ENGINES": "engines",
    "Z4J_SCHEDULERS": "schedulers",
    "Z4J_DEV_MODE": "dev_mode",
    "Z4J_STRICT_MODE": "strict_mode",
    "Z4J_AUTOSTART": "autostart",
    "Z4J_HEARTBEAT_SECONDS": "heartbeat_seconds",
    "Z4J_BUFFER_MAX_EVENTS": "buffer_max_events",
    "Z4J_BUFFER_MAX_BYTES": "buffer_max_bytes",
    "Z4J_MAX_PAYLOAD_BYTES": "max_payload_bytes",
    "Z4J_TAGS": "tags",
    "Z4J_WORKER_ROLE": "worker_role",
    "Z4J_DISABLED": "disabled",
}


def build_config_from_flask(app: Flask) -> Config:
    """Read Flask config + the environment, return a validated Config.

    Flask uses flat uppercase keys by convention, so we look for keys
    like ``Z4J_BRAIN_URL``, ``Z4J_TOKEN``, ``Z4J_PROJECT_ID``, etc.
    An optional ``Z4J`` dict key is also supported for grouping all
    settings under a single namespace.

    Raises:
        ConfigError: Required values are missing or invalid.
    """
    framework_overrides = _read_flask_config(app)
    return resolve_agent_config(
        framework_name="flask",
        framework_overrides=framework_overrides,
    )


def _read_flask_config(app: Flask) -> dict[str, Any]:
    """Extract z4j-related config from a Flask app.

    Supports two layouts that combine cleanly:

    1. Flat keys: ``app.config['Z4J_BRAIN_URL']``, ``app.config['Z4J_TOKEN']``, etc.
    2. Nested dict: ``app.config['Z4J'] = {'brain_url': ..., 'token': ...}``

    Flat keys override the nested dict on collision (flat is more
    specific and typically used for per-environment overrides).
    """
    result: dict[str, Any] = {}

    # Start with the nested dict if present.
    nested = app.config.get("Z4J")
    if isinstance(nested, dict):
        # Flatten nested redaction sub-dict into top-level keys for
        # the resolver, which expects redaction_* at the top level.
        redaction = nested.get("redaction") or {}
        if isinstance(redaction, dict):
            if "extra_key_patterns" in redaction:
                result["redaction_extra_key_patterns"] = list(
                    redaction["extra_key_patterns"],
                )
            if "extra_value_patterns" in redaction:
                result["redaction_extra_value_patterns"] = list(
                    redaction["extra_value_patterns"],
                )
            if "default_patterns_enabled" in redaction:
                result["redaction_defaults_enabled"] = bool(
                    redaction["default_patterns_enabled"],
                )
        for key, value in nested.items():
            if key == "redaction":
                continue
            result[key] = value

    # Flat keys override the nested dict.
    for flask_key, field_name in _FLAT_KEY_MAP.items():
        value = app.config.get(flask_key)
        if value is not None:
            result[field_name] = value

    return result


__all__ = ["build_config_from_flask"]
