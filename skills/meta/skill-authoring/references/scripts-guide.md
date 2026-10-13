# Scripts Guide

Full guide: <https://agentskills.io/skill-creation/using-scripts>

## Default to Scripts

**Scripts are cheaper, faster, and more reliable than LLM instructions.** Every deterministic operation in a skill should be a script. For each step in a workflow, ask: "Could a script do this?" If yes, write the script. Only leave genuine judgment calls to instructions.

A skill that validates input, generates files from templates, and calls APIs should have scripts for all three — the SKILL.md just orchestrates when to call them and handles the decisions between steps.

Keep instructions for:

- Creative or exploratory reasoning
- Decisions that depend on ambiguous context
- Explaining tradeoffs to the user
- Tasks where the right approach varies significantly case-by-case

## Directory Convention

```
skill-name/
└── scripts/
    ├── validate.py
    ├── format-output.sh
    └── setup.py
```

## Making Scripts Executable

### Shebang lines

Every script needs a shebang so it can run directly:

```python
#!/usr/bin/env python3
```

```bash
#!/usr/bin/env bash
```

### Cross-platform compatibility

Skills run on macOS, Windows, and Linux. Write scripts that work on all three:

- Use `#!/usr/bin/env python3` (not a hardcoded path). On Windows, agents call `python script.py` instead of `./script.py`.
- **Temp directories**: Use `tempfile.mkdtemp()` or `tempfile.TemporaryDirectory()`, never hardcode `/tmp`. Windows uses `C:\Users\<user>\AppData\Local\Temp`.
- **Path separators**: Use `pathlib.Path` or `os.path.join()`, never hardcode `/` in paths.
- **Line endings**: Use `newline=""` when opening files for CSV/structured output. Don't assume `\n`.
- **Shell commands**: If a script calls external tools, document the platform differences or use Python stdlib equivalents.
- **subprocess on Windows**: Tools installed via npm/yarn often resolve to `.cmd` shims. Resolve the
  native runtime and JavaScript entry point, then keep structured argv with `shell=False`. Never join
  user input into a command string:

  ```python
  node = shutil.which("node")
  npx_cli = resolve_npx_cli()  # validated path owned by the adapter
  subprocess.run([node, npx_cli, "skills", "add", source], shell=False, check=True)
  ```

```python
import tempfile
from pathlib import Path

# Good — works everywhere
work_dir = Path(tempfile.mkdtemp(prefix="skill-"))
output = work_dir / "result.json"

# Bad — breaks on Windows
work_dir = "/tmp/skill-output"
```

## Python Scripts

### Without dependencies (preferred)

Use stdlib only. Use `argparse` for argument parsing:

```python
#!/usr/bin/env python3
"""Validate workspace configuration."""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="Validate workspace config")
    parser.add_argument("path", help="Path to workspace directory")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # ... validation logic ...

    if args.json:
        json.dump(result, sys.stdout)
    else:
        print(f"Validation: {'PASS' if result['valid'] else 'FAIL'}")

    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
```

### YAML round-trip exception (PEP 723)

Bundled scripts stay stdlib-only, because every dependency is one more thing that has to be present
on the user's machine for the installed skill to run. The one exception worth taking is comment- and
order-preserving YAML round-tripping with `ruamel.yaml`, which stdlib cannot do:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "ruamel.yaml",
# ]
# ///

"""Round-trip a repository YAML file without losing comments."""
# ...
```

Run with `uv run --script scripts/update_yaml.py`. Do not add other PEP 723 dependencies without a
recorded decision that moves the portability boundary for the whole collection.

## Host linter

Leave bundled Python in the style the host repository already enforces. Run that
formatter and linter on every changed `.py` file before the skill is complete,
before a commit, and before a pull request. A lint `check` passing is not enough
when the host also formats.

When the host uses ruff via uv:

```bash
uv run ruff format path/to/changed.py
uv run ruff check path/to/changed.py
```

Do not invent a private quote or import style that the formatter will rewrite.

## Designing for Agents

Scripts invoked by agents should follow these patterns:

### Respect NO_COLOR

Honor the [NO_COLOR](https://no-color.org/) standard. Check both TTY status and the environment variable:

```python
import os
import sys

_no_color = os.environ.get("NO_COLOR") is not None
_is_tty = sys.stdout.isatty() and not _no_color
```

**Gotcha: check the right stream.** If the script logs to `stderr` (common when `--json` output goes to `stdout`), check `sys.stderr.isatty()` — not `sys.stdout.isatty()`. Otherwise ANSI codes get disabled for terminal stderr output when stdout is piped.

```python
# Script logs to stderr, JSON to stdout
_is_tty = sys.stderr.isatty() and not _no_color
```

### Structured output

Return JSON when piped, human-readable when in a terminal:

```python
import sys
import json

if sys.stdout.isatty():
    print(f"Found {count} issues")
else:
    json.dump({"count": count, "issues": issues}, sys.stdout)
```

### Clear exit codes

- `0` = success
- `1` = expected failure (validation failed, no results)
- `2` = usage error (bad arguments)

### Helpful --help

The agent reads `--help` to understand flags. Make it descriptive:

```python
parser.add_argument(
    "--strict", action="store_true", help="Treat warnings as errors. Use for CI checks."
)
```

### Idempotent operations

Scripts should be safe to re-run. Don't assume fresh state.
