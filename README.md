# z4j-flask

[![PyPI version](https://img.shields.io/pypi/v/z4j-flask.svg)](https://pypi.org/project/z4j-flask/)
[![Python](https://img.shields.io/pypi/pyversions/z4j-flask.svg)](https://pypi.org/project/z4j-flask/)
[![License](https://img.shields.io/pypi/l/z4j-flask.svg)](https://github.com/z4jdev/z4j-flask/blob/main/LICENSE)


**License:** Apache 2.0
**Status:** v1.0.0 - first public release.

Flask framework adapter for [z4j](https://z4j.com). Flask-extension
shape - one `Z4J(app)` call and the agent boots on the first request.

## Install

```bash
pip install z4j-flask z4j-celery z4j-celerybeat
```

Pick the engine adapter(s) that match your stack:

```bash
pip install z4j-flask z4j-rq z4j-rqscheduler
pip install z4j-flask z4j-dramatiq z4j-apscheduler
```

## Configure

Register the extension the standard Flask way:

```python
from flask import Flask
from z4j_flask import Z4J

app = Flask(__name__)
app.config.update(
    Z4J_BRAIN_URL="https://z4j.internal",
    Z4J_TOKEN="z4j_agent_...",        # minted in the brain dashboard
    Z4J_PROJECT_ID="my-project",
)

z4j = Z4J(app)
```

Or use the application-factory pattern:

```python
z4j = Z4J()

def create_app():
    app = Flask(__name__)
    app.config.from_envvar("FLASK_CONFIG")
    z4j.init_app(app)
    return app
```

On the first request, the agent connects to the brain and z4j's
dashboard populates with every Celery / Dramatiq task your workers
discover.

## What it does

| Piece | Purpose |
|---|---|
| `Z4J(app)` | Flask extension; hooks into the app lifecycle |
| Config from `app.config` | Reads `Z4J_*` keys - idiomatic Flask configuration |
| Lazy boot | Agent starts on first request, not at import time (so `flask --help` stays fast) |
| Teardown integration | Flushes the event buffer on `SIGTERM` / graceful shutdown |

## Reliability

`z4j-flask` follows the project-wide safety rule: **z4j never breaks
your Flask app**. Agent failures are caught at the boundary, logged, and
swallowed.

## Documentation

- [Quickstart (Flask)](https://z4j.dev/getting-started/quickstart-flask/)
- [Install guide](https://z4j.dev/getting-started/install/)
- [Architecture](https://z4j.dev/concepts/architecture/)

## License

Apache 2.0 - see [LICENSE](LICENSE). Your Flask application is never
AGPL-tainted by importing `z4j_flask`.

## Links

- Homepage: <https://z4j.com>
- Documentation: <https://z4j.dev>
- Issues: <https://github.com/z4jdev/z4j-flask/issues>
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Security: `security@z4j.com` (see [SECURITY.md](SECURITY.md))
