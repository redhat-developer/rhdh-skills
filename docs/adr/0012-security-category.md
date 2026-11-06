# Security editorial category

**Status:** Accepted.

## Context

CVE and Dependabot work for RHDH spans more than one existing folder: plugin
monorepo impact classification and workspace bumps, release-train overlay CVE
exports, and (later) the `rhdh` application tree. Putting the first skill under
`plugins/` would mislead installers once the same tool covers `rhdh`, and
`release/` already owns a different job (`rhdh-overlay-cve-export`).

`npx skills add` groups by catalog category (ADR-0009). A coherent security
install group needs a named category, not a misfiled skill.

## Decision

Add an editorial category `security` beside `jira`, `plugins`, `ci`, `release`,
`refinement`, `reference`, and `meta`:

- Source path: `skills/security/<name>/`
- Catalog: `"security"` in `categories` and on each member skill
- Installer: one marketplace plugin group labelled Security

The first member is `rhdh-package-impact` (Dependabot / yarn.lock impact
classify, patch-status, workspace bump, and policy-gated dismiss). Folder
membership does not change invocation: callers use `/rhdh-package-impact`.

Keep `rhdh-overlay-cve-export` in `release/` — it answers a release CSV
question, not day-to-day Dependabot triage.

## Consequences

- Contributors place new CVE / Dependabot / vulnerability-triage skills under
  `security/` when that is the subject, not under `plugins/` by default.
- README, `CONTRIBUTING.md`, `AGENTS.md`, and `CONTEXT.md` list eight editorial
  folders (plus `third-party/`).
- Expanding classify/bump to the `rhdh` monorepo stays a layout adapter inside
  the skill; it does not force a category move.
