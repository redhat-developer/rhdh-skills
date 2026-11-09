# Testing the aged-bug triage skill

Two levels are supported: a fixture run that needs no Jira access, and a real
dry run against an export or a live read session. Both are read-only.

## Prerequisites

- Python 3.9 or newer.
- `uv` for the repository tests, or plain `python3` for the bundled CLI.
- Optional: `acli` authenticated for Jira reads, and `gh` authenticated for
  read-only PR evidence. Neither is required for the fixture run.

From the repository root:

```bash
uv sync --extra dev
```

## Fixture run

The fixtures live at `tests/unit/fixtures/bug_triage/` and contain 12 issues:

- 5 aged bugs eligible for the sample;
- 3 customer-linked bugs that must be excluded;
- 1 young bug that must be excluded;
- 1 Done duplicate that must be excluded;
- 2 controls: one still valid, one duplicate.

### 1. Select the sample

From the repository root:

```bash
python3 skills/jira/rhdh-bug-triage/scripts/run_poc.py select \
  --input tests/unit/fixtures/bug_triage/issues.json \
  --size 5 \
  --control RHDHBUGS-1009=still-valid \
  --control RHDHBUGS-1010=duplicate \
  --as-of 2026-11-09 \
  --out /tmp/bugtriage-sample.json
```

Expected: 7 tickets in the manifest — 5 aged plus 2 controls. The customer
tickets `RHDHBUGS-1003`, `RHDHBUGS-1004`, and `RHDHBUGS-1005` are excluded, as
are the young `RHDHBUGS-1008` and the Done `RHDHBUGS-1012`.

### 2. Run the policy and report

```bash
python3 skills/jira/rhdh-bug-triage/scripts/run_poc.py run \
  --input tests/unit/fixtures/bug_triage/issues.json \
  --sample /tmp/bugtriage-sample.json \
  --assessments tests/unit/fixtures/bug_triage/assessments \
  --out /tmp/bugtriage-run \
  --current-release 2.1.0 \
  --as-of 2026-11-09
```

Expected output:

```
DRY RUN complete: 7 packet(s) in /tmp/bugtriage-run
  with cited evidence: 5
  local close proposals: 2
  customer-linked: 0
  dispositions: {'already_fixed': 1, 'duplicate': 2, 'still_valid': 2, 'unclear': 2}
  actions: {'comment_only': 1, 'keep_open': 2, 'needs_repro': 2,
            'propose_close_duplicate': 1, 'propose_close_fixed': 1}
Nothing was posted, transitioned, linked, or written to Jira.
```

Two close proposals are expected:

- `RHDHBUGS-1006` — `propose_close_fixed`, because the fixture has a merged PR
  and a released fix;
- `RHDHBUGS-1010` — `propose_close_duplicate`, because the fixture carries an
  explicit Jira Duplicate link.

`RHDHBUGS-1002` is a deliberate near miss: the assessment says duplicate, but the
lexical score is 0.71, below the 0.85 close floor. It must be `comment_only`. If
it closes, the policy is broken.

### 3. Inspect the artifacts

```bash
ls /tmp/bugtriage-run
sed -n '1,120p' /tmp/bugtriage-run/report.md
sed -n '1,80p' /tmp/bugtriage-run/proposed/RHDHBUGS-1002.md
python3 -m json.tool /tmp/bugtriage-run/manifest.json | grep -A2 writes
```

Confirm:

- every artifact starts with the dry-run banner;
- `manifest.json` has `"writes": []`;
- no `proposed/` file says the comment was posted;
- `RHDHBUGS-1002` contains "not a close proposal";
- no customer-linked ticket appears in the sample.

### 4. Evaluate

The fixture truth file is at
`tests/unit/fixtures/bug_triage/truth.json`.

```bash
python3 skills/jira/rhdh-bug-triage/scripts/run_poc.py evaluate \
  --packets /tmp/bugtriage-run/packets.json \
  --truth tests/unit/fixtures/bug_triage/truth.json \
  --out /tmp/bugtriage-run/evaluation.md \
  --strict
```

Expected: coverage 100%, no false closes, decision-ready rate at least 80%.
`--strict` exits 1 on a false close or a decision-ready rate below 0.8.

## Repository tests

```bash
cd /home/fndlovu/Documents/rhdh-agentic-strategy/rhdh-skills
uv run pytest tests/unit/test_bug_triage.py -q
```

The suite covers normalization, customer filtering, deterministic selection,
duplicate scoring, every close gate, invalid evidence, report rendering, the
end-to-end fixture run, evaluation, adapters, catalog membership, and the
dry-run invariant that no write verb exists in the scripts.

Before committing:

```bash
uv run ruff format skills/jira/rhdh-bug-triage/scripts tests/unit/test_bug_triage.py
uv run ruff check skills/jira/rhdh-bug-triage/scripts tests/unit/test_bug_triage.py
uv run pytest
```

## Real dry run

### Option A: live Jira reads

```bash
cd skills/jira/rhdh-bug-triage
python3 scripts/run_poc.py check --json
python3 scripts/run_poc.py select --source acli --size 12 --out /tmp/live-sample.json
```

`check` reports whether `acli` is installed and whether a read smoke check
passes. If it is unreadable, authenticate with `acli jira auth login` or use
Option B. Do not paste a token into a command, a file, or the conversation.

### Option B: offline export

Produce a JSON file through the host Atlassian adapter, an MCP Jira tool, or a
saved search. The loader accepts:

```json
{"issues": [{"key": "RHDHBUGS-1234", "fields": {"summary": "..."}}]}
```

a bare list of the same issue objects, or the flatter records `acli --json`
emits. A `fieldNames` map may translate custom field IDs:

```json
{
  "fieldNames": {"customfield_10746": "Customer Name"},
  "issues": []
}
```

Then run the same commands with `--source export --input /tmp/rhdhbugs.json`.
Keep the export local; it may contain customer field values. The selector removes
customer-linked tickets, but the raw file should still be treated as internal.

### Sample size and controls

Use 12–15 aged tickets. Add 1–3 controls whose disposition you already know; they
are the fastest way to catch a policy regression. A control can be a known
duplicate, a bug fixed in a release you can name, or a still-valid bug with a
current reproduction. Do not use an uncertain ticket as a control.

### Writing assessments

```bash
python3 scripts/run_poc.py template --sample /tmp/live-sample.json --out /tmp/live-assessments
```

Fill one file per ticket. The full schema is in
[references/report-schema.md](references/report-schema.md). Two rules matter most:

1. Cite something for every claim. An uncited item is dropped and counted as a
   gap.
2. Run the adjudication twice in independent contexts and record both passes.
   A close with `independentPasses` below 2 or `agree: false` cannot close.

### Review checklist

- Does the report's decision-ready rate include abstentions honestly?
- Does every close proposal have a direct citation a reviewer can open?
- Is every customer-linked ticket either absent or explicitly close-disabled?
- Does every `already_fixed` proposal name a release and `released: true`?
- Does every duplicate proposal clear 0.85 or carry an outward Duplicate link?
- Are the evidence gaps plausible for the export, or is the adapter dropping
  fields?
- Did the verifier downgrade anything? Read the reason before overriding it.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `acli failed: unauthorized` | No Jira session | `acli jira auth login`, or use an export |
| Selector returns fewer than `--size` | Too few eligible tickets after the customer/age filter | Widen the export, lower `--aged-days`, or accept the smaller sample and say so |
| `sample names tickets missing from the export` | The sample and export are from different searches | Regenerate the sample from the same export |
| `invalid assessment` | Malformed JSON or a missing `key` | Fix the file; the run aborts rather than guessing |
| Close proposal became `comment_only` | A gate failed | Read `gaps` and `verificationErrors`; do not hand-edit the packet |
| Every ticket is `needs_repro` | No assessments, or evidence was dropped | Check the assessment files and the evidence `ref`/`why` fields |
| Duplicate scores look low | The export has no description or error text | Enrich the export; lexical retrieval needs text |

## What not to test

Do not assert exact prose, heading order, or menu text. Test behavior: the
sample membership, the action each gate produces, the dry-run invariant, the
artifact set, and the exit codes.
