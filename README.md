# z4j-flask

[![PyPI version](https://img.shields.io/pypi/v/z4j-flask.svg)](https://pypi.org/project/z4j-flask/)
[![Python](https://img.shields.io/pypi/pyversions/z4j-flask.svg)](https://pypi.org/project/z4j-flask/)
[![License](https://img.shields.io/pypi/l/z4j-flask.svg)](https://github.com/z4jdev/z4j-flask/blob/main/LICENSE)

The Flask framework adapter for [z4j](https://z4j.com).

Adds the z4j agent into your Flask app via a one-line `Z4J(app)`
initializer. Auto-discovers the engine adapter you have installed
(Celery, RQ, Dramatiq, Huey, arq, TaskIQ) and streams every task
lifecycle event to the brain. Operator control actions flow back
the same channel.

## What it ships

- **One-line install**, `Z4J(app)` and the agent connects on the
  next worker boot
- **Engine auto-discovery**, picks up whichever z4j engine adapter
  is installed alongside; cross-stack combos (Flask + RQ, Flask +
  Celery) are first-class
- **`@z4j_meta` decorator**, optional per-task annotations
  (`priority="critical"`, `description="..."`) for dashboard
  filtering and SLO display
- **Service-user safe**, auto-relocates the local outbound buffer
  to `$TMPDIR/z4j-{uid}` when `$HOME` is unwritable

## Install

```bash
pip install z4j-flask z4j-celery z4j-celerybeat
```

Wire it into your app:

```python
from flask import Flask
from z4j_flask import Z4J

app = Flask(__name__)
Z4J(app)  # reads Z4J_AGENT_TOKEN, Z4J_BRAIN_URL, Z4J_PROJECT from env
```

Mint the agent token from the dashboard's Agents page.

## Reliability

- No exception from the agent ever propagates back into Flask request
  handlers or your worker code.
- Events buffer locally when the brain is unreachable; your application
  never blocks on network I/O.

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
