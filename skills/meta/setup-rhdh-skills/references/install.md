# Install or repair the complete collection

The primary path installs the official `RHDH complete` skills.sh pack. The catalog is the local
source of truth for the promoted skill set and its three required external dependencies.

1. State the installation plan:

   ```bash
   uv run scripts/setup.py install-plan --agent <agent-id> --scope global --json
   ```

   Use `--pack-url <url>` to bootstrap a release before its URL is recorded in the catalog. When no
   pack URL exists, the script states an equivalent repository-install fallback plan.

2. Take that plan through `/mutation-gate`: one table row per operation. After the user
   approves it, save the exact plan JSON to a file in the temporary directory and run it:

   ```bash
   uv run scripts/setup.py apply --plan <plan.json> --confirm --json
   ```

   Without `--confirm` the script runs nothing and reports `NOT_CONFIRMED`.

3. Report every operation's outcome, including any reported as skipped after a failure.
4. Run `uv run scripts/setup.py doctor --json`. Repair only the skills still reported missing.
5. Ask the user to restart or rescan the agent so newly installed descriptions are loaded.
6. **Seed OpenSpec into the current product repo (when applicable).** If the
   working directory is a product checkout that will use OpenSpec changes, and
   either `openspec/config.yaml` or `openspec/schemas/rhdh-spec-driven/` is
   missing, invoke `/rhdh-spec-driven-schema` and run its project-install step.
   Take the copy through `/mutation-gate`. Skip when both already exist, or
   when the user is only installing skills globally with no product repo in
   scope — the openspec-* skills also check and install at startup when needed.

The script validates every operation before running the first one and executes argument arrays
directly without a command shell. If validation fails, no installation operation runs.

Completion requires all promoted skills, `grilling`, `code-review`, and `handoff` to be discovered in a
supported host layout.
