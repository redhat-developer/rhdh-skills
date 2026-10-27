# Jira input and handoff

Resolve Jira input locally with your Jira tool, then compose the handoff.
This skill does not authenticate to Jira or select among `acli`, REST, GraphQL,
or MCP.

## Parse a Jira reference

Accept these formats and normalize them to a key and browse URL:

| Input | Example | Extraction |
|---|---|---|
| Bare key | `RHDHBUGS-1934` | Match directly |
| Browse URL | `https://redhat.atlassian.net/browse/RHDHBUGS-1934` | Take the segment after `/browse/` |
| URL without scheme | `redhat.atlassian.net/browse/RHIDP-15252` | Take the segment after `/browse/` |
| URL with query or fragment | `https://redhat.atlassian.net/browse/RHIDP-15252?focusedId=123` | Strip query and fragment |

1. If the input contains `atlassian.net/browse/`, extract the next path
   segment.
2. Otherwise, scan for
   `(RHIDP|RHDHBUGS|RHDHPLAN|RHDHSUPP)-\d+`.
3. Reject input that matches neither form.
4. Construct the canonical browse URL from the normalized key; do not retain a
   query string or fragment.

## Read handoff

When the caller did not provide Jira context, read the issue with your Jira
tool and consume the detail:

```json
{
  "key": "ISSUE-123",
  "summary": "Issue summary",
  "source": "jira",
  "url": "https://redhat.atlassian.net/browse/RHDHBUGS-1934"
}
```

`/rhdh-forge` returns the same shape for a GitHub issue with `source: github`,
so downstream steps read `key`, `summary`, and `source` without branching on
which skill answered.

If the named skill cannot provide the detail, retain the key and URL, leave the
summary unresolved, and report that Jira enrichment is unavailable and that the
human's next step is `/setup-rhdh-skills jira`. Never inspect a credential file
as a fallback.

## Write handoff after PR publication

After the PR URL exists, ask `/rhdh-jira-update` to state the desired comment,
transition, and remote-link outcomes. It states each write with its target and
exact command; surface that complete set for approval, and afterwards report the
outcome of every operation in it. The Jira skill owns capability detection,
adapter choice, execution, and verification.

Failure to update Jira does not invalidate a successfully created PR. Keep the
successful PR result, attach the setup requirement or the failed Jira outcomes,
and report the desired Jira outcomes for retry.
