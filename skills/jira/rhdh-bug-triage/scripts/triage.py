#!/usr/bin/env python3
"""Read-only triage entry point. All Jira comments remain local drafts."""

from bugtriage.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
