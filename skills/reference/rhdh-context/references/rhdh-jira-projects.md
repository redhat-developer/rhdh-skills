## Purpose

Single source of truth for RHDH Jira projects — their keys, purpose, and which
skill domains operate on them.

## Projects

| Key | Full name | Purpose | Domains |
|---|---|---|---|
| RHIDP | Red Hat Internal Developer Platform | Engineering work: bugs, features, epics, stories, tasks. Canonical source for fix-version metadata when the version exists here. | jira, release, ci, plugins |
| RHDHPLAN | Red Hat Developer Hub Planning | Planning Features: release milestones, PI tracking, release-level Epics. Second canonical source for fix-version metadata. | jira, release |
| RHDHBUGS | Red Hat Developer Hub Bugs | Customer-facing defects and CVEs triaged from support cases. Third canonical source for fix-version metadata. | jira, release |
| RHDHSUPP | Red Hat Developer Hub Support | Support case tracking and customer escalations. Not in scope for fix-version sync. | jira |

## Fix-version canonical order

When the same fix-version name exists in more than one project, metadata
(description, dates, released/archived flags) is taken from the first project
that defines it: **RHIDP → RHDHPLAN → RHDHBUGS**. Other copies are updated to
match. RHDHSUPP is intentionally excluded from fix-version sync.

## Notes

- All four projects live on `issues.redhat.com` (Jira Cloud).
- `acli` can query all four; fix-version CRUD requires the Jira REST API
  (version endpoints are outside `acli`'s supported commands).
- Administer Projects permission is required for fix-version create/update/delete.
