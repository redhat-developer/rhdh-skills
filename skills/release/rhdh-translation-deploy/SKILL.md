---
name: rhdh-translation-deploy
description: >-
  Downloads completed translations from TMS (Memsource), merges them into
  locale TypeScript files for rhdh-plugins and community-plugins (update
  matching keys only), merges backstage/community-plugins/rhdh JSON into
  rhdh/translations/, and prepares branches for PR creation with signed-off
  commits and changesets. Does not open a PR in the upstream backstage repo.
  Use for "deploy RHDH translations", "download translations from TMS", or
  "create translation PRs".
compatibility: "Node 22+, translations-cli built in rhdh-plugins/workspaces/translations, memsource CLI, gh CLI for PRs, prettier in target repos, sibling clones of rhdh-plugins, rhdh, community-plugins, and backstage."
---

# RHDH Translation Deploy

Download translated files from TMS, merge into the right targets, and prepare
PRs.

## What goes where

| Source repo in TMS | Deploy target |
|--------------------|---------------|
| rhdh-plugins | In-place `.ts` merge in rhdh-plugins + changesets + PR |
| community-plugins | In-place `.ts` merge in community-plugins + changesets + PR; also JSON merge into `rhdh/translations/` |
| backstage | JSON merge into `rhdh/translations/backstage-{locale}.json` only — **no upstream backstage PR** |
| rhdh | JSON merge into `rhdh/translations/rhdh-{locale}.json` |

## Merge rules for `.ts` files

Do **not** use `translations-cli i18n deploy` — it rewrites files and removes
unchanged keys.

1. Load downloaded JSON for a plugin + locale.
2. Open the existing locale file (e.g. `de.ts`).
3. For each downloaded key: if it exists in the file → update the value; if
   not → skip.
4. Never remove keys. Never change imports/exports.
5. Strings containing an apostrophe use double quotes (`"..."`).
6. Run Prettier on changed files before commit.

No delta comparison and no `ref.ts` gate during merge. Keys developers add
after upload stay untouched.

## Subcommands

| Command | Description |
|---------|-------------|
| `preflight` | Check repos, tools, TMS credentials |
| `download` | Download completed jobs via translations-cli |
| `validate` | Basic JSON / structure checks on downloads |
| `update-translated-sot --sprint S` | Fix TMS `en` → real locale, merge into `rhdh/translations/`, PR on rhdh |
| `deploy` | In-place `.ts` merge for rhdh-plugins and community-plugins |
| `pr --sprint S` | Write changesets with real package names; report repos ready for `/mutation-gate` |

## Route

Load `workflows/download-and-deploy.md`.

## Boundary

- Extracting strings and uploading to TMS is `/rhdh-translation-upload`.
- Repository locations and branch context are `/rhdh-context`.
- External writes (creating PRs, pushing branches) go through `/mutation-gate`.

## Completion

Report per-repo: files changed, keys updated/skipped, changesets, and PR URLs
when created. Note that backstage has no upstream PR.
