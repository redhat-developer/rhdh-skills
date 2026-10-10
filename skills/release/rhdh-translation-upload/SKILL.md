---
name: rhdh-translation-upload
description: >-
  Extracts translation strings from rhdh-plugins, rhdh, community-plugins, and
  backstage, compares against the source of truth to find new keys and changed
  English values, applies RHDH-priority overrides for backstage, and uploads
  delta reference JSON files to TMS (Memsource). English SOT lives in
  rhdh-plugins/workspaces/translations/sot/. Use for "extract translation
  strings", "generate translation delta", "upload translations to TMS", or
  "prepare translations for upload".
compatibility: "Python 3.9+, Node 22+, yarn, translations-cli built in rhdh-plugins/workspaces/translations, memsource CLI for upload, gh CLI for PR creation, all four repos cloned as siblings."
---

# RHDH Translation Upload

Extract translation strings from the four RHDH repos and upload delta files
to TMS. The delta includes only new keys and keys whose English value changed
since the previous release, ensuring translators only see what needs work.

## Subcommands

| Command | Description |
|---------|-------------|
| `preflight` | Check repos, tools, TMS credentials |
| `extract --sprint S` | Generate reference JSONs from all repos (auto-checkouts backstage to the version in `rhdh/backstage.json`) |
| `delta --sprint S` | Compare against SOT, apply RHDH overrides for backstage, filter to Red Hat-owned plugins, produce delta + full files |
| `upload --sprint S` | Upload delta files to TMS (requires `source ~/.memsourcerc`) |
| `upload --sprint S --dry-run` | Preview what would be uploaded |
| `update-sot --sprint S` | Copy full references to `rhdh-plugins/workspaces/translations/sot/{repo}-en.json`, create branch + PR in rhdh-plugins |

## Route

Load `workflows/extract-and-upload.md`. It walks through preflight, extraction,
delta computation, upload, and EN SOT update in sequence.

## Boundary

- Downloading translated files from TMS and deploying them back to repos is
  `/rhdh-translation-deploy`.
- Repository locations and branch context are `/rhdh-context`.
- External writes (creating PRs, pushing branches) go through `/mutation-gate`.

## Completion

Report:
1. Per-repo delta summary (new/changed/removed/unchanged key counts)
2. Upload status per repo (filename, key count, project ID)
3. EN SOT PR link (if created)
4. Next step: wait for translators, then run `/rhdh-translation-deploy`
