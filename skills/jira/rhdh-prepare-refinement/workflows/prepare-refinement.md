# Prepare refinement

## Inputs

1. **Team name** — ask if not provided. Must match a board in `/rhdh-jira-api`
   (references/jql-patterns.md, Boards table):

   | Board | ID | Team |
   |-------|----|------|
   | RHDH Install | 11462 | Install |
   | RHDH Plugins | 11549 | Plugins |
   | RHDH Frontend Plugins & UI | 11525 | Frontend |
   | RHDH AI Sprint | 10725 | AI |
   | RHDH Cope | 11374 | COPE |
   | RHDH Documentation Sprint | 10851 | Documentation |

2. **Fix version** — e.g. `2.1.0`. Required.

## Run

```bash
./scripts/prepare-refinement --team Install --fix-version 2.1.0
```

The script:
- Looks up the team's Jira team ID via `acli`
- Builds JQL: `project = RHIDP AND sprint in openSprints() AND "Team[Team]" = ID AND fixVersion = "VER"`
- Fetches release milestones from RHDHPLAN ADF
- Evaluates queue signals
- Prints the brief

## Output shape

```
🎯 RHDH Install · Refinement

Release: 2.1.0
Code freeze: 13 Oct · 7 days 🔥

✨ Summary
…

🚀 Feature Tracking (Dashboard)
   …
🎫 Team Dashboard (Dashboard)
   …
🧹 Hygiene (Dashboard)
   …
```

## Auth

```bash
acli jira auth login --site redhat.atlassian.net --email <you@redhat.com> --token
```

Or `export JIRA_EMAIL` and `JIRA_API_TOKEN`.
