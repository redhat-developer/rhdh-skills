#!/usr/bin/env python3
"""Compatibility alias for scripts/triage.py; no remote write path exists."""

from bugtriage.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
