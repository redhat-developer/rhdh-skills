# rhdh-patch-backstage workflow (Mermaid)

Companion diagram for [`SKILL.md`](../SKILL.md). Render in GitHub, GitLab, VS Code (Mermaid preview), or docs tooling.

## Overview

One flow: **backstage/backstage** at the **`backstage.json`** release tag is built **twice** (before and after the fix). **Only** dist files that differ between those builds are copied into the Yarn patch temp. **RHDH** pins that minimal set onto the lockfile version.

```mermaid
flowchart TB
  subgraph repos["Repos"]
    direction LR
    U(["backstage/backstage<br/><i>checkout v from backstage.json; baseline build; cherry-pick; patched build; diff dist</i>"])
    R(["redhat-developer/rhdh<br/>release-V<br/><i>yarn patch; copy only changed dist files; patch-commit</i>"])
  end

  subgraph work["Workflow"]
    direction TB
    P[Pre-flight: clean trees, map git remotes] --> S1[Sync RHDH → release-V; read backstage.json]
    S1 --> S2[Fetch tags; checkout vVERSION]
    S2 --> B0[yarn build → DIST_BASELINE]
    B0 --> S3{Apply fix}
    S3 -->|Upstream SHAs| CP[cherry-pick onto tag]
    S3 -->|manual edits| ME[edit src/]
    CP --> B1[yarn build → DIST_PATCHED]
    ME --> B1
    B1 --> D[diff baseline vs patched; exclude *.map]
    D --> RHDH[yarn patch → copy only changed files → patch-commit]
    RHDH --> I[yarn install]
    I --> V[Verify minimal .patch + yarn why via patch:]
  end
```

Step-by-step detail, troubleshooting, and **dynamic-plugins** (second Yarn project) are in [`SKILL.md`](../SKILL.md).
