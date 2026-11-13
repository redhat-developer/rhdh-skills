#!/usr/bin/env python3
"""Entry point for the read-only RHDH aged-bug triage skill.

    python scripts/run_poc.py --help

No subcommand writes to Jira, GitHub, or any remote. See TESTING.md for a
fixture walkthrough and SKILL.md for the workflow.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bugtriage.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
