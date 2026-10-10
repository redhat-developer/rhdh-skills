# Jira bulk-read adapter

Use `acli` for bulk reads unless the agent host exposes an already-authenticated Atlassian
GraphQL capability. This reference owns query semantics, not credentials or HTTP transport.

## Capability gate

1. Run the capability check in [auth.md](auth.md).
2. If `acli` is ready, prefer its paginated JSON search:

   ```bash
   acli jira workitem search --jql "<JQL>" --paginate \
     --fields "key,summary,status,issuetype,priority,assignee,parent,labels,fixVersions" --json
   ```

3. Use GraphQL only when the host exposes a ready authenticated Atlassian adapter and the branch
   needs relationship or custom-field data that `acli` cannot return efficiently.
4. If neither adapter satisfies the branch, say so and tell the human to run
   `/setup-rhdh-skills atlassian-mcp`.

The agent never creates an `AUTH` variable, reads a token file into context, builds an
Authorization header, or invokes a raw HTTP client with credentials. Authentication stays
inside the native CLI, the bundled Greenhopper adapter (in-process; never printed), or a
host connector.

## Query contract

The adapter accepts a GraphQL document plus variables and returns response data without exposing
request headers or credentials. Keep GraphQL read-only. Writes go through the supported `acli`
command or the authenticated host operation, and only after the user approves the exact command.

### Schema discovery

Use targeted introspection through the adapter when a field or type is unknown:

```graphql
query IntrospectType($name: String!) {
  __type(name: $name) {
    name
    fields {
      name
      type { name kind ofType { name kind } }
    }
  }
}
```

Do not load a full schema dump into model context. If offline inspection is necessary, save the
adapter response to a temporary file and query only the relevant type names programmatically.

### Search issues

`issueSearchStable` is a beta endpoint, and three things about it fail the whole request rather
than degrading. The JQL goes inside an `issueSearchInput` object, not a top-level `jql` argument.
The request needs the header `X-ExperimentalApi: JiraIssueSearch`; without it the endpoint returns
`BetaHeaderOptInException`. The adapter sends that header — if it cannot, use paginated `acli`
instead. And the operation must be named: anonymous `query { ... }` documents are rejected.

```graphql
query SearchIssues($cloudId: ID!, $input: JiraIssueSearchInput!, $first: Int!, $after: String) {
  jira {
    issueSearchStable(cloudId: $cloudId, issueSearchInput: $input, first: $first, after: $after) {
      totalCount
      edges {
        node {
          key
          summary
          status { name }
          issueType { name }
          priority { name }
          assignee { name accountId }
          parentIssue { key summary }
          storyPoints
          labels
          fixVersions { name }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
```

Variables are `{"input": {"jql": "project = RHIDP AND status = \"In Progress\""}, "first": 50}`.
`first` sits on the connection, never inside `issueSearchInput`. Compare `totalCount` against the
rows collected to know whether a result set was truncated, and report a truncated result as
truncated. Carry forward normalized issue data only; never carry raw connector metadata.

### Single issue

```graphql
query GetIssue($cloudId: ID!, $key: String!) {
  jira {
    issueByKey(cloudId: $cloudId, key: $key) {
      key
      summary
      status { name }
      issueType { name }
      priority { name }
      assignee { name accountId }
      parentIssue { key summary }
      storyPoints
      labels
      fixVersions { name }
      fields { edges { node { __typename } } }
    }
  }
}
```

Custom fields arrive as typed nodes under `fields`. Select them with inline fragments:

| `__typename` | Fragment | Returns |
|---|---|---|
| `JiraNumberField` | `... on JiraNumberField { number }` | Story Points and the DEV/QE/DOC point fields |
| `JiraSingleSelectField` | `... on JiraSingleSelectField { fieldOption { value } }` | Size, Ready, Blocked, Release Note Type |
| `JiraSprintField` | `... on JiraSprintField { selectedSprintsConnection { edges { node { name state } } } }` | Sprint name and state |
| `JiraLabelsField` | `... on JiraLabelsField { labels { edges { node { name } } } }` | Labels |
| `JiraComponentsField` | `... on JiraComponentsField { components { edges { node { name } } } }` | Components |
| `JiraRichTextField` | introspect for sub-fields | Description, Acceptance Criteria, Release Note Text |
| `JiraTeamViewField` | `... on JiraTeamViewField { selectedTeam { jiraSuppliedName fullTeam { members(first: 50) { nodes { member { name accountId } state role } } } } }` | Team name and roster — see Team roster below |

Introspect any `__typename` not listed here rather than guessing its shape.

### Team roster

Query team membership directly instead of inferring a roster from issue assignees.

```graphql
query GetTeamRoster($teamId: ID!, $siteId: ID!, $first: Int!, $after: String) {
  team {
    teamV2(id: $teamId, siteId: $siteId) {
      displayName
      members(first: $first, after: $after) {
        nodes { member { name accountId } state role }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
```

`siteId` is the same cloud id used elsewhere; `teamId` is the Jira team UUID, which the caller
supplies. Never infer a team from member names. Each node carries `state` — `FULL_MEMBER`,
`INVITED`, or `ALUMNI` — and `role`, either `REGULAR` or `ADMIN`. Keep `FULL_MEMBER` only:
`INVITED` members have not accepted and `ALUMNI` have left, so counting either inflates capacity
and produces recommendations for people who cannot take the work. Page past the first 50 members
with `pageInfo.endCursor`.

A team can also be reached from an issue through `JiraTeamViewField`, whose
`selectedTeam.fullTeam.members` returns the same node shape. Prefer `teamV2` when a team id is
known; it avoids fetching an issue to reach the roster.

`/rhdh-jira-update` consumes this roster for expertise and capacity analysis,
`/rhdh-jira-sprint-plan` consumes it for per-member capacity, and
`/rhdh-release-capacity-plan` consumes it for release-horizon availability.

## Fallback rules

| Need | Adapter |
|---|---|
| Normal or bulk JQL search | `acli jira workitem search --paginate --json` |
| Single issue with custom fields | `acli jira workitem view KEY --fields '*all' --json` |
| Relationship-heavy bulk read | Authenticated host GraphQL adapter |
| Team roster by team id | Authenticated host GraphQL adapter, `team.teamV2` |
| Unsupported custom-field read or write | [rest-api-fallback.md](rest-api-fallback.md) |
| Sprint report / burndown | Bundled `scripts/greenhopper.py` (local token file). Host REST adapter only if that script cannot run |
| No capable authenticated adapter | Name the missing capability and `/setup-rhdh-skills atlassian-mcp` |

`issueSearchStable` is an evolving API. When it fails, fall back to paginated `acli`, not raw REST
search. Enrich and normalize results with `scripts/parse_issues.py` before claiming a field is
missing.
