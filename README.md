# z4j-flask

[![PyPI version](https://img.shields.io/pypi/v/z4j-flask.svg)](https://pypi.org/project/z4j-flask/)
[![Python](https://img.shields.io/pypi/pyversions/z4j-flask.svg)](https://pypi.org/project/z4j-flask/)
[![License](https://img.shields.io/pypi/l/z4j-flask.svg)](https://github.com/z4jdev/z4j-flask/blob/main/LICENSE)

The Flask framework adapter for [z4j](https://z4j.com).

Adds the z4j agent into your Flask app via a one-line `Z4J(app)`
initializer. It registers installed engine adapters only when their required
native handles are configured on the Flask app (`CELERY_APP`, `RQ_APP` or
`RQ_REDIS_URL`, `ARQ_REDIS_SETTINGS`, `HUEY`, or `TASKIQ_BROKER`). Dramatiq can
instead use a process-global broker that already has registered actors.

## Compatibility

- Flask 3.1.3+ (no upper cap)
- Python 3.11+

Pair with an engine adapter (`z4j-celery`, `z4j-rq`, `z4j-dramatiq`, `z4j-huey`, `z4j-arq`, `z4j-taskiq`); each engine adapter carries its own upstream floor.

Full per-adapter matrix at <https://z4j.dev/reference/compatibility/>.

## What it ships

- **One-line install**, `Z4J(app)` and the agent connects on the
  next worker boot
- **Configured engine discovery**, supports multiple installed adapters when
  each adapter's required native handle is present in Flask config
- **TaskIQ middleware discovery**, `TASKIQ_BROKER` attaches z4j capture without
  guessing an event loop; TaskIQ broker startup binds its actual owner loop
- **Per-task metadata from supporting engine adapters**; `z4j-celery`,
  `z4j-rq`, and `z4j-dramatiq` expose `@z4j_meta` rather than this framework
  package defining one
- **Service-user safe**, auto-relocates the local outbound buffer
  to `$TMPDIR/z4j-{uid}` when `$HOME` is unwritable

## Install

```bash
pip install z4j-flask z4j-celery z4j-celerybeat
```

Wire it into your app:

```python
from flask import Flask
from myproject.celery import app as celery_app
from z4j_flask import Z4J

app = Flask(__name__)
app.config["CELERY_APP"] = celery_app
Z4J(app)  # reads Z4J_TOKEN, Z4J_HMAC_SECRET, Z4J_BRAIN_URL, Z4J_PROJECT_ID
```

Mint the agent from the dashboard's Agents page and retain both values it shows:
the bearer token and the HMAC secret.

For `TASKIQ_BROKER`, initialize `Z4J(app)` before the component that starts the
broker. Flask discovery attaches the middleware, and TaskIQ's real broker
startup binds its owner loop. A separate TaskIQ worker process still needs its
own agent and must attach before the TaskIQ CLI starts the broker.

## Reliability

- Agent startup and delivery failures are logged and isolated from Flask
  request handlers and worker code; capture hooks make no brain network request
  inline.
- Engine event queues and the SQLite outbound buffer are bounded. Queue
  overflow drops new events and buffer pressure evicts oldest rows; both losses
  are logged.

## Documentation

Full docs at [z4j.dev/frameworks/flask/](https://z4j.dev/frameworks/flask/).

## License

Apache-2.0, see [LICENSE](LICENSE).

## Links

- Homepage: https://z4j.com
- Documentation: https://z4j.dev
- PyPI: https://pypi.org/project/z4j-flask/
- Issues: https://github.com/z4jdev/z4j-flask/issues
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Security: security@z4j.com (see [SECURITY.md](SECURITY.md))
