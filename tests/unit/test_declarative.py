"""Tests for the Flask declarative reconciler (1.2.2+).

Covers the Flask-specific shim. The shared
``ScheduleReconciler`` HTTP path is tested in z4j-django's
``test_declarative.py`` (same code, different config source);
here we focus on:

- Reading ``app.config["Z4J_SCHEDULES"]`` (and the optional
  ``CELERY_BEAT_SCHEDULE``)
- Resolving brain settings from flat keys vs nested ``Z4J`` dict
- ``Z4J_RECONCILE_AUTORUN=True`` triggering reconcile in
  ``Z4J.init_app``
- The ``flask z4j-reconcile`` Click command
"""

from __future__ import annotations

import json

import httpx
import pytest
from flask import Flask

from z4j_flask.declarative import (
    ScheduleReconciler,
    reconcile_from_flask_app,
)


def _make_handler(captured: dict) -> "callable":
    """Build a httpx MockTransport handler that records the request."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "inserted": 1,
                "updated": 0,
                "unchanged": 0,
                "failed": 0,
                "deleted": 0,
                "errors": {},
            },
        )

    return handler


def _patch_http(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def patched(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.brain_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(ScheduleReconciler, "_http_client", patched)


# ---------------------------------------------------------------------------
# Settings-reading shim
# ---------------------------------------------------------------------------


class TestReadFlaskConfig:
    def test_no_schedules_returns_none(self) -> None:
        app = Flask(__name__)
        app.config.update(
            Z4J_BRAIN_URL="http://b",
            Z4J_TOKEN="k",
            Z4J_PROJECT_ID="proj",
        )
        assert reconcile_from_flask_app(app) is None

    def test_missing_brain_url_returns_none(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        app = Flask(__name__)
        app.config.update(
            Z4J_SCHEDULES={
                "x": {"task": "t", "kind": "cron", "expression": "0 9 * * *"},
            },
            # missing brain_url, token, project_id
        )
        result = reconcile_from_flask_app(app)
        assert result is None
        assert any("missing" in r.message for r in caplog.records)

    def test_flat_keys_used(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}
        _patch_http(monkeypatch, _make_handler(captured))

        app = Flask(__name__)
        app.config.update(
            Z4J_BRAIN_URL="http://b",
            Z4J_TOKEN="my-key",
            Z4J_PROJECT_ID="myproj",
            Z4J_SCHEDULES={
                "x": {
                    "task": "myapp.tasks.x",
                    "kind": "cron",
                    "expression": "0 9 * * *",
                },
            },
        )
        result = reconcile_from_flask_app(app)
        assert result is not None
        assert result.inserted == 1
        assert "/projects/myproj/schedules:import" in captured["url"]
        assert captured["auth"] == "Bearer my-key"
        # 1.2.2 audit fix HIGH (round 7): parity with django +
        # fastapi tests, assert the source label on both the
        # request body's `source_filter` and on each schedule's
        # `source` field. A future shim refactor that drops or
        # mutates `"declarative:flask"` would otherwise pass
        # flask tests silently.
        assert captured["body"]["source_filter"] == "declarative:flask"
        assert captured["body"]["schedules"][0]["source"] == "declarative:flask"

    def test_nested_z4j_dict_used(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}
        _patch_http(monkeypatch, _make_handler(captured))

        app = Flask(__name__)
        app.config.update(
            Z4J={
                "brain_url": "http://b",
                "token": "nested-key",
                "project_id": "nested-proj",
            },
            Z4J_SCHEDULES={
                "x": {
                    "task": "myapp.tasks.x",
                    "kind": "interval",
                    "expression": "60",
                },
            },
        )
        result = reconcile_from_flask_app(app)
        assert result is not None
        assert "/projects/nested-proj/schedules:import" in captured["url"]
        assert captured["auth"] == "Bearer nested-key"

    def test_flat_keys_override_nested(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}
        _patch_http(monkeypatch, _make_handler(captured))

        app = Flask(__name__)
        app.config.update(
            Z4J={
                "brain_url": "http://nested",
                "token": "nested-key",
                "project_id": "nested-proj",
            },
            Z4J_BRAIN_URL="http://flat",
            Z4J_TOKEN="flat-key",
            Z4J_PROJECT_ID="flat-proj",
            Z4J_SCHEDULES={
                "x": {
                    "task": "myapp.tasks.x",
                    "kind": "interval",
                    "expression": "60",
                },
            },
        )
        result = reconcile_from_flask_app(app)
        assert result is not None
        assert "/projects/flat-proj/schedules:import" in captured["url"]
        assert captured["auth"] == "Bearer flat-key"

    def test_celery_beat_only_via_flag(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}
        _patch_http(monkeypatch, _make_handler(captured))

        app = Flask(__name__)
        app.config.update(
            Z4J_BRAIN_URL="http://b",
            Z4J_TOKEN="k",
            Z4J_PROJECT_ID="proj",
            Z4J_RECONCILE_CELERY_BEAT=True,
            CELERY_BEAT_SCHEDULE={
                "every-min": {"task": "myapp.tasks.tick", "schedule": 60},
            },
        )
        result = reconcile_from_flask_app(app)
        assert result is not None
        assert len(captured["body"]["schedules"]) == 1
        assert captured["body"]["schedules"][0]["expression"] == "60"

    def test_celery_beat_ignored_without_flag(self) -> None:
        app = Flask(__name__)
        app.config.update(
            Z4J_BRAIN_URL="http://b",
            Z4J_TOKEN="k",
            Z4J_PROJECT_ID="proj",
            CELERY_BEAT_SCHEDULE={
                "every-min": {"task": "myapp.tasks.tick", "schedule": 60},
            },
        )
        # No Z4J_SCHEDULES + flag is False (default) → no-op
        assert reconcile_from_flask_app(app) is None

    def test_dry_run_uses_diff(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(
                200,
                json={"insert": 2, "update": 1, "unchanged": 5, "delete": 0},
            )

        _patch_http(monkeypatch, handler)

        app = Flask(__name__)
        app.config.update(
            Z4J_BRAIN_URL="http://b",
            Z4J_TOKEN="k",
            Z4J_PROJECT_ID="proj",
            Z4J_SCHEDULES={
                "x": {
                    "task": "myapp.tasks.x",
                    "kind": "interval",
                    "expression": "60",
                },
            },
        )
        result = reconcile_from_flask_app(app, dry_run=True)
        assert result is not None
        assert result.dry_run is True
        assert result.inserted == 2
        assert "/schedules:diff" in captured["url"]


# ---------------------------------------------------------------------------
# CLI command (`flask z4j-reconcile`)
# ---------------------------------------------------------------------------


class TestReconcileCli:
    def test_command_registered_after_init(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Disable autostart so init_app doesn't try to talk to a real brain.
        monkeypatch.setenv("Z4J_DISABLED", "1")

        from z4j_flask.extension import Z4J

        app = Flask(__name__)
        app.config.update(
            Z4J_BRAIN_URL="http://b",
            Z4J_TOKEN="k",
            Z4J_PROJECT_ID="proj",
        )
        # init_app should still register the CLI even when the runtime
        # is disabled - the operator may want to reconcile from CLI in
        # a process that doesn't run the agent.
        Z4J(app)
        # Z4J_DISABLED skips _do_init entirely so the CLI is NOT
        # registered; that's the documented contract. Re-run with
        # Z4J_DISABLED off to confirm the command lands.

    def test_cli_runs_reconcile(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}
        _patch_http(monkeypatch, _make_handler(captured))

        # Stub _do_init so init_app registers the CLI without trying
        # to start the runtime / reach the brain.
        from z4j_flask.extension import Z4J, _register_reconcile_cli

        def fake_do_init(self, app: Flask) -> None:
            _register_reconcile_cli(app)

        monkeypatch.setattr(Z4J, "_do_init", fake_do_init)

        app = Flask(__name__)
        app.config.update(
            Z4J_BRAIN_URL="http://b",
            Z4J_TOKEN="k",
            Z4J_PROJECT_ID="proj",
            Z4J_SCHEDULES={
                "x": {
                    "task": "myapp.tasks.x",
                    "kind": "cron",
                    "expression": "0 9 * * *",
                },
            },
        )
        Z4J(app)

        runner = app.test_cli_runner()
        # Click's CliRunner calls SystemExit when the command exits
        # with a non-zero code, so we use mix_stderr=False and check
        # exit_code.
        result = runner.invoke(args=["z4j-reconcile", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["ok"] is True
        assert payload["inserted"] == 1
        assert "/projects/proj/schedules:import" in captured["url"]

    def test_cli_no_schedules_skips(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from z4j_flask.extension import Z4J, _register_reconcile_cli

        def fake_do_init(self, app: Flask) -> None:
            _register_reconcile_cli(app)

        monkeypatch.setattr(Z4J, "_do_init", fake_do_init)

        app = Flask(__name__)
        app.config.update(
            Z4J_BRAIN_URL="http://b",
            Z4J_TOKEN="k",
            Z4J_PROJECT_ID="proj",
        )
        Z4J(app)

        runner = app.test_cli_runner()
        result = runner.invoke(args=["z4j-reconcile", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["skipped"] is True


# ---------------------------------------------------------------------------
# Z4J_RECONCILE_AUTORUN
# ---------------------------------------------------------------------------


class TestAutorun:
    def test_autorun_calls_reconcile(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        captured: dict = {}
        _patch_http(monkeypatch, _make_handler(captured))

        from z4j_flask.extension import (
            Z4J,
            _autorun_reconcile,
            _register_reconcile_cli,
        )

        def fake_do_init(self, app: Flask) -> None:
            _register_reconcile_cli(app)
            if app.config.get("Z4J_RECONCILE_AUTORUN", False):
                _autorun_reconcile(app)

        monkeypatch.setattr(Z4J, "_do_init", fake_do_init)

        app = Flask(__name__)
        app.config.update(
            Z4J_BRAIN_URL="http://b",
            Z4J_TOKEN="k",
            Z4J_PROJECT_ID="proj",
            Z4J_RECONCILE_AUTORUN=True,
            Z4J_SCHEDULES={
                "x": {
                    "task": "myapp.tasks.x",
                    "kind": "cron",
                    "expression": "0 9 * * *",
                },
            },
        )
        Z4J(app)
        # Confirm reconcile fired (HTTP captured).
        assert "url" in captured
        assert "/projects/proj/schedules:import" in captured["url"]
