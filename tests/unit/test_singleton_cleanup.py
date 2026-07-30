"""The Flask extension must UNREGISTER the process singleton when the
runtime fails to start, so a later install path can register + start a fresh
runtime instead of reusing the poisoned, never-started one."""

from __future__ import annotations

import secrets

import pytest
from flask import Flask


@pytest.fixture(autouse=True)
def _reset_singleton():
    from z4j_bare._process_singleton import clear_runtime

    clear_runtime()
    yield
    clear_runtime()


def test_start_failure_clears_singleton_r8_m5(monkeypatch: pytest.MonkeyPatch) -> None:
    from z4j_bare import _process_singleton
    from z4j_bare.runtime import AgentRuntime
    from z4j_flask import extension as ext
    from z4j_flask.extension import Z4J

    class _FakeEngine:
        name = "fake"

        def capabilities(self) -> set[str]:
            return set()

    # Ensure _do_init reaches try_register + start() with a discoverable engine.
    monkeypatch.setattr(ext, "_discover_engines", lambda app: [_FakeEngine()])
    monkeypatch.setattr(ext, "_discover_schedulers", lambda app: [])

    def _boom(self: object) -> None:
        raise RuntimeError("start blew up (transient buffer-init error)")

    monkeypatch.setattr(AgentRuntime, "start", _boom)

    app = Flask(__name__)
    app.config["Z4J_BRAIN_URL"] = "http://u:7700"
    app.config["Z4J_TOKEN"] = "test-token-12345678901234567890"
    app.config["Z4J_PROJECT_ID"] = "p"
    app.config["Z4J_HMAC_SECRET"] = secrets.token_hex(32)
    app.config["Z4J_AUTOSTART"] = True
    app.config["Z4J_DEV_MODE"] = True

    # init_app swallows the start error (logs + continues without the agent).
    Z4J(app)

    # The singleton must be empty again: a fresh registration WINS (returns its
    # own object) instead of losing to the poisoned runtime.
    sentinel = object()
    assert _process_singleton.try_register(sentinel, owner="probe") is sentinel
