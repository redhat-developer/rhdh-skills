# Triage aged RHDH bugs

Run one read-only pass over an aged RHDHBUGS sample. The output is a local report
a reviewer can act on; nothing is posted to Jira.

## 1. Check capability

```bash
python3 scripts/run_poc.py check --json
```

Three inputs are possible:

| Input | When to use | What to say |
|---|---|---|
| `acli` | A Jira session is available | Use `--source acli` for `select` |
| JSON export | A host adapter, MCP tool, or saved search produced a file | Use `--source export --input FILE` |
| `gh` cache | PR state was saved for repeatable runs | Pass `--forge-cache FILE` to `collect` |

The **sample export** and the **duplicate corpus** can come from the same broad
export, or from two files when you already have a narrow one. Either way, the
corpus must contain closed bugs, because the canonical ticket for a duplicate is
often already closed:

```bash
# Broad export: everything in the project, or open plus recently resolved.
# Selection removes Done, young, and customer-linked tickets by itself.
acli jira workitem search --jql 'project = RHDHBUGS' \
  --fields '*all' --paginate --json > export.json
```

If you must keep a saved open-only export for the sample, pass the broad file
separately: `run --input open-export.json --corpus broad-export.json`. Without
closed tickets in the corpus, the report says duplicate search could not reach a
closed canonical report and tells you to rerun.

`check` never prints a credential. If `acli` is unreadable, do not ask this skill
to repair it: tell the user to authenticate, or continue with an export through
the offline adapter. `/rhdh-jira-api` owns the read mechanics and the fallback
order.

## 2. Build the sample

```bash
python3 scripts/run_poc.py select \
  --input export.json \
  --aged-days 90 \
  --size 12 \
  --control RHDHBUGS-4102=known-fixed \
  --control RHDHBUGS-4477=known-duplicate \
  --out sample.json
```

The selector:

- excludes anything younger than `--aged-days`;
- excludes customer-linked tickets and anything already Done;
- stratifies by Team, then by the first component, then `Unowned`;
- orders each stratum by a stable hash of `seed:key`, so the same export and seed
  give the same list on any machine;
- appends the controls after the aged sample and labels them.

Use 12–15 aged tickets. Add controls only when a reviewer already knows the
answer; a control that is itself uncertain teaches nothing. If the export is
missing fields the selector needs, stop and fix the export rather than guessing.

## 3. Collect evidence

```bash
python3 scripts/run_poc.py collect \
  --input export.json \
  --sample sample.json \
  --out evidence
```

For each ticket the collector records:

- the ticket facts, customer signals, links, and fix/affects versions;
- every PR URL found in the ticket text and links;
- PR state from the cache, or from read-only `gh` calls when `--gh` is set;
- PRs found by searching the ticket key **and** the Jira keys it mentions or
  links to, each tagged with the key that found it (`foundVia`);
- other Jira keys mentioned in the text;
- up to three distinctive search phrases for a live duplicate search.

Use [../references/evidence-sources.md](../references/evidence-sources.md) to
extend this with code inspection, release notes, and a current-release
reproduction. `/rhdh-forge` owns the PR and commit read mechanics, and
`/rhdh-backport` owns backport rules; this skill only records what they return as
evidence.

## 4. Adjudicate each ticket twice

Create one assessment per ticket:

```bash
python3 scripts/run_poc.py template --sample sample.json --out assessments
```

Fill the template with a disposition, evidence, and notes. Then run the
adjudication again in a fresh context — a new session or a second reviewer — and
record both results under `review`:

```json
"review": {"independentPasses": 2, "agree": true}
```

The second pass must not copy the first. It re-reads the ticket and the evidence
and reaches its own disposition. If the passes disagree, set `agree` to `false`
and record the disagreement in `notes`; the policy will refuse a close.

Rules the adjudicator follows:

1. Every evidence item names a type, a reference, why it matters, and a strength
   (`direct`, `strong`, or `supporting`). A claim without a reference is dropped.
2. `duplicate` names the target key. `/rhdh-jira-authoring` owns what counts as
   the same bug; this skill applies that definition and adds the close gates
   below. The duplicate candidate list is a retrieval aid; a reviewer still
   decides whether the failures are the same. The target is the older report and
   may already be closed. Only an outward Jira Duplicate link ("this ticket
   duplicates the target") supports a close; an inward "is duplicated by" link
   means the other ticket is the duplicate. A candidate newer than this ticket is
   a hint, never a close target.
3. `already_fixed` names the PR or commit, the release that carries it, and that
   the fix is released. Merged but unreleased is a comment, not a close. The fix
   release must be no newer than the release under review; a fix that first ships
   later keeps the ticket open. A fix recorded under a linked bug's key still
   counts when the citation is direct.
4. `still_valid` names the reproduction or the code path that proves it.
5. `no_longer_valid` names the removal, the changed behavior, or the failed
   reproduction on a supported release.
6. If the evidence cannot support any of these, use `needs_repro` or `unclear`.
7. Do not invent a confidence number. The policy computes it.

Read [../references/disposition-rubric.md](../references/disposition-rubric.md)
before the first pass.

## 5. Run the policy and render the report

```bash
python3 scripts/run_poc.py run \
  --input export.json \
  --sample sample.json \
  --assessments assessments \
  --out report \
  --current-release 2.1.0
```

The run writes:

```
report/
  report.md            one file: numbers, close proposals, then one section per
                       ticket (verdict, evidence, next step, proposed comment)
  packets.json         structured packets used by evaluation and tooling
  summary.csv          one row per ticket for a spreadsheet
  manifest.json        inputs, counts, thresholds, and `writes: []`
  proposed/KEY.md      the exact comment that would be posted, then review details
```

The policy downgrades, never upgrades. A close that misses a gate becomes
`comment_only`; a weak packet becomes `needs_repro`; a customer-linked ticket
cannot close at all. The verifier re-checks each close and fails closed. Every
ticket gets a proposed comment, including `unclear` and `needs_repro`, so no
triaged ticket leaves without a written trace.

Each `proposed/KEY.md` opens with the comment exactly as it would appear in Jira:
terse, with Jira keys and the cited PRs, commits, or releases as Markdown links,
and one recommendation. The review details below the rule justify that comment;
they are not meant to be posted.

## 6. Review before anyone acts

Read `report.md` in this order:

1. **Bottom line** — how many tickets can close, stay open, need a reproduction,
   or are unclear.
2. **The tickets** — one section per ticket, in sample order. Does each verdict
   match the evidence under it, and is "Do this next" the action you would take?
3. **Close proposals to review** — open `proposed/KEY.md` and read the comment
   first. Confirm that every Jira key and URL resolves, that the recommendation
   matches the action, and that the review details cite the same evidence. Then
   check the gaps for anything the comment overstates.
4. **Method and limits** — confirm the corpus reached closed tickets, and that the
   report's caveats match what the evidence can support.

Reject any packet whose recommendation is stronger than its citations. Record the
reason in the review notes; do not silently edit the disposition.

## 7. Hand off

Present the report and the close proposals to the human who owns the queue. For
each approved proposal, hand the exact comment from `proposed/KEY.md` and its
target to `/rhdh-jira-update`; that skill states the operation, preview, and
failure behavior under `/mutation-gate` and executes only after approval. The
review details are for the human, not for Jira. For a still-valid bug, hand the
packet to `/rhdh-plugin-bug-fix`. For an unclear or needs-repro ticket, send the
proposed comment through `/prose-editing` and stop. Any comment a human intends
to post goes through `/prose-editing` once before approval; nothing is posted
without an explicit gate.

## Optional: score the pass

If the sample includes controls or a reviewer supplied ground truth, write a
truth file and evaluate:

```bash
python3 scripts/run_poc.py evaluate \
  --packets report/packets.json \
  --truth truth.json \
  --out report/evaluation.md \
  --strict
```

A false close is the hard failure. Decision-ready rate is a quality signal, not a
target to game: an honest abstention is better than a confident wrong close.
