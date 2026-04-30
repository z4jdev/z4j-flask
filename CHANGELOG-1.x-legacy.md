# Changelog

All notable changes to `z4j-flask` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.2] - 2026-05-01

### Added

- **Declarative scheduler reconciler**: `Z4J_SCHEDULES` (and
  optional `CELERY_BEAT_SCHEDULE` when `Z4J_RECONCILE_CELERY_BEAT=True`)
  read from `app.config` and reconciled against the brain.
- **`flask z4j-reconcile`** Click command, with `--dry-run` and
  `--json`. Auto-registered by `Z4J.init_app()`.
- Optional `Z4J_RECONCILE_AUTORUN=True` runs the reconciler from
  `Z4J.init_app()` (off by default — reconcile-from-CI is the
  recommended pattern).

## [1.2.0] - 2026-04-29

### Added

- **`FlaskFrameworkAdapter.default_worker_role = "web"`**.
  Flask agents under gunicorn / uwsgi / waitress report as
  role=`web` automatically.

### Changed

- Dependency floors: `z4j-core>=1.2.0`, `z4j-bare>=1.2.0`.


## [1.1.2] - 2026-04-28

### Added

- **`z4j-flask` console script.** Both `z4j-flask <subcommand>`
  (pip-installed entry point) and `python -m z4j_flask
  <subcommand>` (module form) work and dispatch to the same code
  path.
- **`z4j-flask check`** - compact pass/fail health check.
- **`z4j-flask status`** - one-line introspection of running z4j
  agents on this host (PID + liveness via pidfile registry).
- **`z4j-flask restart`** (alias `reload`) - sends SIGHUP to the
  running Flask agent so it drops its connection and reconnects
  immediately, skipping the supervisor's exponential backoff.

### Changed

- **Floor bumped to `z4j-bare>=1.1.2`** (was `>=1.1.0`). 1.1.2
  fixes the supervisor trapdoor + ships the pidfile + SIGHUP
  infrastructure that powers `z4j-flask restart`.

## [1.1.0] - 2026-04-28

### Changed

- **v1.1.0 ecosystem family bump.** Pinned ``z4j-core>=1.1.0`` and ``z4j-bare>=1.1.0`` so a Flask host installed at 1.1.0 always resolves a known-good 1.1.0 slice of brain + agent. The driving fix lives in z4j-bare 1.1.0: the agent dispatcher now correctly routes ``schedule.fire`` to the queue engine's ``submit_task``, instead of rejecting every brain-side scheduler tick. Operators running brain 1.1.0 + scheduler 1.1.0 with z4j-flask 1.0.x had every scheduled task silently fail at the agent - this floor refuses that mixed install.

## [1.0.3] - 2026-04-24

### Added

- **`python -m z4j_flask doctor`** - connectivity diagnostics from the same package operators already pip-installed. Wraps `z4j-bare`'s shared CLI doctor; reads `Z4J_*` env vars and runs the buffer-path / DNS / TCP / TLS / WebSocket probe ladder. Exits 0 on all-green, 1 on any failure. JSON output via `--json`.

### Changed

- Bumped minimum `z4j-core` to `>=1.0.4` and `z4j-bare` to `>=1.0.6`. Picks up the smart buffer-path fallback automatically: Flask deployments running under uwsgi/gunicorn with an unwritable `$HOME` (the `www-data` class of failure) now relocate the buffer to `$TMPDIR/z4j-{uid}/buffer-{pid}.sqlite` and log a single WARNING instead of crashing at startup.

## [1.0.1] - 2026-04-21

### Changed

- Lowered minimum Python version from 3.13 to 3.11. This package now supports Python 3.11, 3.12, 3.13, and 3.14.
- Documentation polish: standardized on ASCII hyphens across README, CHANGELOG, and docstrings for consistent rendering on PyPI.


## [1.0.0] - 2026-04

### Added

<!--
TODO: describe what ships in this first public release. One bullet per
capability. Examples:
- First public release.
- <Headline feature>
- <Second feature>
- N unit tests.
-->

- First public release.

## Links

- Repository: <https://github.com/z4jdev/z4j-flask>
- Issues: <https://github.com/z4jdev/z4j-flask/issues>
- PyPI: <https://pypi.org/project/z4j-flask/>

[Unreleased]: https://github.com/z4jdev/z4j-flask/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/z4jdev/z4j-flask/releases/tag/v1.0.0
