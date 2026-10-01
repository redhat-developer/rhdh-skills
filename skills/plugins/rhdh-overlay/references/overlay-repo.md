# Reference: Overlay Repository Patterns

Patterns and examples for working with [rhdh-plugin-export-overlays](https://github.com/redhat-developer/rhdh-plugin-export-overlays).

<overview>
The overlay repo defines which upstream plugins to export as dynamic plugins for RHDH.
Each plugin lives in a workspace folder under `workspaces/`.
CI handles the actual export — we define the configuration.
</overview>

<workspace_structure>

```
workspaces/<name>/
├── source.json           # Required: upstream source definition
├── plugins-list.yaml     # Required: which plugins to export
├── backstage.json        # Optional: version override for RHDH compatibility
├── patches/              # Optional: source modifications
│   └── fix-something.patch
└── metadata/             # Required for catalog: package metadata
    ├── frontend.yaml
    └── backend.yaml
```

</workspace_structure>

<reference_examples>
When in doubt, find a similar workspace and copy its structure.

| If your plugin... | Look at | Key patterns to copy |
|-------------------|---------|----------------------|
| Is from `awslabs/backstage-plugins-for-aws` | `aws-ecs/`, `aws-codebuild/` | `patches/`, `backstage.json` override, `--embed-package` |
| Is from `backstage/community-plugins` | `backstage/` | Multiple plugins, patches |
| Needs Backstage version override | `aws-codebuild/` | `backstage.json` + matching `source.json` |
| Has unpublished shared dependencies | `aws-ecs/` | `--embed-package` in `plugins-list.yaml` |
| Is a Red Hat plugin | `intelligent-assistant/` | Standard structure |
| Needs metadata files | `aws-codebuild/metadata/`, `todo/metadata/` | YAML structure, `appConfigExamples` patterns |

**View similar PRs:**

```bash
gh pr view <number> --repo redhat-developer/rhdh-plugin-export-overlays
```

See PR #1426 (AWS ECS) for a comprehensive PR description template.
</reference_examples>

<known_gotchas>
Patterns not caught by CI that require specific handling:

| Scenario | Solution |
|----------|----------|
| AWS plugins (`awslabs/backstage-plugins-for-aws`) | Copy `patches/` from `aws-ecs/` — fixes workspace glob issue |
| Monorepo with unpublished shared deps | Use `--embed-package` in plugins-list.yaml |
| Version mismatch | Add `backstage.json` override, keep `source.json` as upstream's actual version |
</known_gotchas>

<related_tooling>

| Resource | Description |
|----------|-------------|
| [rhdh-dynamic-plugin-factory](https://github.com/redhat-developer/rhdh-dynamic-plugin-factory) | Container for local plugin building |
| [rhdh-plugin-export-utils/export-dynamic](https://github.com/redhat-developer/rhdh-plugin-export-utils) | GitHub Action for exporting plugins |
| [rhdh-local](https://github.com/redhat-developer/rhdh-local) | Local testing environment |
</related_tooling>
