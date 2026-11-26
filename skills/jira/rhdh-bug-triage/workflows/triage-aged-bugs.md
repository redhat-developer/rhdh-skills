# Dry-run triage, step by step

This is an **agent workflow**: the scripts gather and check, but the
investigators (one fresh agent per bug) do the thinking. Every picked bug
continues through local verification, a reviewable outcome and an exact draft comment. Nothing is ever written to
Jira.

Run the commands from the installed skill directory and keep everything in
one private run folder. In the examples, `$CURRENT_RELEASE` is the release
version you verified below, `$RELEASE_EVIDENCE_URL` the web link that proves
it shipped, and `$JQL` the search you actually chose. They are placeholders,
not defaults.

## 1. Check the release and the reading tools

Use `/rhdh-context` to find the released product version under review and
its repositories. Then read the official release record yourself — the
context skill's cached table or a repository tag can be wrong or stale, and
neither alone proves the product actually shipped. If you cannot establish
what shipped, stop; do not guess. Write down where you verified it and when.
`--release-evidence` records the link; the tool does not open it for you.

Use `/rhdh-jira-api` for authenticated Jira reading. Credentials stay inside
its adapter. If reading is broken, that is a job for `/setup-rhdh-skills`,
not for this workflow.

```bash
python3 scripts/triage.py check --json
python3 scripts/triage.py fetch --jql "$JQL" --out export.json
```

`fetch` runs a search and then reads every issue in full. Check that
descriptions, comments and the customer fields actually arrived. If a
history cannot be paged completely, record that gap instead of pretending it
is complete. A ready-made export also works; say how old it is. When the
Jira adapter returns the names of the tenant's custom fields, save that
ID-to-name map and pass `--field-names tenant-fields.json` to `fetch`. Never
invent field IDs.

## 2. Pick the bugs, and keep a list to compare against

An example search:

```jql
project = RHDHBUGS AND statusCategory != Done AND created <= -90d
AND (labels IS EMPTY OR labels NOT IN ("RHDH-Customer"))
ORDER BY created ASC
```

The parentheses and `IS EMPTY` keep unlabelled reports in — a search that
silently drops them is the classic mistake. This query does not check every
customer signal or version rule; the local checks below still apply.

```bash
python3 scripts/triage.py select --input export.json \
  --current-release "$CURRENT_RELEASE" --scope aged --out sample.json
```

- Default: open, non-customer, at least 90 days old, every affected version
  known and strictly older than the release under review. A bug affecting
  both old and current versions is not eligible. Unknown, equal or newer
  versions are excluded, with a reason written down.
- Default: 5 bugs, spread across teams.
  `--all` takes every eligible bug in the export.
- `--scope all-open` drops only the age and version checks, never the
  customer or closed checks. It needs a matching wider export for both
  `select` and `run`.

Then build the comparison list — the open **and closed** bugs we will search
for duplicates and fixes. Searching only open, only aged bugs is not a real
duplicate search:

```bash
python3 scripts/triage.py backlog --out backlog.json \
  --search-jql 'project = RHDHBUGS AND statusCategory != Done AND (labels IS EMPTY OR labels NOT IN ("RHDH-Customer"))' \
  --search-jql 'project = RHDHBUGS AND statusCategory = Done AND fixVersion IS EMPTY AND (labels IS EMPTY OR labels NOT IN ("RHDH-Customer"))' \
  --full-jql 'project = RHDHBUGS AND statusCategory = Done AND fixVersion IS NOT EMPTY AND (labels IS EMPTY OR labels NOT IN ("RHDH-Customer"))'
```

The `--search-jql` parts are fast and cover whole partitions, but their
records have no dates, links or fix versions — good for finding leads, not
for proving anything. The `--full-jql` part fully reads its bugs (that is
where dates, links and fix versions come from); add it for the closed,
fix-versioned bugs when fixes matter to you, because full reads cost time.
The parts must not overlap. When a lead looks promising, read that bug in
full before drawing any conclusion.

## 3. Gather leads, then write one brief per bug

```bash
python3 scripts/triage.py collect --input export.json --sample sample.json \
  --backlog backlog.json --out evidence --gh \
  --repo owner/product-repo --repo owner/docs-repo
```

Pass the repositories that `/rhdh-context` resolved, repeating `--repo`.
Without `--gh`, collection reads only the local cache — that is **not** a
GitHub search. Keep the failures, rate limits and never-run searches; a
failed search is not "nothing found". Add `--jira-search --max-queries 4
--query-limit 20 --hydrate-limit 10` to also run the planned Jira searches
(those limits are per bug). Leads are leads; they are never verdicts.

Use `/rhdh-forge` read-only to open the actual PRs and commits, read the
diffs, and check what release a fix really shipped in. Search the bug key,
the keys it links to, the symptoms, and the promising candidates from the
list. Read the URLs hidden inside links and inline cards too. Finding
nothing does not prove there is no fix. See
[evidence sources](../references/evidence-sources.md).

Then give each investigator its own small file, instead of the whole export:

```bash
python3 scripts/triage.py brief --input export.json --sample sample.json \
  --evidence evidence --out briefs
python3 scripts/triage.py template --sample sample.json --out assessments
```

## 4. The investigator team: one bug, one fresh agent, no shortcuts

Spawn one investigator per picked bug — the host's subagent capability, or
separate sessions if there is none. Each investigator reads only its own
brief (`briefs/KEY.md`) and the sources it cites, and writes one filled-in
`assessments/KEY.json`. Investigators do not read each other's conclusions;
that independence is what makes their reviews and their disagreements mean
something.

Each investigator owns the whole question for its bug, stopping before any
code is written:

- Rebuild the failure from the report and discussion, then trace it in the
  release's own sources. Record the method, outcome, exact release and links
  in `validation` — or state exactly what is still unknown.
- Follow [bug verification](../references/bug-verification.md) for every kind
  of bug: frontend, backend, configuration, docs, dependencies, installation.
  Record the checks in `investigation`. For each new assessment, set
  `investigation.classification` with `kind`, `basis`, and an evidence `ref`.
  Compare the reporter’s expected behavior with the documented contract and comments.
  Use `bug` for a defect, `feature` for new behavior, `task` for operational work,
  or `uncertain` when the evidence cannot distinguish them. For a real defect with
  an additional feature request, keep the defect classified as a bug and record
  the separate capability in the follow-through result. Route feature, task and
  uncertain classifications to the triage owner for human review.
- Compare the bug against its duplicate and related candidates; record the
  comparisons in `comparisons`, citing both tickets.
- Write a `fixPlan`: what a fix would change, where it would land, how big
  it is. Resolution-only verdicts describe the action instead (complexity
  `none`).

**Settle unknowns before writing them down.** If a check or the verdict is
heading for unknown/unclear, first try the missing check read-only — nightly
test results on the public web, deeper digging into vendored or built code,
package registries, release records. Only write "unknown" when that evidence
genuinely does not exist, and say what was tried. An open ticket, an old
version number, an empty fix field or a search that found no fix still never
justify "still valid".

A specialist like `/rhdh-plugin-bug-fix` may help if used
**inspection-only**; never run its default fix workflow. No running product
code, builds, deploys, cluster changes, fixes, PRs or backports — here or
anywhere in this workflow.

For duplicate and already-fixed verdicts, get two genuinely independent
reviews: fresh contexts that see the evidence but not each other's
conclusion. The reviewer must be a different agent from the investigator.
Save each review's reasoning, citations and where it ran. `independentPasses:
2` with `agree: true` summarizes work that actually happened; copied numbers
or a "second opinion" from the same context don't count. If the reviews
disagree, keep the disagreement and stay uncertain.

## 5. Check the paperwork, then preview every draft

```bash
python3 scripts/triage.py run --input export.json --sample sample.json \
  --assessments assessments --backlog backlog.json --evidence evidence \
  --out review --current-release "$CURRENT_RELEASE" \
  --release-evidence "$RELEASE_EVIDENCE_URL" \
  --require-investigation --require-fix-plan
```

Use a fresh output directory; a non-empty one is refused so stale drafts can
never survive. Missing assessments, unfilled verdicts or broken inputs stop
the run — do not manufacture an "unclear" just to get exit code 0.
`--require-investigation` refuses assessments whose checks were not actually
done; `--require-fix-plan` refuses ones without a fix plan. `template` writes
empty shells, and those shells are exactly what both flags refuse: fill every
field before the first strict run. A blocked investigation needs one unknown
check and a sentence on what is missing, and stays visibly blocked.

The run writes a phased root. `01-triage/` contains the decision page
(`START-HERE.md`), one exact draft per bug under `comments/`, and the
selection, release record, method, per-bug proof, assessments and machine
record under `audit/`. `02-fixes/` contains `README.md`,
`AUDIT.md`, and one case folder per finding under its outcome:
`pull-requests/` (including documentation), `new-bugs/`, `resolution/` or `blocked/`. Each case starts with a plan. Local fix events add the verified patches and backport decisions.
`audit/packets.json` carries the machine record plus a `meta` block (which
inputs, which hashes, which code, and `writes: []`).

To make the source citations tamper-evident, write a read plan first (which
sources, which checks — see
[verification acquisition](../references/verification-acquisition.md)), run
`python3 scripts/triage.py verify --plan verification-plan.json --out
verification`, read what came back, and add `--verification verification` to
`run`. This step makes network reads and hashes them; it runs no code and
proves nothing about correctness — a human still reads the sources.

As the final composer, run `/prose-editing` **exactly once over the whole
batch of drafts** before the reviewer sees them. If it finds a defect, fix
the assessment and rerun into a new directory; never hand-edit a draft into
something the checks did not verify. An unavailable `/prose-editing` is
recorded as a gap, not silently skipped.

Read `START-HERE.md` for the current queue, then
`01-triage/comments/KEY.md` for the exact draft and
`01-triage/audit/bugs/KEY.md` for the proof, validation, fix plan, owner,
next step, and whether the comment may be posted. `review_required` and
`suppress` are statuses, not missing findings and not permission to post.
The root review index contains the handoff for each issue.

## 6. Finish the dry run

Investigate each remaining uncertainty, exercise the available reproduction and prepare each supported local change. Record attempted checks and external blockers. Follow [the fix event and finish workflow](review-events.md) to validate every selected outcome and rebuild the queue. Report the root `START-HERE.md`, the tested proposals, the delivery holds and the next decision per bug. Jira and remote repositories remain read-only.

## Scoring against known answers

```bash
python3 scripts/triage.py evaluate --packets review/01-triage/audit/packets.json \
  --truth labels.json --strict
```

Use bugs whose answers were established independently (see
[verification](../references/verification.md)). Report wrong "still valid"
calls as readily as wrong close recommendations. A good score on one run
certifies nothing about accuracy in general, and never certifies posting or
closing.
