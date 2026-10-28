# Recommend and assign Jira work

Recommend assignees from team membership, recent expertise, current capacity, and
context proximity, then apply the assignment. Accepts one or more issue keys, a
JQL query, and an optional Jira team ID.

## Choose a mode

- **Deep** — authenticated team roster plus recent work and sprint capacity. The
  default when the host and CLI capabilities are ready.
- **Quick** — only the issue and assignee evidence already in context. If that
  evidence is thin, say so rather than guessing.

## Capability boundary

The team roster comes from the
authenticated host GraphQL adapter — the `GetTeamRoster` query in
`/rhdh-jira-context`. If that adapter is unavailable, say so, name
`/setup-rhdh-skills atlassian-mcp`, and ask whether to continue in quick mode.
Never construct credentials or raw HTTP requests.

## Deep analysis

1. Fetch the roster through `/rhdh-jira-context`. Keep members whose `state` is
   `FULL_MEMBER`; drop `INVITED` and `ALUMNI` — counting either inflates capacity
   and recommends people who cannot take the work. Capture display name and
   account ID, and paginate past 50 members.
2. Fetch up to 90 days of recent work per member:

   ```jql
   project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS) AND assignee = ACCOUNT_ID AND updated >= -90d ORDER BY updated DESC
   ```

3. Build an expertise profile: top components, issue-type counts, recurring
   domain phrases, and the share of work in the leading component.
4. Fetch active and future sprint load:

   ```jql
   project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS) AND assignee = ACCOUNT_ID AND sprint in (openSprints(), futureSprints()) AND status != Closed
   ```

5. Mark a member overloaded at 10 open issues or 21 committed story points.
6. Score context proximity: +3 per shared component, +1 per shared meaningful
   phrase, +5 for a shared parent.

Score with `expertise_match * 3 + proximity * 2 - open_issue_count`, minus 10 for
an overloaded member. For Blocker or Critical work, pick the strongest domain
expert and disclose the capacity risk. Otherwise exclude overloaded members.
Include a runner-up when the scores are within 20%.

Also flag:

- one person owning more than 60% of a component's recent work;
- the same person recommended for four or more issues in one batch;
- a low-priority issue that could safely broaden someone else's experience.

## Recommendation output

Report issue key, summary, priority, proposed account ID and display name, score,
short evidence, runner-up, capacity, and warnings. When component or sprint
metadata is missing, say the confidence is low — do not imply certainty.

## Apply the assignment

Assignment is an external write. Invoke `/mutation-gate` and follow it, with
one row per issue-to-person mapping, then apply.

There is no GraphQL mutation for assignment — the local CLI and the
authenticated host adapter are the only two paths. If the tool you have
cannot perform a required assignment, use the authenticated host adapter;
never fall back to raw HTTP.

Verify each assignee after execution and report successes, skips, and permission
failures separately.

## Failure handling

| Failure | Action |
|---|---|
| Team ID unknown | Ask for it. Do not infer a team from names. |
| Member has no recent work | Keep them, mark expertise unknown |
| Rate limit | Honor the adapter delay and retry once |
| Everyone is overloaded | Recommend the least-loaded qualified member, with a warning |
| Issue has no useful metadata | Score only the available evidence and label confidence low |
