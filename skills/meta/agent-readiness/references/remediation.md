# Remediate assessment findings

Load this reference only after a fresh assessment and user agreement to address
its failures.

## Order and scope

Work only on findings whose status is `fail`. Sort by ascending tier, then by
descending default weight. Skip passing and inapplicable findings silently.

Use the report's remediation steps, commands, and examples. Add repository
facts discovered from the codebase, but do not invent extra remediation.

## Automatic mode

Apply self-contained fixes without prompting. Ask before a fix when it requires
project-specific input or may not apply to the repository's technology.

Skip ADR and design-intent findings in automatic mode. Record them for the final
summary because their rationale must come from a human.

When RHDH context identifies an inapplicable language or layout check, skip it
and explain that decision in the summary.

## Review mode

For every failing finding, show its tier, name, score, evidence, and remediation,
then offer `yes`, `skip`, `defer`, or `quit`.

- `yes`: apply the report-backed remediation.
- `skip`: leave it unresolved and continue.
- `defer`: include it in the post-run follow-up list.
- `quit`: stop immediately and preserve the work already completed.

For an ADR or design-intent finding, ask the user for the decision and rationale.
Write an ADR only from information they provide.

## Agent instruction files

For an `agent_instructions` failure, scan commands from `package.json`, Makefiles,
`pyproject.toml`, and CI workflow `run:` steps. Use `/rhdh-context` to pre-fill
known RHDH technology, key paths, and conventions.

For a non-RHDH repository, ask one question at a time about:

1. conventions that cannot be discovered from the code;
2. surprising architecture or file locations;
3. commit, CI, and pull-request conventions.

Write `AGENTS.md` with only supported, non-empty sections for build/test
commands, key conventions, architecture, and pull-request conventions. Include
an `Assisted-By: <model>` footer convention when agent-assisted commits require
attribution. Write `CLAUDE.md` with exactly `@AGENTS.md`.

## Verify the result

Create a new OS temporary directory and rerun:

```bash
uvx --from git+https://github.com/ambient-code/agentready agentready -- assess \
  -o <new-temporary-report-directory> \
  <repository-path>
```

Use the same user-supplied configuration, if any. Parse the fresh
`assessment-latest.json` and present:

```text
Before: <old score>/100 (<old certification>)
After:  <new score>/100 (<new certification>)
Remaining failures: <count>
```

List applied, skipped, deferred, and still-failing findings. Offer another
remediation pass when failures remain.
