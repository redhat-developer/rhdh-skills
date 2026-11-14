# Remediation procedures

The standard procedure for each action class. A sweep that writes without
following this is guessing with write access. Every procedure starts with
[investigation.md](investigation.md); none of them starts from the field's name.

## Ground rules

1. **Empty only.** Every procedure fills a field that is empty. A set field is
   not a finding, even when it looks wrong; report the disagreement and stop.
2. **State the basis.** Every value carries the evidence that produced it — the
   parent key, the comparable issue, the acceptance criteria, the phase — into
   the comment and the receipt.
3. **Evidence decides between writing and blocking.** Sufficient evidence writes.
   Insufficient evidence blocks with one question. It never becomes a plausible
   number and never becomes a waiver the bot grants itself.
4. **Read back.** A write is complete when the issue is re-fetched and the field
   holds the value.
5. **Prose gets one pass.** Release Note Text and comment bodies go through
   `/prose-editing` once for the whole batch, in the **flavored** register.
6. **Order matters.** Derive parent-dependent values before estimating children,
   so a child inherits the corrected parent rather than the old one.

## Comment policy

One marker comment per distinct batch of changes on an issue, written by
`scripts/apply.py` after the fields land.

| Situation | Comment |
|---|---|
| A field changed | Yes — every change in that batch, with its basis |
| Nothing changed on the issue | No comment |
| A decision needs a person | No comment; it goes in the summary with the options |
| A person already exempted the issue | No comment; the exemption stands |

Address the assignee. When the issue is unassigned, address the reporter — they
raised it, so they are the only person with context. When both are absent, post
without a mention and surface the issue as an escalation.

The comment says what was done and why. It never asks for the work, because the
work was done. If the change is one a human should reverse, it says how: clear
the field, or reply with the reason the basis is wrong.

## `LINT-COMPONENT` — derive

1. The parent Epic or Feature has one or more components → copy that set.
2. No parent component → identify the affected subsystem from the description,
   acceptance criteria, and links, and match it against the component catalog in
   `/rhdh-jira-api`. Set only when exactly one component fits.
3. Two components fit, or none does → `choose` and escalate. A component is an
   ownership claim, so a wrong one routes work to the wrong team.

## `LINT-PRIORITY` — derive, or escalate

Inheritance comes first:

1. The parent has a defined priority → inherit it.
2. The parent has none → classify from stated impact and urgency:

| Priority | Evidence it needs |
|---|---|
| Blocker | Production outage, data loss, or an exploitable security defect with no workaround, in the current release |
| Critical | Major user-facing breakage, release-blocking, workaround costly or unavailable |
| Major | Standard work with a clear user or business outcome and no urgency signal |
| Minor | Cosmetic or low-impact change with no delivery pressure |

**The sweep never writes Blocker or Critical on its own.** Those two change
release scope and require a named exception; the finding is escalated with that
recommendation. The sweep may write `Major` or `Minor` when the evidence above is
present, and must say which row it used.

## `LINT-POINTS` — estimate

Use the Fibonacci scale and its scope descriptions in `/rhdh-jira-authoring`.
Read the issue's own scope, not its title alone.

| Evidence | Points |
|---|---|
| `SPIKE:` summary, time-boxed | 2 or 3, never more |
| 1–2 acceptance criteria, one area, no new tests | 1 or 2 |
| 3–5 criteria, new unit or integration tests, small doc change | 3 |
| Multiple PRs or several codebase areas | 5 |
| Research or unknowns, external library, cross-team review | 8 |
| Unbound scope | Do not write 13; escalate for a split or a spike |

Do not estimate when the description has no scope signals — no acceptance
criteria, no affected area, and nothing to distinguish a one-day change from a
two-week one. That issue is unsized because it is not yet understood. Mark it
blocked and ask the one question that changes the answer: what is the scope?

## `LINT-SIZE` — estimate

T-shirt sizes describe effort in sprints, not story points. Use
`/rhdh-jira-authoring` for the bands.

1. Epic with sized child Stories → sum their points into sprints (use the team's
   current velocity; if it is unknown, block rather than assume) and place the sum
   in the band.
2. Feature with sized child Epics → the Feature is at least its largest Epic;
   several L or XL children make it L or XL regardless of the arithmetic.
3. No sized children → use the scope signals only if the description is specific
   enough to distinguish the bands. Otherwise block.
4. `XL` is a finding in itself: record that the issue is a split candidate; do
   not quietly set the largest value to close the rule.

## `LINT-FIXVERSION-MULTI` — derive, or escalate

Keep one version, chosen in this order:

1. The links, the PR target, or the description name the release the work is
   actually for → keep that one.
2. The parent has exactly one Fix Version → use it.
3. Exactly one of the current versions is in an active release phase → keep it.
4. Otherwise → escalate. Two plausible releases is a delivery commitment, not a
   formatting problem, and the move/descope question is the owner's.

Never invent a version that is not already on the issue, its parent, or a linked
issue.

## `LINT-RN-STATUS` — derive

Type is set and is not `Release Note Not Required`, status is empty → set
`Proposed`. This one is mechanical; it records that the note exists and awaits
review. Do not set it when the type is `Release Note Not Required`.

## `LINT-RN-TYPE` — classify

Use the decision tree and the type indicators in `/rhdh-feature-docs`, then map
the result onto the values the field actually accepts. Two deterministic
shortcuts:

- The component is marked in the catalog's `Excl RN` column → `Release Note Not
  Required`.
- The issue is a Bug → `Bug Fix`.

Otherwise classify from what the change does, not from the words in the title
alone. Adjacent types (`Feature` versus `Enhancement`, `Developer Preview`
versus `Tech Preview`) are a product statement, not an inference: if both fit,
mark it blocked for the product owner.

## `LINT-RN-TEXT` — draft

1. Resolve the Release Note Type first. Without it there is no register to write
   in and no requirement to write at all.
2. Draft from the summary, the outcome, and the acceptance criteria. Say what a
   user can now do or what changed for them; do not restate the implementation.
3. Convert to ADF through `/rhdh-jira-api`; Release Note Text is a rich-text
   field and a Markdown paragraph lands as literal characters.
4. One prose pass over the whole batch, then write.

## Freeze rules — escalate

`LINT-FF-PRIORITY`, `LINT-CF-PRIORITY`, and `LINT-GA-OPEN` are never written by
a sweep. Each is a release commitment, and the three legitimate answers have
different owners:

| Option | Owner | Cost |
|---|---|---|
| Move the Fix Version to a later release | Owner + PM | The work misses this release |
| Escalate the priority | PM + Release Manager | Freeze scope grows; needs a named exception |
| Descope or close | Owner + PM | The work stops being tracked here |

Prepare all three with the issue key, the phase boundary, the current priority,
and the exact command for each option. Send one summary per owner, not one
message per issue. `Release` component issues are exempt from the freeze priority
rules because publishing and release-file work happens after the freeze; they are
not exempt from `LINT-GA-OPEN`.

## Existing exemption — honor, or escalate its expiry

A label of `hygiene-waived` means a person decided the blank is deliberate. Leave
it alone and do not comment.

A `hygiene-waived-YYYY-MM` label past its month is a decision that has gone stale.
Do not silently renew it and do not create a replacement. Escalate it with the
three options: renew with a new reason, fix the field, or retire the exemption
because the rule no longer applies.

## Receipt

The sweep ends with one table: issue, rule, action, before, after or reason.
Completed operations carry both values; blocked ones carry the evidence they
need; escalated ones carry the options. The receipt is the evidence that the
sweep happened, and it is what the next sweep diffs against.
