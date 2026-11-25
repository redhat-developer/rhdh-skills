# Incremental review

Use a private run directory (`umask 077`). Keep credentials inside the Jira and forge adapters. Keep raw issue descriptions, support IDs and local receipts in restricted storage. Only copy reviewed, sanitized draft text into a proposed public bug.

## Start or resume the inventory

From the skill directory, set RUN to the private run directory and RELEASE to the verified release. The Jira adapter paginates a cheap key/status search. Full issue and comment reads apply to one batch.

```bash
python3 scripts/triage.py inventory --project RHDHBUGS --out "$RUN/bugs.json"
python3 scripts/triage.py inventory --project RHDHSUPP --out "$RUN/support.json"
python3 scripts/triage.py fetch --inventory "$RUN/bugs.json" --batch 1 --out "$RUN/export-1.json"
python3 scripts/triage.py select --input "$RUN/export-1.json" --scope all-open --current-release "$RELEASE" --out "$RUN/sample-1.json"
```

Continue the investigation, verification and strict run in the aged workflow using this export/sample pair and `--scope all-open` on run. Give each batch a fresh output directory. Advance the fetch batch number after a completed run. Retry the same inventory slice on a failed read. Use the frozen inventory for the entire cycle. An issue that closed or shows a customer signal after inventory is still accounted for with a reason. Run `python3 scripts/triage.py progress --inventory "$RUN/bugs.json" --run "$RUN/review-1" --run "$RUN/review-2"` with each finished run to list completed, blocked, excluded and pending keys. Keep multiple snapshots separate. An aged export can instead be paged with `select --batch N` using the same export, size, seed, release and as-of date for each page.

Ask /rhdh-jira-api for the authenticated tenant field metadata (GET /rest/api/3/field or an authenticated issue read expanded with names). Save the returned ID-to-name map privately and pass it as `fetch --field-names FILE`. Verify mapped fields actually arrived in the full read. If metadata is inaccessible, retain the customer-coverage hold. A technical finding and a recommendation to close are independent.

## Consume a trigger

When the host delivers a Jira issue-created or issue-updated webhook, run `python3 scripts/triage.py trigger --input notification.json --out "$RUN"`. The returned directory contains a request.json with only the issue key, update timestamp and stage. Duplicate deliveries share one receipt. Have the host invoke this skill on the resulting request. On bug.updated, fetch that key, check the revision, then investigate. On support.updated, read that case privately, check existing bugs and prepare sanitized intake. A host can also invoke a specific local fix request for an actionable finding.

Run `python3 scripts/triage.py event --input EVENT.json --out "$RUN"` for one locally prepared event. An operator or host adapter supplies the issue key, type and revision (the Jira update timestamp or approved fix request ID). Treat incoming webhook data solely as a signal. Re-read the issue through the authenticated adapter and prepare the local event yourself. Never accept checkout paths, patch paths, commands or prepared prose from an external webhook. Replay of a processed revision returns its original receipt. Changed input requires a fresh revision. Each receipt directory is private and published atomically.

| Type | Local event fields beyond type, key, revision | Result |
|---|---|---|
| bug.updated | export (single-issue full export), release, asOf | Selection or exclusion for that issue. Continue collect, brief, investigation and run with this sample and export. |
| support.updated | sanitized (true after review), duplicateCheck, and either existingBug or summary, observed, expected | A suggested new bug or an existing bug reference. Read the private case first, compare existing bugs, and remove customer identifiers, logs and internal URLs from draft prose. A resulting Jira bug key enters through bug.updated. |
| fix.requested | Local proposal inputs below | A patch checked against the recorded branch tip, proposed PR text, verification record and branch-specific decisions. |

## Prepare a fix request

Read the current packet and underlying issue. Use this stage for actionable code or documentation findings. A reproduction blocker can coexist with a tested documentation remedy. Record kind `code` for a product change (including its accompanying tests and docs) or `docs` for a documentation-only patch, and identify its target repository in the assessment fix plan. Use a disposable checkout of the identified repository. Verify the contribution branch and supported maintenance branches through the repository's current release or contribution records. Refresh the remote tracking refs. Capture the exact base commit. Implement the proposed change locally, include tests and docs where appropriate, run the relevant checks, and export the complete staged diff with `git diff --cached --binary`. Include new files. Check that the tested tree matches the staged diff. Preserve a failed or unavailable check in the verification text.

For `fix.requested`, supply triageRun (the completed run directory containing the actionable finding), repository (GitHub owner/repo), checkout, branch, base, branchEvidence (source and rationale), patch (file path), patchHash (SHA-256), title, body, docsImpact, verification (commands, results, limits), maintenanceEvidence (maintained branches and source), and backports (a list). Paths resolve relative to the local event file. For each maintained branch other than the primary target, supply branch, decision (propose, skip or undetermined) and reason. A proposed backport also needs base, patch, patchHash and verification for that branch. An empty list requires evidence that no other branch applies. Check application against each pinned base. Keep unresolved branch decisions visible to the reviewer.

The event command verifies the repository origin, local tracking ref, diff digest and patch application with an isolated Git index. The investigator owns target selection and the recorded test results. External publication, deployment, issue creation and issue resolution are outside v1. Route only the stage requested by the event.

## Complete the batch

After consuming all applicable fix events in the review directory, run:

```bash
python3 scripts/triage.py finish --input "$RUN/results.json" --out "$RUN/review"
```

Supply an array with one object per selected issue. Each object contains `key`, `stage`, a brief `finding`, `verification` describing the check actually run, `next` naming the remaining action, and `evidence` pointing to a shareable text receipt beneath the results file's directory. For each new result, include `nextActions`, an array of objects with `owner` and `action`. Name a recorded assignee, team, or responsible role for each distinct action. Use a role for proposed handoffs where Jira has no assigned person. State what the change solves and which part of the original report remains open. Use `resolution` for an index-specific summary when the Jira-facing `finding` needs different wording. Older results with only `next` show the action with ownership unrecorded. The command copies that receipt into the review audit. Keep secrets and raw private exports out of the receipt.

Use `patch` for a verified local proposal, including a partial remedy with its remaining blocker recorded in `next`. Use `existing_fix` for a verified shipped fix, `verified_resolution` for a verified duplicate or obsolete finding, `ready_to_close` for a policy-approved closure recommendation, or `blocked` with an additional `blocker` naming the missing input. Attempt every accessible check before marking a case blocked. Replaying finish rebuilds the single review index. Jira delivery and closure holds still apply.
