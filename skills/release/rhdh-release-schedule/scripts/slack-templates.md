# Slack Announcement Templates

Templates for release milestone announcements. Each template uses `{{PLACEHOLDER}}` syntax for values that must be filled from Jira and Google Sheets data.

**Important:** Always wrap the final Slack message in a triple-backtick code block (` ```slack `) so the user can copy-paste directly into Slack.

---

## Feature Freeze Update

- **Milestone:** Feature Freeze
- **When to send:** Before Feature Freeze date
- **Data requirements:**
  1. Feature Freeze date from release issue (use `active_release` query via `/rhdh-jira-api`, then read the date table in the issue description)
  2. Active engineering teams from spreadsheet (Category=Engineering, Status=Active)
  3. Outstanding Release Notes count (use `release_notes` query with `--count`)
  4. Team issue counts (use `feature_freeze_issues` query filtered by team)

```slack
:announcement: *RHDH {{RELEASE_VERSION}} [Feature Freeze](https://docs.google.com/document/d/1IjMH985f3XUhXl_6drfUKopLxTBoY0VMJ2Zpr_62K2g/edit?tab=t.0#bookmark=id.5a1n60q199qh) Update* :announcement:

Feature Freeze is coming up and its target date is *{{FEATURE_FREEZE_DATE}}*. To check on the Feature Freeze status, you can use the [RHDH Release Tracking dashboard](https://redhat.atlassian.net/jira/dashboards/21028) and set fixversion to the current release.

Here's what's outstanding for Feature Freeze. Please review and share if there are any risks to meet this milestone.

• *{{TEAM_NAME}}* - [{{ISSUE_COUNT}}]({{JIRA_LINK}}) @{{LEAD_SLACK}}
(repeat for each active engineering team)

There are [{{OUTSTANDING_RELEASE_NOTES_ISSUE_COUNT}}]({{RELEASE_NOTES_JIRA_LINK}}) outstanding Release Notes. Please review and update Features and bugs.

cc @rhdh-release
```

---

## Feature Freeze Announcement

- **Milestone:** Feature Freeze
- **When to send:** On Feature Freeze date
- **Data requirements:**
  1. Open EPICs count (use `epics` query with `--count`)
  2. CVE issues count (use `cves` query with `--count`)
  3. Outstanding Release Notes count (use `release_notes` query with `--count`)

```slack
:rotating_light: *RHDH {{RELEASE_VERSION}} [Feature Freeze](https://docs.google.com/document/d/1IjMH985f3XUhXl_6drfUKopLxTBoY0VMJ2Zpr_62K2g/edit?tab=t.0#bookmark=id.5a1n60q199qh)* :rotating_light:

Its Feature Freeze! To see the latest status use the [RHDH Release Tracking dashboard](https://redhat.atlassian.net/jira/dashboards/21028) and set fixversion to the current release.
:one: The release branch is created, and any work intended for the release must be cherry-picked into this branch.
:two: Release and test pipelines are being set up for the release branch.
:three: The Test Plan is approved, and any required manual testing is identified.
:four: [{{EPIC_ISSUE_COUNT}}]({{JIRA_LINK}}) Engineering EPICs that are outstanding.
:five: [{{CVE_ISSUE_COUNT}}]({{JIRA_LINK}}) CVEs on target to be fixed before code freeze.
:six: [{{OUTSTANDING_RELEASE_NOTES_ISSUE_COUNT}}]({{JIRA_LINK}}) Release Notes to be updated before Release Notes date. Refer to [Release Notes Dashboard](https://redhat.atlassian.net/jira/dashboards/21418) for more details.
:seven: Reminder to start verifying Features and creating Feature Demos.

Please adhere to these rules so we can keep the release stable and on track. Let me know if you have any questions.

Thanks for your support.
cc @rhdh-release
```

---

## Code Freeze Update

- **Milestone:** Code Freeze
- **When to send:** Before Code Freeze date
- **Data requirements:**
  1. Code Freeze date from release issue (use `active_release` query via `/rhdh-jira-api`, then read the date table in the issue description)
  2. Active engineering teams from spreadsheet (Category=Engineering, Status=Active)
  3. Outstanding Release Notes count (use `release_notes` query with `--count`)
  4. Feature Subtasks count (use `feature_subtasks` query with `--count`)
  5. Team issue counts (use `code_freeze_issues` query filtered by team)

```slack
:announcement: *RHDH {{RELEASE_VERSION}} [Code Freeze](https://docs.google.com/document/d/1IjMH985f3XUhXl_6drfUKopLxTBoY0VMJ2Zpr_62K2g/edit?tab=t.0#bookmark=id.ecpldu1g74vj) Update* :announcement:

Code Freeze is coming up and its target date is *{{CODE_FREEZE_DATE}}*. To check on the Code Freeze status, you can use the [RHDH Release Tracking dashboard](https://redhat.atlassian.net/jira/dashboards/21028) and set fixversion to the current release.

:one: Here's what's outstanding for Code Freeze. Please review and share if there are any risks to meet this milestone or retriage to future release if applicable.

• *{{TEAM_NAME}}* - [{{TEAM_ISSUE_COUNT}}]({{JIRA_LINK}}) @{{LEAD_SLACK}}
(repeat for each active engineering team)

:two: There are [{{OUTSTANDING_RELEASE_NOTES_ISSUE_COUNT}}]({{RELEASE_NOTES_JIRA_LINK}}) outstanding Release Notes. Please review and update Features and bugs.
:three: [{{FEATURE_SUBTASK_ISSUE_COUNT}}]({{FEATURE_SUBTASK_JIRA_LINK}}) Feature Subtasks outstanding to verifying Features Acceptance Criteria and creating Feature Demos if needed.
cc @rhdh-release
```

---

## Code Freeze Announcement

- **Milestone:** Code Freeze
- **When to send:** On Code Freeze date
- **Data requirements:**
  1. Blocker bugs (use `open_issues` query + `priority = blocker` filter — detailed)
  2. Feature Demos count (use `feature_demos` query with `--count`)
  3. Test Day Features count (use `test_day_features` query with `--count`)
  4. Open issue count (use `open_issues` query with `--count`)

```slack
:rotating_light: Heads up @rhdh-core - Its {{RELEASE_VERSION}} [Code Freeze](https://docs.google.com/document/d/1IjMH985f3XUhXl_6drfUKopLxTBoY0VMJ2Zpr_62K2g/edit?tab=t.0#bookmark=id.ecpldu1g74vj) :rotating_light:
:one: No cherry-picks into the release {{RELEASE_VERSION}} branch are allowed without explicit approval from both the @rhdh-release-manager
:two: [{{BLOCKER_BUG_ISSUE_COUNT}}]({{JIRA_LINK}}) Blocker bugs outstanding.
:three: Regarding CVEs: Only critical severity CVEs will be considered for inclusion before GA, and these will follow the same approval process (Release Manager). All other CVEs will be handled in the next z stream release
:four: Review and update [Release Notes and Known Issues](https://redhat.atlassian.net/jira/dashboards/21418#)
:five: [Feature Demos](https://docs.google.com/document/d/1IjMH985f3XUhXl_6drfUKopLxTBoY0VMJ2Zpr_62K2g/edit?tab=t.0#bookmark=id.l8izl2mswrfb): [{{FEATURE_DEMO_ISSUE_COUNT}}]({{JIRA_LINK}}) Features are tagged for demos. Add your demos and update the RHDH Release Features Slide in the {{RELEASE_VERSION}} [folder](https://drive.google.com/drive/folders/1QKf2hgOxCo6cmWkJ0b78o1Byx8uxgK_E?q=title:%3C1.9.0%3E)
:six: [{{TEST_DAY_FEATURE_ISSUE_COUNT}}]({{JIRA_LINK}}) Features are tagged for Testday. Please review they are ready for Testday.
:seven: [{{OPEN_ISSUE_COUNT}}]({{JIRA_LINK}}) issues set to {{RELEASE_VERSION}} and not closed. Please review and move to the next release as appropriate and can be fixed in main branch ONLY.
:eight: Release Candidate: Once the release candidate is available then will proceed with the Test plan.

Please adhere to these rules so we can keep the release stable and on track. Let me know if you have any questions.

Thanks for your support!
@rhdh-release
```
