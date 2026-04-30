# z4j-flask

[![PyPI version](https://img.shields.io/pypi/v/z4j-flask.svg)](https://pypi.org/project/z4j-flask/)
[![Python](https://img.shields.io/pypi/pyversions/z4j-flask.svg)](https://pypi.org/project/z4j-flask/)
[![License](https://img.shields.io/pypi/l/z4j-flask.svg)](https://github.com/z4jdev/z4j-flask/blob/main/LICENSE)

The Flask framework adapter for [z4j](https://z4j.com).

Adds the z4j agent into your Flask app via a one-line
`Z4J(app)` initializer. Auto-discovers the engine adapter you
have installed (Celery, RQ, Dramatiq, Huey, arq, TaskIQ) and
streams every task lifecycle event to the brain.

## Install

```bash
pip install z4j-flask z4j-celery z4j-celerybeat
```

## Documentation

Full docs at [z4j.dev/frameworks/flask/](https://z4j.dev/frameworks/flask/).

## License

Apache-2.0 — see [LICENSE](LICENSE).

## Links

- Homepage: https://z4j.com
- Documentation: https://z4j.dev
- PyPI: https://pypi.org/project/z4j-flask/
- Issues: https://github.com/z4jdev/z4j-flask/issues
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Security: security@z4j.com (see [SECURITY.md](SECURITY.md))
