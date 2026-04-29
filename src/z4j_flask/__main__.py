"""``python -m z4j_flask`` - module entry point.

Both forms work and dispatch to the same code:

    z4j-flask <subcommand>            # pip-installed console script
    python -m z4j_flask <subcommand>  # module form

The module form is what containerized deploys typically use
(predictable PATH); the console-script form is what humans type.
Both are supported in 1.1.2+.
"""

from __future__ import annotations

import sys

from z4j_flask.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
