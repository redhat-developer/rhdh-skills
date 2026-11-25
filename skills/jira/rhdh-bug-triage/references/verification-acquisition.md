# Runnable verification acquisition

`verify` acquires source/release/artifact evidence through read-only adapters.
It does **not** diagnose by matching strings, execute product code/tests or assign
a fix verdict. The agent still compares actual changes and final code against
each acceptance requirement, using `/rhdh-plugin-bug-fix`'s explicit
`inspection-only` branch for plugin diagnosis when available.

The native forge adapter owns authenticated GitHub GET/diff reads. Anonymous
public HTTPS reads are restricted to product release/docs/registry hosts; they
never retrieve saved login credentials, repair authentication or follow arbitrary redirects.
401/403, unreadable files, missing tags and digest mismatches remain failures.
Registry-issued signed blob redirects to the approved Quay CDN are followed only
inside the adapter; transient capability URLs/queries are never stored in plans
or receipts. Downloaded bytes must still verify against the requested digest.

## Plan: explicit requirements and exact targets

```json
{
  "release": {
    "version": "2.1.0",
    "url": "https://access.redhat.com/errata/RHSA-2026:96391"
  },
  "issues": [{
    "key": "RHDHBUGS-664",
    "requirements": [
      "Default Operator behavior handles the original busy-cluster scenario",
      "Separate opt-in filtering from the default configuration"
    ],
    "repositories": [{
      "repository": "redhat-developer/rhdh-operator",
      "ref": "tags/2.1.0",
      "paths": ["cmd/main.go", "bundle/rhdh/manifests/backstage-operator.clusterserviceversion.yaml"],
      "pullRequests": [2070]
    }]
  }]
}
```

Values above illustrate an existing historical release; they are not a current
release default. Resolve the actual reviewed release/repositories first. Include
all material supported paths, callers, dependencies/configuration and existing
tests; absence from the plan is not proof that a path is irrelevant.

`ref` accepts `tags/<tag>`, `heads/<branch>` or an exact commit SHA. Annotated tags
are peeled to commits. Branch/tag names are resolved once per requested target;
returned source citations use immutable SHAs. A repository tag itself does not
establish a product release or build mapping.

The collector reads final file contents and checks their Git blob identity,
reads actual PR state/diffs, and compares each real merge commit to the resolved
target. `contained`, `absent`, `unknown`, and `not_a_merged_fix` remain distinct.
A source-contained change is not automatically artifact-contained or correct.

## Optional: tying a released image back to its source

Each issue may add `artifacts` entries with:

- `registry`: `registry.redhat.io`, `registry.access.redhat.com`, or `quay.io`.
- `repository`: the image repository path.
- `digest`: exact `sha256:...`, never a mutable tag.
- `releaseReference`: literal registry/repository@digest from the authoritative
  release record, identifying the same repository/digest. A public mirror may
  serve the bytes only when every requested digest verifies.
- `architecture`: optional, default `amd64` on Linux.

Only index/manifest/config metadata is read—no image layers or product execution.
Every edge is digest-checked. The image must have exactly one matching platform.
Source labels are compared to both repository identity and resolved revision.
`declared_source_matches` means the released metadata declares that inspected
source. It is **not** independent build attestation or proof of acceptance coverage.
If labels omit the source repository, bounded lookups of the declared revision
in the explicitly requested candidate repositories are recorded, not treated as
proof of the build's product-source mapping.
Different/downstream VCS labels, unreadable configs and missing release references
leave `sourceBinding: not_established`; do not silently equate different commits.

## Inspect and render

```bash
python3 scripts/triage.py verify --plan verification-plan.json --out fresh-verification
# Inspect the source, diffs, requirements and gaps; write investigated assessments.
# Add --verification fresh-verification to the ordinary run command.
```

Use a fresh directory. The index retains read targets, times, successes/failures,
content hashes, the original plan and per-issue packet hashes. Source response
receipts are serialized JSON; OCI hashes cover the exact downloaded bytes.
`run` checks saved receipt/packet/plan integrity and exact release identity before
attaching them. Integrity proves bytes have not changed since collection, not
that a source is true or complete. Newly acquired negative fix-incorporation
evidence cannot be overridden by copied assessment booleans.

Read the release record: merely observing the version string is not an automated
shipping determination. Requirement coverage is initially
`requires_agent_inspection`, not “passed”. Obtain independent reviews when the
triage policy requires them. Do not use incomplete acquisition as proof that a
bug persists, is fixed, or needs a reminder comment.
