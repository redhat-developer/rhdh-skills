# Jira authenticated API fallback

Use this seam when `acli` cannot read or update a required Jira field **and** the host adapter does
not expose a native tool for it. This reference defines payload semantics; it never owns credentials
or raw HTTP authentication.

## Capability gate

1. Check the adapter decision table in [auth.md](auth.md). Many operations that formerly required
   a REST fallback are now native host-adapter (MCP) tool calls — prefer those first.
2. If the host adapter exposes no matching tool, use REST through the already-authenticated host
   Atlassian adapter. The adapter owns the site, credential store, request headers, retries, and
   secret redaction.
3. If that adapter is unavailable, say which field could not be set and tell the human to run
   `/setup-rhdh-skills atlassian-mcp`.

Do not create token files, shell `AUTH` variables, Authorization headers, or credential-bearing
request previews. Do not fall back from a native tool to raw `curl`.

## Supported semantic operations

| Operation | Request semantics | Expected result |
|---|---|---|
| Read all fields | Get issue by key with `fields=*all` | Issue object |
| Discover fields | List Jira fields | Field IDs, types, and names |
| Check editability | Get edit metadata for an issue | Allowed operations and values |
| Update fields | Partial issue update with a `fields` object | No-content success or updated issue |
| Add comment | Add an ADF comment, with visibility when required | Comment receipt |
| Add remote link | Attach a web link to an issue key with `{"object": {"url": ..., "title": ...}}` | Created link with an id, or the id of the link it replaced |

The host adapter may expose these as tools instead of URL paths. Select by semantic capability, not
by tool name, and keep transport-specific response metadata out of what you report.

## Remote links

A remote link is the "web link" shown on a Jira issue. It is the supported way to record an
external URL — a pull request, a design document, a support case — against an issue, and `acli`
has no equivalent, so the authenticated adapter owns it.

```json
{"object": {"url": "https://github.com/redhat-developer/rhdh/pull/1234", "title": "GitHub PR: Fix plugin loader"}}
```

The target is the issue key; `object.url` and `object.title` are the whole payload. A second link
carrying the same URL replaces the first rather than creating a duplicate, so re-running after a
partial failure is safe. Report the link id the adapter returns.

A caller handing over a pull request usually wants three writes at once — a comment, a transition
to `Review`, and a remote link to the PR URL. Present all three together so a single approval
covers the set. `/rhdh-jira-update` owns that flow.

## Custom-field payloads

> **Prefer the host adapter's native edit tool.** When a `editJiraIssue`-equivalent tool is
> available, pass custom fields directly in its `fields` dict — no REST call needed. The payloads
> below are the raw REST form; use them only when no native tool covers the operation.

```json
{"fields": {"customfield_10028": 5}}
```

Story Points is numeric.

```json
{"fields": {"customfield_10795": {"value": "M"}}}
```

Size is a select value: `XS`, `S`, `M`, `L`, or `XL`.

```json
{"fields": {"customfield_10001": {"id": "TEAM_ID"}}}
```

Team uses an Atlassian team ID. Discover it from an existing issue through the authenticated
adapter; never guess it.

```json
{"fields": {"customfield_10785": {"value": "Enhancement"}}}
```

Release Note Type is a select value. Allowed values include `Feature`, `Enhancement`,
`Developer Preview`, `Deprecated Functionality`, `Removed Functionality`, and
`Release Note Not Required`.

## Write boundary

A REST-backed write is an external write, so the skill that owns the verb invokes
`/mutation-gate` and follows it. Two details are specific to REST here: the operation's
preview is the full JSON payload rather than a command line, and the outcome is read back from the
changed fields rather than taken from the response, because a request the API accepts can still
leave a field unset.

## Response handling

| Result | Action |
|---|---|
| Validation failure | Re-read field metadata, correct the payload, and re-confirm if it changed |
| Unauthenticated | Name `/setup-rhdh-skills atlassian-mcp`; do not inspect or repair credentials here |
| Forbidden | Report the missing permission; do not retry with another identity |
| Not found | Verify the issue key before retrying |
| Rate limited | Honor the adapter retry delay and retry once |

REST search is not a fallback for bulk JQL in this skill. Use `acli --paginate` or the authenticated
GraphQL adapter instead.
