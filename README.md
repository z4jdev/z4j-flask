# z4j-flask

[![PyPI version](https://img.shields.io/pypi/v/z4j-flask.svg)](https://pypi.org/project/z4j-flask/)
[![Python](https://img.shields.io/pypi/pyversions/z4j-flask.svg)](https://pypi.org/project/z4j-flask/)
[![License](https://img.shields.io/pypi/l/z4j-flask.svg)](https://github.com/z4jdev/z4j-flask/blob/main/LICENSE)


**License:** Apache 2.0

Flask framework adapter for [z4j](https://z4j.com). Flask-extension
shape - one `Z4J(app)` call and the agent boots on the first request.

## Install

Pick your task engine and install with the matching extra. Each extra
pulls the engine adapter AND its companion scheduler in one shot, so
a fresh install never needs a second command.

```bash
pip install z4j-flask[celery]       # Celery + celery-beat
pip install z4j-flask[rq]           # RQ + rq-scheduler
pip install z4j-flask[dramatiq]     # Dramatiq + APScheduler
pip install z4j-flask[huey]         # Huey + huey-periodic
pip install z4j-flask[arq]          # arq + arq-cron
pip install z4j-flask[taskiq]       # TaskIQ + taskiq-scheduler
pip install z4j-flask[all]          # every engine (CI / kitchen sink)
```

`pip install z4j-flask` (no extra) installs only the framework adapter.
That's useful if you already manage engine packages elsewhere; otherwise
always pick an engine extra.

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
