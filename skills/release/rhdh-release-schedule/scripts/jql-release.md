# Release JQL Templates

Template data for `scripts/jql.py`, which parses the `jql` blocks below and
renders them for `scripts/release.py` and for the Jira search links it emits.
All queries tested against `redhat.atlassian.net`.

This is adapter input, not a query catalog to run by hand. For general Jira
queries, boards, and sprints, `/rhdh-jira-context` owns the patterns and IDs.

Freeze scopes, the demo and Test Day filters, and the release-note lifecycle
queues are absent here on purpose: the Rich Filter export supplies them at run
time. `/rhdh-release-status` owns that mapping and the export's configuration.

## active_release

Find all active release features in RHDHPlan.

```jql
project=rhdhplan AND issuetype=feature AND component=release AND status != closed
```

- **Placeholders:** none
- **Notes:** Returns release tracking issues with key dates in description. Ask `rhdh-jira-api` for each result's full issue and read the dates from its description.

## open_issues

Find all open issues for a specific release version.

```jql
project IN (RHIDP, RHDHBugs, RHDHPLAN, RHDHSUPP) AND fixVersion = "{{RELEASE_VERSION}}" and status != closed
```

- **Placeholders:** `{{RELEASE_VERSION}}` — e.g., `1.9.0`
- **Example:** `... AND fixVersion = "1.9.0" and status != closed`
- **Notes:** Base query for all open issues in a release.

## open_issues_by_type

Find open issues for a release filtered by issue type.

```jql
project IN (RHIDP, RHDHBugs, RHDHPLAN, RHDHSUPP) AND fixVersion = "{{RELEASE_VERSION}}" AND status != closed AND issuetype = "{{ISSUE_TYPE}}"
```

- **Placeholders:** `{{RELEASE_VERSION}}`, `{{ISSUE_TYPE}}`
- **Example:** `... AND fixVersion = "1.9.0" AND status != closed AND issuetype = "Bug"`
- **Notes:** Valid issue types: Feature, Epic, Story, Task, Sub-task, Bug, Vulnerability, Weakness.

## epics

Find open EPICs not in Dev Complete or Release Pending.

```jql
project IN (RHIDP) AND fixVersion = "{{RELEASE_VERSION}}" and issuetype = epic and status not in (closed, "Release Pending", "Dev Complete")
```

- **Placeholders:** `{{RELEASE_VERSION}}`
- **Example:** `... AND fixVersion = "1.9.0" and issuetype = epic and status not in (closed, "Release Pending", "Dev Complete")`
- **Notes:** Identifies EPICs that need attention before release.

## cves

Find all CVE issues (vulnerabilities and weaknesses).

```jql
project IN (RHIDP, rhdhbugs) AND fixVersion = "{{RELEASE_VERSION}}" and issuetype in (weakness, Vulnerability, bug) and summary ~ "CVE*"
```

- **Placeholders:** `{{RELEASE_VERSION}}`
- **Example:** `... AND fixVersion = "1.9.0" and issuetype in (weakness, Vulnerability, bug) and summary ~ "CVE*"`
- **Notes:** Critical for security tracking before release.

## feature_subtasks

Find feature subtasks for acceptance criteria verification.

```jql
project in (RHDHPlan) AND issuetype = sub-task AND fixVersion = "{{RELEASE_VERSION}}" AND status != closed
```

- **Placeholders:** `{{RELEASE_VERSION}}`
- **Example:** `... AND fixVersion = "1.9.0" AND status != closed`
- **Notes:** Tracks feature verification and demo creation tasks.

## features_added_to_release

Find features added to release in last 14 days.

```jql
project in (RHDHPlan, rhidp) AND issuetype = feature AND fixVersion = "{{RELEASE_VERSION}}" AND fixversion changed after -14d
```

- **Placeholders:** `{{RELEASE_VERSION}}`
- **Example:** `... AND fixVersion = "1.9.0" AND fixversion changed after -14d`
- **Notes:** Tracks scope changes to release.

## blockers

Find open blocker bugs for a release.

```jql
project IN (RHIDP, RHDHBugs, RHDHPLAN, RHDHSUPP) AND fixVersion = "{{RELEASE_VERSION}}" AND status != closed AND issuetype = bug AND priority = Blocker
```

- **Placeholders:** `{{RELEASE_VERSION}}`
- **Example:** `... AND fixVersion = "1.9.0" AND status != closed AND issuetype = bug AND priority = Blocker`
- **Notes:** Critical path items that must be resolved before release.

## open_issues_by_team

Find all open issues for a release filtered by team using Cloud ID.

```jql
project IN (RHIDP, RHDHBugs, RHDHPLAN, RHDHSUPP) AND fixVersion = "{{RELEASE_VERSION}}" AND status != closed AND "Team[Team]" = "{{CLOUD_ID}}"
```

- **Placeholders:** `{{RELEASE_VERSION}}`, `{{CLOUD_ID}}`
- **Example:** `... AND fixVersion = "2.1.0" AND status != closed AND "Team[Team]" = "ec74d716-af36-4b3c-950f-f79213d08f71-4403"`
- **Notes:** Cloud ID is the Jira Cloud team identifier from the RHDH Team Mapping spreadsheet (column "Cloud ID"). This is the fastest way to filter by team — no enrichment needed.
