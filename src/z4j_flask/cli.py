"""z4j-flask CLI: ``z4j-flask <subcommand>`` and ``python -m z4j_flask``.

Inherits the full doctor/check/status/restart surface from
``z4j_bare.cli``. The only Flask-specific bit (1.1.2): the
``--adapter`` arg for ``restart``/``reload`` is pre-filled to
``flask`` so the SIGHUP routes to the flask agent's pidfile,
not the bare one.

Subcommand summary (all inherited):

- ``doctor`` - full probe ladder + JSON output option
- ``check`` - compact pass/fail
- ``status`` - one-line current state
- ``restart`` / ``reload`` - SIGHUP the flask agent's pidfile
- ``run``, ``version`` - inherited verbatim from z4j-bare

Future work: ``--app path:VAR`` flag here so doctor can also
read overrides from ``app.config["Z4J_*"]``. For now everything
flows through env vars (the 95% case).
"""

from __future__ import annotations

from z4j_bare.cli import make_main_for_adapter

main = make_main_for_adapter("flask")


__all__ = ["main"]
