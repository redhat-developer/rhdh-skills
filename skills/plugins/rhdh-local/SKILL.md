---
name: rhdh-local
description: >-
  Operates a local Red Hat Developer Hub environment with the
  rhdh-local-setup customization system: enable or disable dynamic plugins,
  apply configuration, switch pristine and customized modes, start or stop
  containers, inspect health and logs, run plugin verification, and back up or
  restore customizations. Use for local RHDH, podman compose plugin testing,
  PR artifact verification, 504 or startup troubleshooting, and local
  Extensions Catalog checks.
compatibility: "Python 3 and podman or docker; rhdh-local-setup checkout for runtime operations."
---

# RHDH Local

Own local execution and return evidence to the calling workflow. All commands
use this skill's standalone CLI; another skill does not need to be installed.

## Capability gate

1. Run `uv run scripts/rhdh-local --help`.
2. Locate `rhdh-local-setup` through `RHDH_LOCAL_SETUP_DIR` or by walking from
   the current directory. Run `uv run scripts/rhdh-local --json status`.
3. If the setup is absent, state the required environment variable or checkout
   layout and stop only the runtime branch.
4. Never read secrets from `.env` into conversation context. Ask only for
   missing variable names and let the container runtime consume their values.

## Route by outcome

| Outcome | Load and follow |
|---|---|
| Read a plugin version or artifact at an overlay branch or tag | Run `python3 scripts/fetch-plugin-metadata.py <plugin-name> --branch <branch-or-tag> --json`; default ref is `main` and runtime setup is not required |
| Enable a catalog or PR artifact | `workflows/enable-plugin.md` |
| Disable a plugin | `workflows/disable-plugin.md` |
| Switch pristine/customized mode | `workflows/switch-mode.md` |
| Verify a plugin end to end | `workflows/test-plugin.md` and `references/dynamic-plugin-testing.md` |
| Inspect status or enabled packages | Run `uv run scripts/rhdh-local --json status` or `uv run scripts/rhdh-local --json plugins list` |
| Apply customizations | Run `uv run scripts/rhdh-local --json apply` |
| Start or stop | Run `uv run scripts/rhdh-local --json up [flags]` or `uv run scripts/rhdh-local --json down` |
| Check health | Run `uv run scripts/rhdh-local --json health` |
| Back up or restore | Run `uv run scripts/rhdh-local --json backup` or `uv run scripts/rhdh-local restore <archive>`; restore is a dry run until `--force` |
| Troubleshoot startup, networking, or 504s | `references/troubleshooting.md` |
| Configure environment variables | `references/env-reference.md` |

## Invariants

- Edit only source files under `rhdh-customizations/`. Run `apply` after every
  edit so copies under `rhdh-local/` stay synchronized.
- Use this CLI's `up` and `down` commands when Lightspeed or Orchestrator is
  enabled; they own the compose lifecycle and shared networks.
- Obtain package references from `spec.dynamicArtifact` or from the reference the
  caller supplied. Never construct OCI references from naming conventions.
- Preserve the `includes:` block in dynamic plugin overrides. Put backend
  packages before their frontend packages.
- A plugin test succeeds only with recorded installation, boot, health, and UI
  results relevant to the request. Distinguish an expected credential error
  from a load failure.

## What a caller supplies

A caller invokes this skill by name and states, in conversation:

- each package reference to enable, with its plugin config or `none`
- the environment variables the plugin needs, by name only
- the catalog test entities the plugin renders against
- which checks to run: installation, startup, health, UI
- whether to clean up afterwards

Use those references verbatim. Ask for a missing one rather than reconstructing
it from a naming convention.

## What this skill reports

Report to the caller in conversation. Do not write into another skill's
directory.

- the subject tested, and the mode it ran in: customized or pristine
- one line per requested check — installation, startup, health, UI — each passed,
  failed, or skipped with the reason it was skipped
- the packages actually enabled, with their exact references
- the log excerpts that back each result
- cleanup state: completed, retained, or not requested

## Completion

Complete when the report names every source customization file changed, every
CLI command run, the health and UI evidence observed, the cleanup state, and one
outcome for every check the caller requested.
