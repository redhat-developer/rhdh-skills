---
name: osl-bump-automation
description: Automate and verify OpenShift Serverless Logic (OSL) version bumps across the RHDH chart and operator repositories. Use when an OSL release requires synchronized startingCSV, kn-workflow URL, generated-manifest, documentation, schema, and chart-version updates.
---

# OSL bump automation

Use this skill for the recurring change represented by the RHDH chart/operator OSL
bump pull requests and RHIDP-17562. The authoritative input is the new OSL
`MAJOR.MINOR.PATCH` version. Do not guess the version from a PR number or from
an existing checkout.

## Constraints

- Run the helper from this skill's `scripts/` directory (or invoke it by its
  path). It uses only Python's standard library.
- Treat `rhdh-chart` and `rhdh-operator` as two separate Git repositories. Do
  not combine their histories or commit changes across both repositories.
- Never edit files outside the explicitly listed OSL paths in
  `scripts/osl_bump.py`.
- `plan` is read-only. `apply` requires the explicit `--write` flag.
- Generated files are part of the change: do not update only the source YAML
  and leave `README.md`, `values.schema.json`, `dist/`, or `bundle/` stale.

## Procedure

1. Confirm clean working trees and identify the target branches in both
   checkouts. Save or shelve unrelated changes before applying anything.
2. Obtain the exact OSL version from the release/change request, then run a
   read-only plan:

   ```bash
   ./scripts/osl_bump plan --version 1.38.1 \
     --chart-repo /path/to/rhdh-chart \
     --operator-repo /path/to/rhdh-operator
   ```

3. Review the planned files. In the chart repository the bump must synchronize
   `charts/orchestrator-infra/values.yaml`, both schema files, both README
   representations, and the chart patch version in `Chart.yaml`. In the
   operator repository it must synchronize the profile source plus the checked
   in generated `bundle/rhdh/...` and `dist/rhdh/...` manifests and the
   plugin-dependency source.
4. Apply only after reviewing the plan:

   ```bash
   ./scripts/osl_bump apply --version 1.38.1 \
     --chart-repo /path/to/rhdh-chart \
     --operator-repo /path/to/rhdh-operator --write
   ```

   The chart patch version is incremented automatically. Supply
   `--chart-version X.Y.Z` only when the repository's release process requires
   a different chart version.
5. Inspect the diff in each repository. The only expected semantic changes are
   the OSL version, the chart patch version, and their generated renderings.
6. Verify exact synchronization:

   ```bash
   ./scripts/osl_bump verify --version 1.38.1 \
     --chart-repo /path/to/rhdh-chart \
     --operator-repo /path/to/rhdh-operator
   ```

7. Run repository-native checks. For the chart, run the repository's Helm
   lint/chart-testing and README/schema generation checks. For the operator,
   run formatting/lint/unit checks plus the manifest-generation or bundle
   diff checks documented by its Makefile/CI. If an OpenShift cluster and
   registry access are available, install the infra chart and approve the OLM
   InstallPlan, then confirm the installed Logic Operator CSV equals
   `logic-operator.v<version>`; otherwise clearly report that cluster validation
   was not run.
8. Commit and push one focused commit per repository, using the repository's
   normal signed-off/PR conventions. Include the plan, verification result,
   native checks, and any unavailable cluster/artifact checks in the PR body.

## Testing expectations

A bump is not complete when only one occurrence changes. Verify all selected
files, search the diffs for the previous OSL version, and confirm the source and
checked-in generated manifests agree. Use `plan` before every future bump and
`verify` after every apply. The helper fails closed if an expected file or
version pattern is absent, which protects against upstream layout changes.
