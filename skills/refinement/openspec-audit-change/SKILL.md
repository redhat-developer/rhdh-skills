---
name: openspec-audit-change
description: >-
  Adversarially audits an OpenSpec change's artifacts against each other —
  and lightly against the codebase and repository conventions — for
  cross-artifact consistency before implementation. Use for "audit this
  change" or "run the audit". This is pre-implementation artifact
  coherence; for post-implementation code-vs-artifact verification, use
  openspec-verify-change instead.
compatibility: "openspec CLI preferred; filesystem fallback supported under openspec/changes/<name>/ when the CLI is unavailable."
---

# Audit an OpenSpec change

Spawn an isolated auditor over one change's artifacts, catch cross-artifact
drift before code gets written, and never claim a clean audit the checks
did not actually confirm.

## Steps

1. **Select the change.** If not given, run `openspec list --json`, show
   active (non-archived) changes with schema, and let the user choose. Never
   guess.
2. **Gather artifacts and convention docs.** Run
   `openspec status --change "<name>" --json` and
   `openspec instructions apply --change "<name>" --json`; collect every
   artifact path from `contextFiles` plus `.openspec.yaml`. If the CLI is
   unavailable, fall back to filesystem discovery under
   `openspec/changes/<name>/`. Locate repo-root convention docs
   (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`) and the schema's
   `context`/`rules` if available from `/rhdh-spec-driven-schema`.
3. **Enforce the apply-ready minimum before doing anything else.** Build the
   union of the schema's `apply.requires` (or CLI `applyRequires`) and
   `{proposal, design, specs, tasks}`. Preferred: every ID in that union must
   show `status: "done"` in the status JSON. Filesystem fallback: read
   `.openspec.yaml` for the schema name, read that schema's `apply.requires`,
   and check each mapped path exists and is non-empty
   (`proposal`->`proposal.md`, `design`->`design.md`, `tasks`->`tasks.md`,
   `specs`->at least one `specs/**/spec.md`). If the required set cannot be
   determined, or any required artifact is missing/not done: report CRITICAL,
   state "**Audit blocked (CRITICAL findings remain)**", write/update
   `audit.md` with the current UTC timestamp, suggest
   `/openspec-continue-change`, and **stop** — do not build the ownership map
   or spawn the auditor.
4. **Build a cross-change ownership map.** Resolve sibling changes (reuse
   `openspec list --json` from step 1, or filesystem-list
   `openspec/changes/*` excluding this change and `archive/`). For each
   sibling, read only its `proposal.md` Canonical Touchpoints section and
   `design.md` Decisions section, and build a lightweight
   `capability/namespace/claim -> [change names]` map. Pass the map (or
   condensed claim lines), not full sibling trees, to the auditor. If sibling
   discovery fails entirely, pass an empty map and note category E ran
   degraded in the final report — do not fail the whole audit for this alone.
5. **Spawn an independent auditor subagent** (Task tool,
   `subagent_type: general-purpose`). Give it only: change name, absolute
   artifact paths, the ownership map, convention doc paths, the checklist
   below, and the required JSON return schema. Explicitly forbid passing
   authoring rationale or "what we meant" — this is prompt isolation, not a
   sandbox; instruct it to limit reads to the given paths. Require it to
   return:

   ```json
   {"findings": [{"category": "A|B|C|D|E|F|G|H", "severity": "CRITICAL|WARNING|SUGGESTION", "file": "openspec/changes/<name>/design.md", "line": 1, "quote": "short excerpt", "recommendation": "actionable fix", "autofixable": true}]}
   ```

   `file` must be repo-root-relative; normalize any absolute paths before
   writing `audit.md`. **Fail-closed:** if the subagent fails, times out, or
   returns malformed findings, treat it as CRITICAL — write/update `audit.md`
   with that CRITICAL and the current UTC timestamp, state "**Audit blocked
   (CRITICAL findings remain)**", report the failure, suggest retrying, and
   **stop**. Only a parseable `{"findings": [...]}` — including an empty
   array — may proceed to the fix loop.
6. **Auditor checklist (all categories evaluated):**

   | ID | Category | Catches | Autofixable |
   |----|----------|---------|-------------|
   | A | Entity propagation | Name/value fixed in design.md (or proposal.md) not identically propagated to sibling artifacts | Yes, if one unambiguous spelling |
   | B | Enum / vocabulary | Enumerated sets with different membership/count across files or vs `openspec/specs/<capability>/` | Yes, if superset unambiguous |
   | C | Semantic contradiction | Design fails to satisfy spec WHEN/THEN; Non-Goals vs Decisions; non-deterministic outcomes; Verify scoped differently than the task | No |
   | D | Codebase & convention grounding | References to APIs/tickets/modules that don't exist; mechanisms violating loaded house rules | No |
   | E | Namespace & cross-change ownership | Unresolved `openspec/changes/<id>/` refs; claim shared with a sibling with no reconciliation note | No |
   | F | Template/copy-paste residue | Literal paths/prefixes from a different project than this repo | Yes, if correct target unambiguous |
   | G | Extended coherence | Helper signature vs call sites; shared exports not tasked into consumers; lifecycle semantics missing/inconsistent across artifacts | Yes when a name/signature is already fixed and merely missing in siblings; no for any WHEN/THEN or product-policy choice |
   | H | Security lint | Mutating/admin routes with no authorize story; ambiguous DENY outcomes; hidden-count exposure; secrets in examples | Only if design already named the permission and wiring is obvious |

   Never hardcode product-specific banlists — categories D and H load
   constraints from project convention files and schema context. When
   uncertain, prefer SUGGESTION over WARNING, WARNING over CRITICAL.
7. **Fix-and-reaudit loop, up to 3 passes.** Collect autofixable findings with
   one unambiguous canonical value (prefer the value in `design.md`
   Decisions; else the most frequent spelling agreeing with the proposal's
   Capabilities names). If none, stop the loop. Otherwise list the proposed
   mechanical fixes and ask the user: apply this batch, or skip autofix
   (report-only for remaining passes). On confirm, apply edits and
   re-spawn the auditor (same isolation and fail-closed rules); on skip,
   break and proceed to reporting with current findings. Never auto-apply
   non-autofixable (judgment-call) findings, and never apply any fix without
   explicit confirmation.
8. **Generate the audit report.** Write `openspec/changes/<name>/audit.md`
   (and show the same content in chat) using
   [references/audit-report-template.md](references/audit-report-template.md),
   keeping its section structure. Always set **Last audited** to the current
   UTC time when writing. Every finding needs a repo-root-relative file
   reference and an actionable recommendation. A severity section with no
   findings must contain exactly `- None`.
9. **Report the outcome.** Any CRITICAL remaining: state "**Audit blocked
   (CRITICAL findings remain)**" and list blockers — never claim a clean
   audit. No CRITICAL: state "**Audit clean (no CRITICAL)**" (WARNINGs may
   still be listed) — never say "Ready for implementation." Always close
   with: "Fixes to one file can introduce new drift elsewhere — re-run the
   audit after resolving remaining findings." This is advisory output; it
   does not gate `/openspec-apply-change` or `/openspec-archive-change`.

## Guardrails

- Never skip the independent auditor subagent for a full audit.
- Fail-closed on subagent failure — never claim a clean audit from a failed
  or malformed response.
- Never invent product-specific rules in this skill's own body — load them
  from project files.
- Never pivot into design-decision grilling for unresolved findings — report
  them only.
- Never apply autofixes without explicit confirmation; cap confirmed autofix
  loops at 3 passes.
- Always run the apply-ready minimum check before the ownership map or
  subagent — an incomplete change is CRITICAL and stops the audit early.

## Completion

Complete when `audit.md` reflects the latest auditor pass (or the latest
CRITICAL blocker) with a current UTC timestamp, every finding carries a
repo-root-relative file reference and recommendation, and the user has been
told explicitly whether the audit is blocked or clean — never left to infer
it.
