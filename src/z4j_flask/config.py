"""Build a :class:`z4j_core.models.Config` from Flask app config + env vars.

Resolution priority (highest first):

1. ``Z4J_*`` environment variables
2. ``app.config['Z4J_*']`` keys in the Flask app's configuration
3. Defaults declared on :class:`z4j_core.models.Config`

Why env vars beat Flask config: production deployments typically inject
secrets via the environment. Flask config is the place to declare
*defaults*; the environment is where production values land.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from z4j_core.errors import ConfigError
from z4j_core.models import Config

if TYPE_CHECKING:
    from flask import Flask


def build_config_from_flask(app: Flask) -> Config:
    """Read ``app.config['Z4J_*']`` and the environment, return a validated Config.

    Flask uses flat uppercase keys by convention, so we look for keys
    like ``Z4J_BRAIN_URL``, ``Z4J_TOKEN``, ``Z4J_PROJECT_ID``, etc.
    An optional ``Z4J`` dict key is also supported for grouping all
    settings under a single namespace (similar to the Django adapter).

    Raises:
        ConfigError: Required values are missing or invalid.
    """
    raw_dict = _read_flask_config(app)
    resolved = _resolve(raw_dict)
    try:
        return Config(**resolved)
    except ValidationError as exc:
        # Redact values - only surface field locations + error types.
        details = [
            {
                "loc": ".".join(str(p) for p in err["loc"]),
                "type": err["type"],
            }
            for err in exc.errors()
        ]
        raise ConfigError(
            f"invalid Z4J configuration ({len(details)} field(s))",
            details={"errors": details},
        ) from None
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"invalid Z4J configuration: {type(exc).__name__}",
        ) from None


def _read_flask_config(app: Flask) -> dict[str, Any]:
    """Extract z4j-related config from a Flask app.

    Supports two layouts:

    1. Flat keys: ``app.config['Z4J_BRAIN_URL']``, ``app.config['Z4J_TOKEN']``, etc.
    2. Nested dict: ``app.config['Z4J'] = {'brain_url': ..., 'token': ...}``

    The flat keys are preferred (idiomatic Flask). If the nested dict
    is present, its values serve as a base that the flat keys override.
    """
    result: dict[str, Any] = {}

    # Start with the nested dict if present.
    nested = app.config.get("Z4J")
    if isinstance(nested, dict):
        result.update(nested)

    # Flat keys override the nested dict. Strip the ``Z4J_`` prefix
    # and lowercase the remainder to match Config field names.
    _flat_override(result, app.config, "Z4J_BRAIN_URL", "brain_url")
    _flat_override(result, app.config, "Z4J_TOKEN", "token")
    _flat_override(result, app.config, "Z4J_PROJECT_ID", "project_id")
    _flat_override(result, app.config, "Z4J_HMAC_SECRET", "hmac_secret")
    _flat_override(result, app.config, "Z4J_ENVIRONMENT", "environment")
    _flat_override(result, app.config, "Z4J_TRANSPORT", "transport")
    # Long-poll agent UUID - required by Config when transport='longpoll'.
    # Audit 2026-04-24 Medium-2.
    _flat_override(result, app.config, "Z4J_AGENT_ID", "agent_id")
    _flat_override(result, app.config, "Z4J_LOG_LEVEL", "log_level")
    _flat_override(result, app.config, "Z4J_ENGINES", "engines")
    _flat_override(result, app.config, "Z4J_SCHEDULERS", "schedulers")
    _flat_override(result, app.config, "Z4J_DEV_MODE", "dev_mode")
    _flat_override(result, app.config, "Z4J_STRICT_MODE", "strict_mode")
    _flat_override(result, app.config, "Z4J_AUTOSTART", "autostart")
    _flat_override(result, app.config, "Z4J_HEARTBEAT_SECONDS", "heartbeat_seconds")
    _flat_override(result, app.config, "Z4J_BUFFER_MAX_EVENTS", "buffer_max_events")
    _flat_override(result, app.config, "Z4J_BUFFER_MAX_BYTES", "buffer_max_bytes")
    _flat_override(result, app.config, "Z4J_MAX_PAYLOAD_BYTES", "max_payload_bytes")
    _flat_override(result, app.config, "Z4J_BUFFER_PATH", "buffer_path")
    _flat_override(result, app.config, "Z4J_TAGS", "tags")
    _flat_override(result, app.config, "Z4J_DISABLED", "disabled")

    return result


def _flat_override(
    result: dict[str, Any],
    flask_config: Any,
    flask_key: str,
    config_key: str,
) -> None:
    """Copy a flat Flask config key into the result dict if present."""
    value = flask_config.get(flask_key)
    if value is not None:
        result[config_key] = value


def _resolve(settings_dict: dict[str, Any]) -> dict[str, Any]:
    """Merge env vars on top of the Flask config dict + report missing required keys."""
    env = os.environ
    resolved: dict[str, Any] = {}

    # Required fields.
    brain_url = (
        env.get("Z4J_BRAIN_URL")
        if env.get("Z4J_BRAIN_URL") is not None
        else settings_dict.get("brain_url")
    )
    token = (
        env.get("Z4J_TOKEN")
        if env.get("Z4J_TOKEN") is not None
        else settings_dict.get("token")
    )
    project_id = (
        env.get("Z4J_PROJECT_ID")
        if env.get("Z4J_PROJECT_ID") is not None
        else settings_dict.get("project_id")
    )

    missing: list[str] = []
    if not brain_url:
        missing.append("brain_url (or Z4J_BRAIN_URL)")
    if not token:
        missing.append("token (or Z4J_TOKEN)")
    if not project_id:
        missing.append("project_id (or Z4J_PROJECT_ID)")
    if missing:
        raise ConfigError(
            "missing required Z4J settings: " + ", ".join(missing),
            details={"missing": missing},
        )

    resolved["brain_url"] = brain_url
    resolved["token"] = token
    resolved["project_id"] = project_id

    # HMAC secret
    hmac_secret = env.get("Z4J_HMAC_SECRET") or settings_dict.get("hmac_secret")
    if hmac_secret:
        resolved["hmac_secret"] = hmac_secret

    # Optional fields with env override
    _maybe_set(resolved, settings_dict, env, "environment", "Z4J_ENVIRONMENT")
    _maybe_set(resolved, settings_dict, env, "transport", "Z4J_TRANSPORT")
    # Long-poll agent UUID - required by Config when transport='longpoll'.
    # Audit 2026-04-24 Medium-2.
    _maybe_set(resolved, settings_dict, env, "agent_id", "Z4J_AGENT_ID")
    _maybe_set(resolved, settings_dict, env, "log_level", "Z4J_LOG_LEVEL")

    if "engines" in settings_dict:
        resolved["engines"] = settings_dict["engines"]
    elif "Z4J_ENGINES" in env:
        resolved["engines"] = [
            x.strip() for x in env["Z4J_ENGINES"].split(",") if x.strip()
        ]

    if "schedulers" in settings_dict:
        resolved["schedulers"] = settings_dict["schedulers"]
    elif "Z4J_SCHEDULERS" in env:
        resolved["schedulers"] = [
            x.strip() for x in env["Z4J_SCHEDULERS"].split(",") if x.strip()
        ]

    if "tags" in settings_dict and isinstance(settings_dict["tags"], dict):
        resolved["tags"] = settings_dict["tags"]

    # Booleans
    _maybe_set_bool(resolved, settings_dict, env, "dev_mode", "Z4J_DEV_MODE")
    _maybe_set_bool(resolved, settings_dict, env, "strict_mode", "Z4J_STRICT_MODE")
    _maybe_set_bool(resolved, settings_dict, env, "autostart", "Z4J_AUTOSTART")

    # Integers
    _maybe_set_int(
        resolved, settings_dict, env, "heartbeat_seconds", "Z4J_HEARTBEAT_SECONDS",
    )
    _maybe_set_int(
        resolved, settings_dict, env, "buffer_max_events", "Z4J_BUFFER_MAX_EVENTS",
    )
    _maybe_set_int(
        resolved, settings_dict, env, "buffer_max_bytes", "Z4J_BUFFER_MAX_BYTES",
    )
    _maybe_set_int(
        resolved, settings_dict, env, "max_payload_bytes", "Z4J_MAX_PAYLOAD_BYTES",
    )

    # Path - clamped to the agent's allowed buffer roots
    # (``~/.z4j`` / ``$TMPDIR/z4j-{uid}``). Audit 2026-04-24 Low-2.
    from z4j_bare.storage import clamp_buffer_path

    raw_buffer_path: Path | None = None
    if "buffer_path" in settings_dict:
        raw_buffer_path = Path(settings_dict["buffer_path"])
    elif "Z4J_BUFFER_PATH" in env:
        raw_buffer_path = Path(env["Z4J_BUFFER_PATH"])
    if raw_buffer_path is not None:
        try:
            resolved["buffer_path"] = clamp_buffer_path(raw_buffer_path)
        except ValueError as exc:
            raise ConfigError(str(exc)) from None

    # Redaction nested dict
    redaction = settings_dict.get("redaction") or {}
    if isinstance(redaction, dict):
        if "extra_key_patterns" in redaction:
            resolved["redaction_extra_key_patterns"] = list(
                redaction["extra_key_patterns"],
            )
        if "extra_value_patterns" in redaction:
            resolved["redaction_extra_value_patterns"] = list(
                redaction["extra_value_patterns"],
            )
        if "default_patterns_enabled" in redaction:
            resolved["redaction_defaults_enabled"] = bool(
                redaction["default_patterns_enabled"],
            )

    return resolved


def _maybe_set(
    resolved: dict[str, Any],
    settings_dict: dict[str, Any],
    env: dict[str, str] | os._Environ[str],
    key: str,
    env_key: str,
) -> None:
    if env_key in env:
        resolved[key] = env[env_key]
    elif key in settings_dict:
        resolved[key] = settings_dict[key]


def _maybe_set_bool(
    resolved: dict[str, Any],
    settings_dict: dict[str, Any],
    env: dict[str, str] | os._Environ[str],
    key: str,
    env_key: str,
) -> None:
    if env_key in env:
        resolved[key] = env[env_key].strip().lower() in ("1", "true", "yes", "on")
    elif key in settings_dict:
        resolved[key] = bool(settings_dict[key])


def _maybe_set_int(
    resolved: dict[str, Any],
    settings_dict: dict[str, Any],
    env: dict[str, str] | os._Environ[str],
    key: str,
    env_key: str,
) -> None:
    if env_key in env:
        try:
            resolved[key] = int(env[env_key])
        except ValueError as exc:
            raise ConfigError(f"{env_key} must be an integer: {exc}") from exc
    elif key in settings_dict:
        resolved[key] = int(settings_dict[key])


__all__ = ["build_config_from_flask"]
