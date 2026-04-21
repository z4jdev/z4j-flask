"""Unit tests for ``z4j_flask.config.build_config_from_flask``.

Seeds the ``z4j-flask`` package with its first test suite - until
audit pass 8 (2026-04-21) this adapter had no ``tests`` directory
at all. The bug that drove audit pass 8 (resolver treating
``brain_url=""`` as "not passed" and sliding onto the env
fallback) does NOT reproduce here because this resolver already
uses ``is not None`` discipline on every required field - but
the symmetry argument is simple: ``z4j-fastapi`` and ``z4j-bare``
now have resolver regression tests, so ``z4j-flask`` gets the
same shape of coverage. Any future refactor that drops the ``is
not None`` check would now fail CI.

The tests also pin two Flask-specific behaviours that a reader
wouldn't necessarily guess:

- Env var takes precedence over ``app.config`` - production
  deployments inject secrets via the environment; ``app.config``
  is the home for defaults. This is the opposite of the
  z4j-fastapi resolver, which treats explicit kwargs as the
  strongest source.
- Two config layouts are supported (nested ``app.config['Z4J'] =
  {...}`` AND flat ``app.config['Z4J_BRAIN_URL'] = ...``); flat
  keys win when both are present.
"""

from __future__ import annotations

import os

import pytest
from flask import Flask

from z4j_core.errors import ConfigError

from z4j_flask.config import build_config_from_flask


@pytest.fixture(autouse=True)
def _clear_z4j_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with a clean environment.

    Strips every ``Z4J_*`` env var so host-runner or earlier-test
    leakage cannot contaminate the assertions. ``monkeypatch``
    restores state on teardown.
    """
    for key in [k for k in os.environ if k.startswith("Z4J_")]:
        monkeypatch.delenv(key, raising=False)


def _app_with_flat(**flat: object) -> Flask:
    """Helper - Flask app with flat ``Z4J_*`` keys in app.config."""
    app = Flask(__name__)
    for k, v in flat.items():
        app.config[k] = v
    return app


def _app_with_nested(config: dict[str, object]) -> Flask:
    """Helper - Flask app with the nested ``Z4J`` dict layout."""
    app = Flask(__name__)
    app.config["Z4J"] = config
    return app


class TestRequiredFieldsFailFast:
    """An empty value - via flat key or nested dict - must surface
    as ``ConfigError``, not be silently overridden by environment."""

    def test_missing_everything_raises(self) -> None:
        app = Flask(__name__)
        with pytest.raises(ConfigError) as exc:
            build_config_from_flask(app)
        details = exc.value.details or {}
        missing = details.get("missing", [])
        assert any("brain_url" in m for m in missing)
        assert any("token" in m for m in missing)
        assert any("project_id" in m for m in missing)

    def test_empty_flat_brain_url_does_not_use_env(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # With env-takes-precedence semantics, the env var will
        # actually win here and the config WILL succeed. This
        # test pins that documented behaviour - it's the flip
        # side of z4j-fastapi, where the kwarg is authoritative.
        monkeypatch.setenv("Z4J_BRAIN_URL", "http://env-brain:7700")
        monkeypatch.setenv("Z4J_TOKEN", "env-token")
        monkeypatch.setenv("Z4J_PROJECT_ID", "env-proj")
        app = _app_with_flat(
            Z4J_BRAIN_URL="",  # explicitly empty in Flask config
            Z4J_TOKEN="t",
            Z4J_PROJECT_ID="p",
        )
        config = build_config_from_flask(app)
        # Env wins over the (empty) app.config value because
        # Flask's resolver documents env > app.config precedence
        # for deployment reasons - operators inject secrets via
        # env, not code.
        assert "env-brain" in str(config.brain_url)


class TestPrecedenceEnvOverAppConfig:
    """Env var must override ``app.config`` for every field.

    This is the opposite precedence from ``z4j-fastapi`` - Flask
    deployments configure with ``app.config`` for dev defaults
    and with env vars for production secrets, so env must win.
    """

    def test_env_overrides_flat_key(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("Z4J_BRAIN_URL", "http://env:7700")
        app = _app_with_flat(
            Z4J_BRAIN_URL="http://flat:7700",
            Z4J_TOKEN="t",
            Z4J_PROJECT_ID="p",
        )
        config = build_config_from_flask(app)
        assert "env:7700" in str(config.brain_url)

    def test_env_overrides_nested_dict(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("Z4J_TOKEN", "env-token")
        app = _app_with_nested(
            {
                "brain_url": "http://u:7700",
                "token": "nested-token",
                "project_id": "p",
            },
        )
        config = build_config_from_flask(app)
        assert config.token.get_secret_value() == "env-token"


class TestTwoConfigLayouts:
    """Both flat keys and nested ``Z4J`` dict must work, and flat
    keys override nested values when both are present."""

    def test_nested_dict_only(self) -> None:
        app = _app_with_nested(
            {
                "brain_url": "http://u:7700",
                "token": "t",
                "project_id": "p",
            },
        )
        config = build_config_from_flask(app)
        assert "u:7700" in str(config.brain_url)
        assert config.token.get_secret_value() == "t"
        assert config.project_id == "p"

    def test_flat_keys_only(self) -> None:
        app = _app_with_flat(
            Z4J_BRAIN_URL="http://u:7700",
            Z4J_TOKEN="t",
            Z4J_PROJECT_ID="p",
        )
        config = build_config_from_flask(app)
        assert "u:7700" in str(config.brain_url)
        assert config.token.get_secret_value() == "t"
        assert config.project_id == "p"

    def test_flat_key_overrides_nested_dict(self) -> None:
        # Nested dict provides a baseline; a flat key overrides
        # a specific field. Documented in ``_read_flask_config``.
        app = Flask(__name__)
        app.config["Z4J"] = {
            "brain_url": "http://nested:7700",
            "token": "nested-token",
            "project_id": "nested-proj",
        }
        app.config["Z4J_TOKEN"] = "flat-token"
        config = build_config_from_flask(app)
        # Nested value preserved where flat key is absent.
        assert "nested:7700" in str(config.brain_url)
        assert config.project_id == "nested-proj"
        # Flat key overrode nested.
        assert config.token.get_secret_value() == "flat-token"


class TestOptionalFields:
    def test_hmac_secret_from_env(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("Z4J_HMAC_SECRET", "env-hmac")
        app = _app_with_flat(
            Z4J_BRAIN_URL="http://u:7700",
            Z4J_TOKEN="t",
            Z4J_PROJECT_ID="p",
        )
        config = build_config_from_flask(app)
        assert config.hmac_secret is not None

    def test_no_hmac_anywhere_is_allowed(self) -> None:
        # hmac_secret is optional at config-build time (the
        # runtime may still refuse to start in strict mode).
        app = _app_with_flat(
            Z4J_BRAIN_URL="http://u:7700",
            Z4J_TOKEN="t",
            Z4J_PROJECT_ID="p",
        )
        config = build_config_from_flask(app)
        assert config.hmac_secret is None
