"""``python -m z4j_flask`` - Flask-tagged wrapper around z4j-bare's CLI.

Usage::

    python -m z4j_flask doctor
    python -m z4j_flask doctor --json

Currently every subcommand is delegated 1:1 to ``python -m z4j_bare``,
which already understands ``Z4J_*`` env vars and runs the same probe
ladder. The only reason this wrapper exists is consistency: a Flask
operator types ``python -m z4j_flask doctor`` (the package they
already pip-installed) instead of having to remember a sibling
package name.

Future work: expose ``--app PATH:VAR`` here so the doctor can also
read ``app.config["Z4J_*"]`` overrides for shops that put z4j config
in Flask's app config rather than env vars.
"""

from __future__ import annotations

import sys

from z4j_bare.cli import main


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
