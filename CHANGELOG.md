# Changelog

All notable changes to `z4j-flask` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
