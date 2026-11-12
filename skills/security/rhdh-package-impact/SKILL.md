---
name: rhdh-package-impact
description: >-
  Classifies whether an npm package in a Backstage-style plugins monorepo
  (rhdh-plugins / community-plugins, workspaces/<name>/) or the RHDH core repo
  (redhat-developer/rhdh, root yarn.lock) reaches shipped code (PLUGIN_PROD /
  CORE_PROD), plugin or core dev harnesses, local runners (plugins monorepo
  only), or workspace root (WORKSPACE_DEV). Discovers packages from open
  Dependabot alerts, classifies impact, checks first_patched_version, and
  bumps via yarn up -R. Use when assessing Dependabot alerts, CVE bumps on
  rhdh-plugins, community-plugins, or rhdh core, deciding if a CVE is
  runner-only vs shipped, or interactively closing Dependabot alerts.
---

# plugins package impact

## Goal

For a **plugins-monorepo workspace** (`rhdh-plugins` / `community-plugins`) or
the **RHDH core repo** (`redhat-developer/rhdh`; [references/rhdh-core.md](references/rhdh-core.md)):

1. **Discover** packages from open Dependabot alerts under that workspace’s manifests.
2. **Classify** each package (plugin prod / core prod / plugin dev / runner / workspace root).
3. **Check patch status** vs Dependabot `first_patched_version` — especially `PATCHED_EXCEPT_RUNNER` (plugins monorepo only).
4. **Dismiss** only when policy allows (runner-only, plugin-dev-only, workspace-dev-only, or runner-manifest alert-level).

Dismissal targets **local-dev** paths that are **exactly** `RUNNER`, **exactly** `PLUGIN_DEV`, **exactly** `CORE_DEV`, or **exactly** `WORKSPACE_DEV` — never `PLUGIN_PROD` or `CORE_PROD`. On rhdh core, `packages/app` and `packages/backend` **ship**; they are `CORE_PROD`, not `RUNNER`.

## Classifications

| Label | Meaning | Customer impact |
|-------|---------|-----------------|
| `PLUGIN_PROD` | Reached via a published plugin's `dependencies` or `peerDependencies` (incl. direct deps of those peers, e.g. `react-router` via peer `react-router-dom`) | **high** — fix/bump; do not dismiss prod alerts |
| `CORE_PROD` | RHDH core: `packages/app`, `app-next`, `backend`, `plugin-utils` production deps | **high** — ships in RHDH; never dismiss |
| `PLUGIN_DEV` | Reached via plugin `devDependencies` / local harness / tests | local-dev — dismissable when exact (see policy). Still **bump when practical** for SBOM hygiene |
| `CORE_DEV` | RHDH core: those packages' `devDependencies` only | local-dev / SBOM — dismissable when exact; prefer bump |
| `RUNNER` | Plugins monorepo: `packages/app`, `app-legacy`, or `backend` | local-dev — dismissable when exact. **Not used on rhdh core** |
| `WORKSPACE_DEV` | Workspace root `devDependencies` | local-dev — dismissable when exact; still **bump when practical** for SBOM |
| `UNKNOWN` | Could not map; inspect `yarn why` | unknown |

Combined labels join with `+` (e.g. `PLUGIN_PROD+RUNNER`).

### Per-alert manifest hint

Dependabot alerts are per `manifest_path` (+ optional `scope`). Map a single alert:

| `manifest_path` | scope | Alert class |
|-----------------|-------|-------------|
| `…/packages/(app\|app-legacy\|backend)/package.json` | any | **RUNNER** on plugins monorepo; **CORE_PROD** on rhdh core (never dismiss) |
| `…/plugins/…/package.json` | `runtime` | **PLUGIN_PROD** — never dismiss |
| `…/plugins/…/package.json` | `development` | **PLUGIN_DEV** — dismissable when exact; prefer bump for SBOM |
| `…/yarn.lock` (or other) | — | package-level dismiss only if aggregate is exactly `RUNNER` / `PLUGIN_DEV` / `CORE_DEV` / `WORKSPACE_DEV` |

## Dismissal policy (hard rules)

### A. Package-level (all matching alerts for a workspace)

Safe when aggregate classification is **exactly `RUNNER`**, **exactly `PLUGIN_DEV`**, **exactly `CORE_DEV`**, or **exactly `WORKSPACE_DEV`**. Then you may dismiss open alerts for that package under the workspace manifest(s) (interactive `--close`).

Mixed labels (e.g. `RUNNER+WORKSPACE_DEV`, `PLUGIN_DEV+RUNNER`, anything with `PLUGIN_PROD` or `CORE_PROD`) are **not** package-level dismissable unless they reduce to one of the exact labels above.

#### `PLUGIN_DEV` / `CORE_DEV` / `WORKSPACE_DEV` and SBOMs

Exact findings are **not product/runtime vulnerabilities** — Dependabot dismiss is appropriate. They can still appear in **SBOMs**; prefer a lockfile bump so dismissal is not the only cleanup.

### B. Alert-level (mixed impact — prod fixed / still open, runner alerts remain)

When aggregate classification **includes `PLUGIN_PROD`** (or any non-dismissable label):

1. **Still fix / bump** the published plugin production path; do **not** dismiss PLUGIN_PROD alerts.
2. **May dismiss** only alerts whose `manifest_path` is a **RUNNER** package.json (`packages/app`, `app-legacy`, or `backend`) when prod is patched / no open PLUGIN_PROD alerts remain (see patch-status script).
3. Pass that **exact runner manifest** to `close-dependabot-alerts.js` (not the workspace `yarn.lock` shortcut) so plugin alerts are untouched.
4. **Never dismiss** alerts for `plugins/…` when doing alert-level dismiss of a mixed package.

### C. Patched everywhere except runner

Use `check-dependabot-patch-status.js` to compare yarn.lock resolved versions to each alert’s `first_patched_version` / vulnerable range, and to count open alerts by manifest class.

| Verdict | Meaning | Action |
|---------|---------|--------|
| `RUNNER_ONLY` | Classification exactly `RUNNER` | Package-level dismiss OK |
| `PLUGIN_DEV_ONLY` | Classification exactly `PLUGIN_DEV` | Package-level dismiss OK (not a prod vuln); also **bump** when practical for SBOM hygiene |
| `WORKSPACE_DEV_ONLY` | Classification exactly `WORKSPACE_DEV` | Package-level dismiss OK (not a prod vuln); also **bump** when practical for SBOM hygiene |
| `PATCHED_EXCEPT_RUNNER` | No open `PLUGIN_PROD` alerts; runner alerts remain | Dismiss **RUNNER** `package.json` alerts only |
| `PLUGIN_PROD_ALERTS_REMAIN` | Still open alerts on `plugins/…` | Fix prod first — do not dismiss plugin alerts |
| `LOCKFILE_ALERTS_ONLY` | Only yarn.lock alerts; versions may look patched | Not `PATCHED_EXCEPT_RUNNER`; refresh/bump; exact `RUNNER` / `PLUGIN_DEV` / `WORKSPACE_DEV` may still dismiss at package level |
| `PROD_PATCHED_DEV_UNPATCHED` | Published plugin **production** paths are patched (`patched_prod=yes`); lockfile still has older versions on dev/runner/tooling paths | No open `PLUGIN_PROD` manifest alerts — treat as dev/SBOM hygiene unless `prod_resolved` is unpatched |
| `UNPATCHED_IN_LOCKFILE_NO_PROD_ALERTS` | Lockfile still vulnerable; no prod alerts | Review before dismiss |
| `FULLY_PATCHED` | Lockfile versions meet patch level; no prod/runner package.json alerts | Usually nothing to dismiss |
| other | Needs review | Do not auto-dismiss |

`safeToDismissPackageLevel: true` ⇒ package-level dismiss OK (`RUNNER_ONLY` / `PLUGIN_DEV_ONLY` / `WORKSPACE_DEV_ONLY`).  
`safeToDismissRunnerAlerts: true` ⇒ dismiss runner manifests (interactive); also true for package-level runner-only.

### Shared rules

1. **Never dismiss** `PLUGIN_PROD`, `CORE_PROD`, or `UNKNOWN` at package level. Mixed labels that include `PLUGIN_PROD` / `CORE_PROD` (or that are not exactly `RUNNER` / `PLUGIN_DEV` / `CORE_DEV` / `WORKSPACE_DEV`) are not package-level dismissable.
2. **Do not dismiss** unless the user explicitly asks to close alerts. Classify and recommend first.
3. **Interactive confirmation is required.** Run `--close` **without** `--yes` so the script prompts `[y/N]`. Do **not** pass `--yes` unless the user explicitly requests non-interactive dismissal.
4. **Fullsend: never call `close-dependabot-alerts.js`.** When `FULLSEND_OUTPUT_DIR` is set the script exits non-zero for any invocation (list or dismiss). Classify and bump only; dismiss stays human/out-of-band.

Default reason: `not_used`. Comment should cite classification, e.g. `runner-only in <workspace>; classification=RUNNER`, or `plugin-dev-only / workspace-dev-only in <workspace>; classification=…; not a prod vuln — prefer bump for SBOM hygiene`.

## Prerequisites

- Working directory (or `RHDH_PLUGINS_ROOT` / `RHDH_CORE_ROOT` / `--repo-root`) is either:
  - a plugins monorepo with `workspaces/<name>/yarn.lock`, or
  - rhdh core with a **root** `yarn.lock` + `packages/` (no `workspaces/` directory)
- Prefer `yarn install` in the target workspace before classifying
- `node` ≥ 18
- GitHub PAT (`GITHUB_TOKEN` / `GH_TOKEN` or a cwd-walked `.env`) for REST, **or** `--alerts-json` (no token)

RHDH core details, commands, and the CORE_PROD vs RUNNER rule: [references/rhdh-core.md](references/rhdh-core.md).

### `--repo` vs `--repo-root` vs `--alerts-json`

- `--repo <owner/name>` = **remote GitHub repository** queried by Dependabot REST API calls.
  - default resolution order: explicit `--repo`, then `GITHUB_REPOSITORY`, then `origin` remote from current checkout (or `--repo-root` for scripts that use it)
- `--repo-root <path>` = **local checkout path** used for `yarn.lock` + `yarn why` classification.
- `--alerts-json <file>` = **snapshot** of GitHub list-alerts objects (JSON array, or `{ "alerts": [...] }`). No REST. Dump with `gh api --paginate --slurp "repos/OWNER/REPO/dependabot/alerts?state=open"`. Must include `security_vulnerability` (ranges / `first_patched_version`) for patch-status. Token not required.

### Auth / API rules (agents)

- **Do not use the `gh` CLI** (`gh api`, `gh auth`, `gh auth token`, etc.) from these scripts.
- **Do not use `--token`**, git credential helpers, or hard-coded PATs in commands.
- Call Dependabot **only** through these skill scripts (`fetch` → REST) **or** `--alerts-json`.
- Under Fullsend (`FULLSEND_OUTPUT_DIR`): use the staged snapshot with `--alerts-json`; do not fetch alerts from the sandbox.
- Local impact analysis uses **yarn** (`yarn why -R`), not GitHub.

## Scripts

Skill scripts live in `scripts/` next to this file. Resolve `SKILL_DIR` to this skill directory (where `SKILL.md` lives).

### 1. Discover packages from Dependabot alerts (default input)

Pull open alerts for the workspace and compile the unique package list used for impact assessment:

```bash
GITHUB_TOKEN=… node "$SKILL_DIR/scripts/list-dependabot-packages.js" <workspace>
GITHUB_TOKEN=… node "$SKILL_DIR/scripts/list-dependabot-packages.js" <workspace> --json
node "$SKILL_DIR/scripts/list-dependabot-packages.js" <workspace> --alerts-json /path/to/dependabot-alerts.json
```

`<workspace>` may be `homepage`, `workspaces/homepage`, `rhdh` (core product lockfile), or `workspaces/homepage/yarn.lock`.

| Flag | Effect |
|------|--------|
| (default) | Plugins: all open alerts under `workspaces/<name>/`. RHDH core (`rhdh`): product `yarn.lock` + `packages/` + `plugins/` (not e2e/.ci) |
| `--exact-manifest` | Only the exact yarn.lock (or given file) path |
| `--json` | Packages + alert details |
| `--alerts-json <file>` | Use a runner snapshot; skip REST and token |
| (default stdout) | One package name per line (pipe-friendly); summary on stderr |

When the user names a workspace but does **not** supply a package list, **always start here** — do not invent packages.

### 2. Classify impact — for each discovered package

```bash
# Single package (detailed)
node "$SKILL_DIR/scripts/classify-cve-source.js" <workspace> <package> --repo-root /path/to/plugins-repo

# Multiple packages → markdown classification table (default)
node "$SKILL_DIR/scripts/classify-cve-source.js" --repo-root /path/to/plugins-repo \
  <workspace> pkg1 pkg2 pkg3

# Explicit table for one package
node "$SKILL_DIR/scripts/classify-cve-source.js" --repo-root /path/to/plugins-repo \
  <workspace> <package> --table

# JSON
node "$SKILL_DIR/scripts/classify-cve-source.js" --repo-root /path/to/plugins-repo \
  <workspace> <package> --json
```

Batch from Dependabot package list:

```bash
REPO=/path/to/plugins-repo
WS=homepage
pkgs=$(GITHUB_TOKEN=… node "$SKILL_DIR/scripts/list-dependabot-packages.js" "$WS")
node "$SKILL_DIR/scripts/classify-cve-source.js" --repo-root "$REPO" "$WS" $pkgs
```

### 3. Check patch level vs Dependabot fix (prod patched, runner alerts remain?)

```bash
# Markdown classification/patch table (default)
GITHUB_TOKEN=… node "$SKILL_DIR/scripts/check-dependabot-patch-status.js" \
  --repo-root /path/to/plugins-repo <workspace>

GITHUB_TOKEN=… node "$SKILL_DIR/scripts/check-dependabot-patch-status.js" \
  --repo-root /path/to/plugins-repo <workspace> <package> --json

node "$SKILL_DIR/scripts/check-dependabot-patch-status.js" \
  --repo-root /path/to/plugins-repo --alerts-json /path/to/dependabot-alerts.json <workspace>
```

For each package with open alerts, reports:

- `classification` / `customerImpact` (via classify)
- `resolvedVersions` from workspace `yarn.lock`
- `firstPatchedVersions` / vulnerable ranges from Dependabot
- `fullyPatchedInLockfile`
- `openAlertCounts` by manifest class (`PLUGIN_PROD`, `RUNNER`, `LOCKFILE`, …)
- `verdict` and `safeToDismissRunnerAlerts`

Use this when the user asks whether alerts can be dismissed because the package is patched everywhere except runners.

### 4. List / dismiss Dependabot alerts — only after classify / patch-status

**Fullsend:** do not run this script. When `FULLSEND_OUTPUT_DIR` is set it
exits non-zero for any invocation (list or dismiss). Report dismiss candidates
in the run summary only.

Dry run:

```bash
GITHUB_TOKEN=… node "$SKILL_DIR/scripts/close-dependabot-alerts.js" <workspace> <package> --json
```

Dismiss (interactive — **omit `--yes`**):

```bash
# Package-level RUNNER_ONLY / PLUGIN_DEV_ONLY / WORKSPACE_DEV_ONLY
GITHUB_TOKEN=… node "$SKILL_DIR/scripts/close-dependabot-alerts.js" <workspace> <package> \
  --close --reason not_used \
  --comment "runner-only in <workspace>; classification=RUNNER"

GITHUB_TOKEN=… node "$SKILL_DIR/scripts/close-dependabot-alerts.js" <workspace> <package> \
  --close --reason not_used \
  --comment "plugin-dev-only in <workspace>; classification=PLUGIN_DEV; not a prod vuln — prefer bump for SBOM hygiene"

GITHUB_TOKEN=… node "$SKILL_DIR/scripts/close-dependabot-alerts.js" <workspace> <package> \
  --close --reason not_used \
  --comment "workspace-dev-only in <workspace>; classification=WORKSPACE_DEV; not a prod vuln — prefer bump for SBOM hygiene"

# Alert-level PATCHED_EXCEPT_RUNNER — exact runner manifests only
GITHUB_TOKEN=… node "$SKILL_DIR/scripts/close-dependabot-alerts.js" \
  workspaces/<workspace>/packages/backend/package.json <package> \
  --close --reason not_used \
  --comment "prod patched; runner alert only; classification=…"
```

Defaults to detected remote repo (`--repo`, then `GITHUB_REPOSITORY`, then `origin` remote). Local analysis comes from `--repo-root` / current checkout.

### 5. Prepare bump branch (`prepare-workspace-bump.js`)

Before bumping interactively, reset a clean branch from `upstream/main`.
Under Fullsend, skip the reset — the runner already cloned and set up the
branch. Use `--verify-only` (or rely on auto-detect when `FULLSEND_OUTPUT_DIR`
is set) to check the lockfile only.

```bash
node "$SKILL_DIR/scripts/prepare-workspace-bump.js" --repo-root /path/to/plugins-repo <workspace>
node "$SKILL_DIR/scripts/prepare-workspace-bump.js" --repo-root /path/to/plugins-repo <workspace> --verify-only
node "$SKILL_DIR/scripts/prepare-workspace-bump.js" --repo-root /path/to/plugins-repo <workspace> --dry-run
node "$SKILL_DIR/scripts/prepare-workspace-bump.js" --repo-root /path/to/plugins-repo <workspace> --json
```

| Flag | Default | Effect |
|------|---------|--------|
| `--repo-root <path>` | cwd walk-up / `RHDH_PLUGINS_ROOT` / `RHDH_CORE_ROOT` | Plugins monorepo or rhdh core checkout |
| `--upstream <remote>` | `upstream` | Remote that tracks `redhat-developer/rhdh-plugins` |
| `--base <branch>` | `main` | Branch to `git fetch` / reset onto |
| `--branch <name>` | `chore/<workspace>-cve-bumps` | Local branch created with `checkout -B` |
| `--verify-only` | auto on Fullsend | Verify lockfile + report HEAD; no `git fetch` / `checkout` |
| `--reset-branch` | off | Force interactive reset even when `FULLSEND_OUTPUT_DIR` is set |
| `--dry-run` | off | Print plan only; no `git fetch` / `checkout` |
| `--json` | off | Machine-readable result on stdout |

Behavior:

1. Verifies `workspaces/<workspace>/yarn.lock` exists.
2. **Interactive (default):** `git fetch <upstream> <base>`, then
   `git checkout -B chore/<workspace>-cve-bumps <upstream>/<base>`.
3. **Fullsend / `--verify-only`:** report current branch/HEAD only. Do not
   fetch or checkout — that fights Fullsend’s clone/branch protocol.
4. Prints suggested next commands (`list-dependabot-packages.js`, then
   `bump-workspace-packages.js --json | format-bump-pr.js`).

Does **not** commit, push, open a PR, run `yarn`, or touch unrelated untracked
paths (e.g. other local workspace checkouts).

### 5a. Bump packages (`yarn up -R`)

Run `bump-workspace-packages.js` to `yarn up -R` one or more packages (or all
open-alert packages when none are named), then `yarn install` and `yarn dedupe`
(rhdh-plugins lockfile hygiene so CI `yarn install --immutable` matches), and
print a markdown table of version changes, classifications, open CVEs, and CVEs
that look fixed.

**Known no-major-bump packages** (see `same-major-yarn-up.js`, currently
`http-proxy-middleware`): bare `yarn up -R` can jump majors on wide
descriptors like `*` (e.g. 3.0.3 → 4.2.0 even though the CVE is fixed on
3.0.6+ and v4 is ESM-only). After `yarn up -R` for those packages only, the
script re-pins jumped descriptors to the latest prior major via
`yarn set resolution`. Do not generalize — add a package to the list when a
concrete case appears.

**Never `yarn up` `@backstage/*` or `@backstage-community/*`.** The bump script
skips those (status `skipped`) even when they appear in Dependabot alerts or
are named on the command line.

**Manual only** (do not automate via this script): complex lockfile cases such as
`fast-xml-parser` (dual major lines, `yarn set resolution`, targeted `yarn up` on
specific AWS clients). Handle those by hand after classifying impact.

```bash
node "$SKILL_DIR/scripts/bump-workspace-packages.js" --repo-root /path/to/plugins-repo <workspace>
node "$SKILL_DIR/scripts/bump-workspace-packages.js" --repo-root /path/to/plugins-repo <workspace> <package>…
node "$SKILL_DIR/scripts/bump-workspace-packages.js" --repo-root /path/to/plugins-repo <workspace> --json
node "$SKILL_DIR/scripts/bump-workspace-packages.js" --repo-root /path/to/plugins-repo --alerts-json /path/to/dependabot-alerts.json <workspace> --json
node "$SKILL_DIR/scripts/bump-workspace-packages.js" --repo-root /path/to/plugins-repo <workspace> <package> --dry-run
```

| Flag | Default | Effect |
|------|---------|--------|
| `--repo-root <path>` | cwd walk-up / `RHDH_PLUGINS_ROOT` / `RHDH_CORE_ROOT` | Plugins monorepo or rhdh core checkout |
| `--repo <owner/name>` | auto-detect | GitHub repo for Dependabot CVE metadata |
| `--alerts-json <file>` | — | Use a runner snapshot; skip REST and token |
| `--dry-run` | off | Report only; no `yarn up` / `install` / `dedupe` |
| `--no-dedupe` | off | Skip `yarn dedupe` after `yarn install` |
| `--no-ancestors` | off | Skip allowlisted leftover ancestor bumps (`qs`) |
| `--json` | off | Machine-readable result on stdout |

Behavior:

1. Resolves package list from argv or open Dependabot alerts under `workspaces/<workspace>/`.
2. Records lockfile versions **before** each bump.
3. Skips `@backstage/*` and `@backstage-community/*`. For each remaining package,
   runs bare `yarn up -R <package>` (Yarn forbids ranges with `-R`). For **known
   no-major-bump packages** (currently `http-proxy-middleware`), if a descriptor
   major-jumped (e.g. `*` 3 → 4), re-pins it to the latest prior major via
   `yarn set resolution`. Then `yarn install` (retried once on failure) and
   `yarn dedupe` (unless `--no-dedupe` skips the dedupe step). This matches
   rhdh-plugins `.fullsend/AGENTS.md`: install then dedupe so the lockfile is
   clean for CI `--immutable`.
4. If an **allowlisted leftover** (see `ancestor-allowlist.js`) still has a
   CVE-vulnerable resolved version after `yarn up -R` — a second lockfile line
   **or** a single parent-held unpatched pin — runs `bump-package-ancestors.js`
   for that package automatically (**even when step 3 `yarn install` failed** —
   parent bumps snapshot/revert the lockfile). A single **patched** line is
   done; do not walk parents. Pass `--no-ancestors` to skip. Other leftover
   packages are **not** a cue to walk parents — those ancestor bumps stay
   opt-in (see 5c).
5. **react-router pair sync:** if the bump set includes `react-router` or
   `react-router-dom` and the other is in the lockfile, both are bumped. After
   the steps above, if same-major highs still disagree, `react-router-dom` is
   aligned to `react-router` via lockfile-only `yarn set resolution` (avoids
   Qodo / review findings from version skew).
6. Classifies each package and compares before/after versions against open advisory ranges.
7. Prints a table: `package`, `classification`, `status`, `versions_before`, `versions_after`, `first_patched`, `open_cves`, `cves_fixed`.

`status` values: `fixed` (all vulnerable resolved versions cleared), `partial`, `unchanged`, `updated`, `skipped` (`@backstage/*` / `@backstage-community/*` denylist), `dry-run`, `error` (lockfile still vulnerable after the full bump pipeline — a non-zero `yarn up -R` exit alone does not set `error` when install/dedupe/ancestors already fixed the lockfile).

`--json` also includes `remaining` (after versions still in an open advisory range), compact `alerts` (`ghsa`, `cve`, `vulnerableRange`, `firstPatched`) per package, and hygiene fields `installError`, `installRetried`, `dedupeError`, `ancestorsDespiteInstallFailure`. Use that JSON for PR body tables — do not paste the bump script’s combined `status` table into the PR.

### 5b. PR body tables (`format-bump-pr.js`)

After a bump, pipe `--json` into `format-bump-pr.js` for the PR description. It prints **Fully fixed** (`package | before | after | CVEs cleared`), **Partial leftovers** (versions moved, still vulnerable), and **Unchanged** (`yarn up -R` did not move resolved versions). The Fully fixed advisory cell is one markdown link per finding: **CVE** when Dependabot has a CVE id, **GHSA** otherwise. Skipped `@backstage/*` / `@backstage-community/*` rows are omitted. Do not add a skipped-packages section or a Test plan.

```bash
node "$SKILL_DIR/scripts/bump-workspace-packages.js" --repo-root /path/to/plugins-repo <workspace> --json \
  | node "$SKILL_DIR/scripts/format-bump-pr.js"
node "$SKILL_DIR/scripts/bump-workspace-packages.js" --repo-root /path/to/plugins-repo \
  --alerts-json /path/to/dependabot-alerts.json <workspace> --json \
  | node "$SKILL_DIR/scripts/format-bump-pr.js"
node "$SKILL_DIR/scripts/format-bump-pr.js" --with-title bump.json
node "$SKILL_DIR/scripts/format-bump-pr.js" --title bump.json
```

| Flag | Default | Effect |
|------|---------|--------|
| `--title` | off | Print only `fix(<workspace>): bump yarn.lock packages for Dependabot CVEs` |
| `--with-title` | off | Print that title, then the PR body |

`partial` rows go in Partial leftovers. `unchanged` rows (including `status: error`
when the lockfile did not move) go in Unchanged. The `remaining` cell always
describes the CVE leftover — never raw `yarn up` stderr. Use `yarnError` on
bump `--json` or the bump script stderr summary for command failures.

- `needs <first_patched>` when before === after and every resolved version is still vulnerable
- `still N.x; patched line is <first_patched>` when leftover is one major and the only patched line is a different major (e.g. react-router 6.x vs 7.18.0)
- leftover resolved versions otherwise (e.g. `6.14.2`, `4.17.21`)

Show the formatted body to the user before `gh pr create` unless they already asked to open a PR.

### 5c. Ancestor-chain bumps

**Allowlisted leftovers** (see `scripts/ancestor-allowlist.js`) are
ancestor-bumped automatically by `bump-workspace-packages.js` when `yarn up -R`
leaves a leftover held by a parent: still-vulnerable extra resolved lines, or a
single unpatched pin. A single patched line is not a leftover. Success is
**CVE leftover gone** (Dependabot ranges), not a single remaining lockfile
line — more than one patched version is OK. `qs` leftovers are the
`qs@npm:~6.14.0` line held by `express` / `body-parser`; bumping `express` to a
release that depends on `qs ~6.15.1` drops `6.14.2`. Remaining `6.15.3` and
`6.16.0` is complete. `js-cookie` leftovers are a single `2.2.1` pin held by
`react-use`; a parent bump moves it to a patched 3.x.

**Do not run `bump-package-ancestors.js` for any other package unless the user
explicitly asks.** Leftover versions after `yarn up -R` are reported as
partial/unchanged; they are not a cue to walk parents.

When the user asks (or the allowlist runs), `bump-package-ancestors.js` walks
parents from `yarn why -R` and reverts lockfile collateral when parent bumps do
not clear the CVE leftover. Successful ancestor bumps also run
`yarn install` then `yarn dedupe`.

```bash
node "$SKILL_DIR/scripts/bump-package-ancestors.js" --repo-root /path/to/plugins-repo <workspace> <package>
node "$SKILL_DIR/scripts/bump-package-ancestors.js" --repo-root /path/to/plugins-repo <workspace> <package> --fast --json
```

| Flag | Default | Effect |
|------|---------|--------|
| `--max-parents <n>` | `8` | Max parents to try per depth tier |
| `--max-depth <n>` | `2` | Ancestor depth from target |
| `--fast` | off | `--max-depth 1`, `--max-parents 4`; fail fast on no progress |
| `--dry-run` | off | Plan only; no `yarn up` |

After bumping, re-run `check-dependabot-patch-status.js` to confirm patch level and whether dismiss is appropriate.

## Agent workflow

```
Task progress:
- [ ] Resolve workspace (`homepage` or `rhdh`) and `--repo-root`. RHDH core: `--repo redhat-developer/rhdh` ([references/rhdh-core.md](references/rhdh-core.md)).
- [ ] Ensure GITHUB_TOKEN / GH_TOKEN via .env or env — NOT gh, --token, or git credential
- [ ] If bumping interactively: `prepare-workspace-bump.js <workspace>`
      (fetch upstream/main, checkout -B chore/<workspace>-cve-bumps).
      On Fullsend: `prepare-workspace-bump.js --verify-only` (or omit reset;
      auto-selected when FULLSEND_OUTPUT_DIR is set). Use `--dry-run` to preview.
- [ ] Run list-dependabot-packages.js <workspace> [--json] → package list
      (REST, or `--alerts-json` when a runner snapshot is staged)
- [ ] Prefer check-dependabot-patch-status.js <workspace> (markdown table default;
      pass `--alerts-json` under Fullsend). OR classify-cve-source.js <workspace> pkg…
- [ ] Report classifications to the user as a markdown table (required)
- [ ] Call out RUNNER_ONLY / PLUGIN_DEV_ONLY / WORKSPACE_DEV_ONLY / PATCHED_EXCEPT_RUNNER / PROD_PATCHED_DEV_UNPATCHED vs PLUGIN_PROD remaining
- [ ] If packages need bumping: `bump-workspace-packages.js <workspace> [package…]` for
      bare `yarn up -R` + `yarn install` + `yarn dedupe` + CVE summary table.
      Under Fullsend, pass `--alerts-json` with the staged snapshot (no PAT in sandbox).
      Known no-major-bump packages (`http-proxy-middleware`) are re-pinned if
      they jump majors. Allowlisted leftovers (see `ancestor-allowlist.js`) are
      ancestor-bumped automatically when a CVE-vulnerable resolved version
      remains. `react-router` / `react-router-dom` are co-bumped and
      aligned to the same patch when either is in the bump set.
      Do **not** run `bump-package-ancestors.js` for other packages unless the
      user explicitly asks.
      Re-run `check-dependabot-patch-status.js` afterward if needed
- [ ] Complex bumps (e.g. `fast-xml-parser`): handle manually — do not use the script for
      dual-major, `yarn set resolution`, or targeted non-`-R` parent updates.
      Never bump `@backstage/*` or `@backstage-community/*`.
- [ ] If opening a PR: `bump-workspace-packages.js --json | format-bump-pr.js` for
      Fully fixed / Partial leftovers / Unchanged tables. Preview the body before
      `gh pr create`.
      Title: `fix(<workspace>): bump yarn.lock packages for Dependabot CVEs`
      (rhdh core: `fix(deps): bump yarn.lock packages for Dependabot CVEs`).
      No Test plan, no skipped-packages section.
- [ ] If user asks to dismiss (interactive Cursor only — never under Fullsend):
  dry-run close script, then --close without --yes (runner package.json only
  for PATCHED_EXCEPT_RUNNER; note SBOM bump for PLUGIN_DEV / WORKSPACE_DEV).
  Under Fullsend (`FULLSEND_OUTPUT_DIR` set): do not call
  `close-dependabot-alerts.js`; report dismiss candidates only.
```

### Decision

| Situation | Action |
|-----------|--------|
| Aggregate exactly `RUNNER` / verdict `RUNNER_ONLY` | Package-level dismiss OK (interactive) |
| Aggregate exactly `PLUGIN_DEV` / verdict `PLUGIN_DEV_ONLY` | Package-level dismiss OK; recommend bump for SBOM hygiene |
| Aggregate exactly `WORKSPACE_DEV` / verdict `WORKSPACE_DEV_ONLY` | Package-level dismiss OK; recommend bump for SBOM hygiene |
| Verdict `PATCHED_EXCEPT_RUNNER` / `safeToDismissRunnerAlerts` | Dismiss **only** runner `package.json` alerts |
| Verdict `PROD_PATCHED_DEV_UNPATCHED` | Prod paths patched; unpatched lockfile lines are dev/runner/tooling — prefer SBOM/dev bump or stale lockfile refresh; do not treat as open PLUGIN_PROD work unless `patched_prod=no` |
| Open `PLUGIN_PROD` alerts remain / unpatched lockfile | Bump with `bump-workspace-packages.js` (auto ancestor-bumps allowlisted leftovers); other ancestor bumps only if the user asks |
| Open `PLUGIN_PROD` alerts remain | Fix prod; do not dismiss plugin alerts |
| Aggregate exactly `CORE_DEV` / verdict `CORE_DEV_ONLY` | Package-level dismiss OK; recommend bump for SBOM hygiene |
| Verdict `CORE_PROD_ALERTS_REMAIN` | Fix shipped RHDH packages; do not dismiss |
| Mixed labels (not exact `RUNNER` / `PLUGIN_DEV` / `CORE_DEV` / `WORKSPACE_DEV`) | **Do not dismiss** at package level |
| `UNKNOWN` / `NEEDS_REVIEW` | Dig into `yarn why`; do not dismiss |

## Report back

Present assessment results primarily as a **markdown table**. Prefer the script table output from `check-dependabot-patch-status.js` (default) or `classify-cve-source.js` (multi-package / `--table`).

Minimum classification table columns:

| package | classification | verdict / impact | notes |
|---------|----------------|------------------|-------|

Full patch-status table columns (from script): `package`, `classification`, `verdict`, `patched_prod`, `patched_lockfile`, `prod_alerts`, `runner_alerts`, `safe_dismiss_pkg`, `safe_dismiss_runner`, `prod_resolved`, `resolved`, `first_patched`.

`patched_prod` / `prod_resolved` come from `resolve-versions-by-path.js`, which walks `yarn why -R` trees rooted at published plugins and splits versions on production dependency paths vs plugin `devDependencies`, runners, and workspace tooling. When `yarn why -R` truncates deep transitive chains, `prod_resolved` may be empty even though aggregate classification includes `PLUGIN_PROD` — use `yarn why` + classify plugin list in that case.

Also include:

| Field | Source |
|-------|--------|
| Workspace | input |
| Packages assessed | `list-dependabot-packages.js` (or user-supplied list) |
| Alert count / manifests | list script `--json` |
| Classification table | `check-dependabot-patch-status.js` (default) or `classify-cve-source.js --table` |
| Runner-only packages | `classification === "RUNNER"` |
| Plugin-dev-only packages | `classification === "PLUGIN_DEV"` — dismiss OK; note SBOM bump follow-up |
| Workspace-dev-only packages | `classification === "WORKSPACE_DEV"` — dismiss OK; note SBOM bump follow-up |
| Safe dismiss package-level | `safeToDismissPackageLevel` |
| Safe dismiss runner alerts | `safeToDismissRunnerAlerts` |
| Dismiss candidates | policy A/B/C above |
| Bump result | `bump-workspace-packages.js --json`: `versionsBefore`, `versionsAfter`, `status`, `remaining`, `cvesFixed`, `openCves` |
| PR body tables | `format-bump-pr.js` from bump `--json` (Fully fixed / Partial leftovers / Unchanged) |
