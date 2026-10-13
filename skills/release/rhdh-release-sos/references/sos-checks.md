# SoS release checks

This file is the runbook for the SoS release check-in report. Read **Query
vocabulary** first — it defines what each `Query` cell means. The **Schedule**
table below lists when each check runs, what it is called in the report, and the
**Action item** teams should take when the check is not clear.

Maintain the schedule table top to bottom. Section header rows name a milestone
gate; check rows beneath it run only while the release calendar is in that
section — a **Code Freeze** row never appears during the **Feature Freeze**
section, and vice versa. On each run the CLI resolves `When` against
`/rhdh-release-schedule` milestone dates, executes every check whose resolved
date is on or before today, and stops before the first future check in the
active section. Upcoming checks are not rendered in the report.

## Query vocabulary

Every check row ends in a Jira query. The query decides **what** is counted; the
`When` column decides **when** that row appears in the report.


| Query                                            | What Jira counts                                                                      | When to use it                                                                               |
| ------------------------------------------------ | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `static "Name"`                                  | The Rich Filter static filter **Name**, scoped to this release (`fixVersion`)         | A **count** or **snapshot** — especially when you need `+ extra JQL` to narrow the scope     |
| `static "Name" + …`                              | Same static filter, plus extra JQL after `+`                                          | A **slice** of that scope (e.g. not in a sprint, unassigned, wrong status)                   |
| `due static "Name"`                              | **The same JQL as** bare `static "Name"` — full filter, no extras                     | **Due by milestone** **Name** — tracked from early in the section through that milestone day |
| `expect assignee summary ~ "pattern"`            | Open issues whose summary contains **pattern**, scoped to this release                | A **named ticket must exist and have an assignee** — pass/fail, not a volume count           |
| `expect assignee summary ~ "pattern" + …`        | Same, plus extra JQL after `+`                                                        | Narrow to one ticket shape (e.g. `issuetype = Epic`)                                         |
| `testplan children assigned summary ~ "pattern"` | Test Plan **Epic** for this release; all open child Tasks must have an assignee by FF | Test-plan execution readiness                                                                |
| `testplan signoff open summary ~ "pattern"`      | Same epic; child tasks with **sign-off** in the summary must be **Closed**            | Lists open sign-off tasks in HTML (collapsible)                                              |
| `metric epic_dev_complete static "Name"`         | Epics under static filter **Name**; reports % in Dev Complete                         | Epic readiness before Feature Freeze                                                         |
| `template blockers`                              | Named template from the Rich Filter overlay                                           | Blocker bugs (and similar template-backed scopes)                                            |
| `queue "RNs Unclassified"`                       | Named Rich Filter queue + `fixVersion`                                                | Queue-backed scopes such as release notes                                                    |


### `static` vs `due static` — same number, different job

These two look similar in the vocabulary table. The difference is **not** a
different Jira filter — for the same name (e.g. `"Feature Freeze"`), both count
issues in that static filter for the release.


|                          | `static "Feature Freeze"`                                              | `due static "Feature Freeze"`                                    |
| ------------------------ | ---------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Jira scope               | Rich Filter **Feature Freeze** + `fixVersion`                          | **Identical**                                                    |
| Extra JQL                | Yes — `+ sprint is EMPTY`, `+ status in (…)`, etc.                     | No — always the full filter                                      |
| Report role              | Count check or **milestone snapshot** (see row title)                  | **Due by Feature Freeze** — scope that should clear by that date |
| HTML                     | Count, team breakdown, Jira link                                       | Same, plus **Complete by Feature Freeze ·** `<date>`             |
| After Feature Freeze day | Row can still appear if its `When` date is due (e.g. FF - 0d snapshot) | Row is **dropped** — due-by tracking ends on the milestone       |


**Rule of thumb:** use `due static` once per milestone for “how much scope must
clear by this gate?” Use `static` for snapshots, slices, and anything that needs
`+ extra JQL`. Do not add a second row that repeats bare `static "Feature Freeze"`
or `static "Code Freeze"` mid-section — the `due static` row already tracks that
full scope from the first offset in the section.

Supported names for `due static` today: **Feature Freeze**, **Code Freeze**.

### `expect assignee` — one ticket, must have an owner

Use when the check is about **a specific coordination ticket**, not how many issues
are open in a filter.


| Query part            | Meaning                                                                         |
| --------------------- | ------------------------------------------------------------------------------- |
| `expect assignee`     | Check kind — verify assignee on a matching ticket                               |
| `summary ~ "pattern"` | Jira `summary ~ "pattern"` (contains, case-sensitive in Jira) plus `fixVersion` |
| `+ …`                 | Optional extra JQL after `+` (e.g. `issuetype = Epic`)                          |


Report summaries:


| Summary                                             | Meaning                                             |
| --------------------------------------------------- | --------------------------------------------------- |
| `Assigned (RHIDP-123)`                              | Exactly one match, assignee set — green             |
| `Unassigned — find an owner`                        | One match, no assignee — action needed              |
| `Not found — create or link ticket`                 | No open issue matches — action needed               |
| `Multiple matches (KEY-1, KEY-2) — pick one ticket` | Pattern matched more than one issue — action needed |


The Jira column links to the ticket when there is a single match; otherwise it
links to the search. No team breakdown — this is not team-scoped volume.

Pick a **distinct enough** `summary ~` pattern so only the intended ticket matches.
Add more checks by adding rows with different patterns.

### `testplan` — Test Plan epic and its child tasks

Both queries locate one **Test Plan** epic (`summary ~ "pattern"`, `issuetype = Epic`,
this release `fixVersion`). They run from **FF - 21d** through **Feature Freeze day**.


| Query                          | Pass                                           | Action needed                                                       |
| ------------------------------ | ---------------------------------------------- | ------------------------------------------------------------------- |
| `testplan children assigned …` | Every open child Task/Sub-task has an assignee | Unassigned child tasks remain — Jira links to the unassigned filter |
| `testplan signoff open …`      | Every sign-off child task is Closed            | Sign-off tasks still open — listed under the check in HTML          |


## Check notes

- **Epic Dev Complete** (`metric epic_dev_complete static "Feature Freeze"`) uses
the static **Feature Freeze** filter scoped to `issuetype = Epic`. The exported
filter's `status not in (…)` clause is dropped for the denominator so Dev
Complete epics count in the total. Runs from **FF - 21d** through **Feature
Freeze day** only.
- **Due by milestone** (`due static "…"`) uses the matching static filter as-is,
starts at the first offset shown in the schedule, shows the milestone date as
the completion target in HTML, includes team breakdown, and stops after that
milestone day.
- **Expect assignee** (`expect assignee summary ~ "…"`) finds open issues matching
the summary pattern and release `fixVersion`. Exactly one match with an assignee
passes; zero, many, or unassigned matches call for action in the summary.

## Schedule

Leave **Action item** blank when a check needs no team guidance (for example
milestone snapshots). The report omits the markdown sub-row and HTML info icon for
blank cells.

| When           | Check                                              | Query                                                                      | Action item                                                                                                                                                           |
| -------------- | -------------------------------------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Feature Freeze |                                                    |                                                                            |                                                                                                                                                                       |
| FF - 21d       | FF Stories, Tasks not in a sprint                  | static "Feature Freeze" + sprint is EMPTY AND issuetype in (Story, Task)   | Plan every FF Story and Task into the current sprint.                                                                                                                 |
| FF - 21d       | FF Stories, Tasks unassigned                       | static "Feature Freeze" + assignee is EMPTY AND issuetype in (Story, Task) | Assign an owner to every unassigned FF Story and Task.                                                                                                                |
| FF - 21d       | FF Epics, Stories, Tasks in New, To Do, or Backlog | static "Feature Freeze" + status in (New, "To Do", Backlog)                | Possibly move FF scope out of New, To Do, or Backlog into active work.                                                                                                |
| FF - 21d       | FF Epics Dev Complete                              | metric epic_dev_complete static "Feature Freeze"                           | By the Feature Freeze date, EPICs should be in the Dev Complete state, meaning all engineering work is complete, excluding test automation and documentation stories. |
| FF - 21d       | Work remaining for Feature Freeze                  | due static "Feature Freeze"                                                | Close all FF-scope work before Feature Freeze.                                                                                                                        |
| FF - 21d       | Test Day ticket has owner                          | expect assignee summary ~ "Test Day" + issuetype = Epic                    | Ensure a single Test Day epic exists and has an assignee.                                                                                                             |
| FF - 21d       | Test Plan tasks assigned                           | testplan children assigned summary ~ "Test Plan"                           | Assign an owner to every open Test Plan child task.                                                                                                                   |
| FF - 21d       | Test Plan sign-off complete                        | testplan signoff open summary ~ "Test Plan"                                | Close all Test Plan sign-off tasks.                                                                                                                                   |
| FF - 0d        | Feature Freeze day snapshot                        | static "Feature Freeze"                                                    |                                                                                                                                                                       |
| Code Freeze    |                                                    |                                                                            |                                                                                                                                                                       |
| CF - 14d       | Blocker bugs outstanding                           | template blockers                                                          | Resolve or downgrade every open blocker before Code Freeze.                                                                                                           |
| CF - 14d       | CF work remaining for Code Freeze                  | due static "Code Freeze"                                                   | Clear all CF-scope work before Code Freeze.                                                                                                                           |
| CF - 0d        | Code Freeze day snapshot                           | static "Code Freeze"                                                       |                                                                                                                                                                       |
| Go/No Go       |                                                    |                                                                            |                                                                                                                                                                       |
| GNG - 7d       | Open engineering EPICs                             | template epics                                                             | Close or defer open engineering epics before Go/No Go.                                                                                                                |
| GNG - 7d       | Unclassified release notes                         | queue "RNs Unclassified"                                                   | Classify every unclassified release note before Go/No Go.                                                                                                             |
| GA Announce    |                                                    |                                                                            |                                                                                                                                                                       |
| GA - 7d        | Post Code Freeze scope                             | template post_code_freeze_issues                                           | Review post-Code Freeze scope and drive it to closure.                                                                                                                |


