# Linking a PR raised by `/rhdh-pr-create`

`/rhdh-pr-create` invokes this skill by name for the Web link + comment, then
runs its own **Review** transition. It passes the PR URL, title, and Jira key;
it never runs this skill's scripts itself.

The contract:

1. Run the link step with defaults disabled — the linker's default status
   target is **In Progress**, while `/rhdh-pr-create` wants **Review** after
   PR submit. Defaults (story points, team, etc.) remain available for general
   agent sessions that raise a PR without `/rhdh-pr-create`.
2. An RHDHPLAN Epic, Story, or Task may have been moved to RHIDP by the link
   step — use the post-move key it reports for everything that follows.
3. `/rhdh-pr-create` transitions the issue to **Review** on the effective key
   after the link step returns.

> Tooling: `references/tooling.md#serving-rhdh-pr-create`
