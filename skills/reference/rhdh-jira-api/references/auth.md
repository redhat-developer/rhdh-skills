# Jira capability check

Detect capability here. Creating, storing, or repairing a credential belongs to
the human-invoked `/setup-rhdh-skills`, and this skill never duplicates it.

## Check

Run the local detector without printing credential contents:

```bash
uv run scripts/setup.py --json
```

Use its boolean capability fields. `token_file_found` and `token_file_status`
say whether Greenhopper REST can run. The JSON never includes file contents.

**The smoke check outranks `acli auth status`.** With API-token authentication
`acli auth status` reports unauthorized while the session works perfectly well.
Confirm with a real call before believing it:

```bash
acli jira project list --recent 1
```

If that succeeds, the session is good and the `auth status` line is a false
negative — ignore it. Do not send the user to setup on the strength of
`auth status` alone.

## API preference

1. `acli` for ordinary and bulk reads and for the mutations it supports.
2. An authenticated host Atlassian adapter for relationship-heavy GraphQL reads.
3. The bundled token-file adapter (`scripts/greenhopper.py`) for Greenhopper
   paths `acli` has no verb for. REST runs in-process; public output stays
   credential-free.
4. The host-managed REST boundary for other fields or writes `acli` cannot
   handle, when that adapter can GET an authenticated path.

The agent never reads, prints, copies, transforms, or repairs credential
material in model context. Never construct an Authorization header, a token
file, an `AUTH` shell variable, or a raw `curl` call. The adapter script may
read the local token file; it must not echo it.

## Token file (Greenhopper only)

The token file lives next to the real `acli` binary
(`Path(which("acli")).resolve().parent / ".jira-token"`), or at `JIRA_TOKEN_FILE`
when that override is set. Format is one line `email:token`. A bare token 401s.

`setup.py` warns if group or other can read the file. Keep mode `600`. Do not
`chmod 644`. If the file is owner `root` and the agent user cannot read it, the
human should `chown` it or copy it to a user path and set `JIRA_TOKEN_FILE` —
still `chmod 600`.

## Missing capability

If required Jira capability is absent, stop the affected branch, say which
capability is missing, and tell the human to run `/setup-rhdh-skills jira` — or
`/setup-rhdh-skills atlassian-mcp` when the missing piece is the host REST or
GraphQL adapter rather than `acli` itself. A missing token file skips
Greenhopper only; `acli` branches still run. After setup completes, rerun
`scripts/setup.py --json` and resume only when the capability passes.

## Non-auth errors

| Symptom | Interpretation |
|---|---|
| `acli auth status` says unauthorized but the smoke check succeeds | False negative — ignore it |
| Host REST/GraphQL adapter unavailable | Name `/setup-rhdh-skills atlassian-mcp`; `acli` branches still work |
| Token file missing or unreadable | Skip Greenhopper; reconstruct. Do not chmod the file world-readable |
| 429 response | Wait briefly and retry once; this is not a setup failure |
