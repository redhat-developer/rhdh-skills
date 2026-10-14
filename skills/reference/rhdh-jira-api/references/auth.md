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

## Adapter decision table

Choose the adapter that best fits the operation. Do not default to `acli` for every call.

| Operation | Preferred adapter | Reason |
|---|---|---|
| Single issue read with custom fields | Host adapter (`fields: ["*all"]`) | No silent empty-field trap |
| Single issue read + comments in one call | Host adapter (include `"comment"` in fields) | One round trip |
| JQL search, moderate result set | Either — host adapter up to 100/page, `acli` up to 500/page | Host adapter has no silent-truncation trap |
| JQL search, all pages (auto-walk) | `acli --paginate` | Host adapter requires manual `nextPageToken` loop |
| Issue create with priority/components | Host adapter | `acli create` rejects `--priority` and `--component` |
| Custom field write (Story Points, Size, Team, Release Note Type) | Host adapter `fields` dict | `acli` requires a REST fallback call for every custom field |
| Remote link / PR web-link attachment | Host adapter | `acli` has no equivalent |
| Comment with role/group visibility restriction | Host adapter | `acli` has no visibility control |
| Worklog | Host adapter | `acli` has no worklog commands |
| Single-issue transition | `acli` (status name accepted directly) | Host adapter requires a prior ID-lookup call |
| Batch transition by JQL | `acli --jql ... --yes` | Host adapter has no batch capability |
| Batch edit by JQL | `acli --jql ... --yes` | Host adapter has no batch capability |
| Board and sprint reads | `acli` | Host adapter exposes no board/sprint tools |
| Greenhopper sprint/board paths | Bundled token-file adapter (`scripts/greenhopper.py`) | `acli` has no verb for Greenhopper REST |
| Saved filter lookup | `acli` | Host adapter exposes no filter tools |
| Attachment list/delete | `acli` | Host adapter exposes no attachment tools |
| Confluence read/write | Host adapter | `acli` has no Confluence commands |
| Teamwork Graph cross-product links | Host adapter | `acli` cannot reach Atlas or Goals |

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
`/setup-rhdh-skills atlassian-mcp` when the missing piece is the host REST,
MCP, or GraphQL adapter rather than `acli` itself. A missing token file skips
Greenhopper only; `acli` and host adapter branches still run. After setup completes, rerun
`scripts/setup.py --json` and resume only when the capability passes.

## Non-auth errors

| Symptom | Interpretation |
|---|---|
| `acli auth status` says unauthorized but the smoke check succeeds | False negative — ignore it |
| Host REST/GraphQL/MCP adapter unavailable | Name `/setup-rhdh-skills atlassian-mcp`; `acli` branches still work |
| Token file missing or unreadable | Skip Greenhopper; reconstruct. Do not chmod the file world-readable |
| 429 response | Wait briefly and retry once; this is not a setup failure |
