# OCI Image Structure

> **Note:** `npx @red-hat-developer-hub/cli plugin package --tag <image>` handles OCI image creation automatically — including directory layout, annotation, and correct structure. This reference is for **troubleshooting** or understanding what the CLI does under the hood.

## How `plugin package` Works

The `plugin package` command from `@red-hat-developer-hub/cli`:
1. Takes the `dist-dynamic/` output from `plugin export`
2. Creates an OCI image with the plugin files as an extracted directory (not a tarball)
3. Adds the `io.backstage.dynamic-packages` annotation (base64-encoded JSON) automatically
4. Tags the image with the specified `--tag`
5. Prints the `dynamic-plugins.yaml` entry to use on the cluster

```bash
npx @red-hat-developer-hub/cli@latest plugin package \
  --tag ghcr.io/<user>/<repo>/<plugin-name>:v0.1.0
```

Docs: https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.9/html/installing_and_viewing_plugins_in_red_hat_developer_hub/assembly-third-party-plugins

## Expected Directory Layout

RHDH's dynamic plugin installer expects the OCI image to contain the
**extracted** plugin contents as a named directory — NOT a tarball.

```
/
└── <plugin-short-name>/
    ├── package.json
    ├── dist/
    │   └── *.js, *.js.map
    ├── dist-scalprum/
    │   └── *.js (module federation chunks)
    └── alpha.d.ts (optional)
```

## Common Failures

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `ENOENT: no such file or directory, open '.../package.json'` | Image contains a `.tgz` archive instead of extracted directory | Use `plugin package` instead of manual `podman build` |
| `InstallException: No plugins found in OCI image` | Missing `io.backstage.dynamic-packages` annotation | Use `plugin package` (adds annotation automatically) or rebuild manually with `--annotation` |
| Plugin loads but features not discovered | Missing `backstage.features` in `dist-dynamic/package.json` | Run `npx @red-hat-developer-hub/cli plugin export` again (it generates the features field) |
| Push fails with `permission_denied` | Token missing `write:packages` scope | `gh auth refresh -h github.com -s write:packages` then re-login to GHCR |
| Image pulled but package not found | Wrong directory name in image vs annotation key | Use `plugin package` which ensures consistency |
| `plugin package` fails with "container tool not found" | `podman` not on PATH or not running | `podman machine start` (macOS) or add `--container-tool docker` |

## Annotation Format

The `io.backstage.dynamic-packages` annotation value is base64-encoded JSON (generated automatically by `plugin package`):

```json
[
  {
    "<plugin-short-name>": {
      "name": "@scope/package-name-dynamic",
      "version": "1.2.3",
      "backstage": {
        "supported-versions": "1.52.0",
        "features": {
          "frontend": {
            "default": { "type": "FrontendModule" },
            "./alpha": { "type": "FrontendPlugin" }
          }
        }
      },
      "repository": { ... },
      "license": "Apache-2.0"
    }
  }
]
```

The JSON key (`<plugin-short-name>`) MUST match the directory name inside the image.
The `backstage.features` field is populated by `npx @red-hat-developer-hub/cli plugin export`.

## Manual Build (Fallback)

Only use this if `plugin package` is unavailable or broken:

```dockerfile
FROM scratch
COPY --chmod=755 . /<plugin-short-name>/
```

`.dockerignore`:
```
Containerfile
.dockerignore
```

```bash
podman build --no-cache --platform linux/amd64 \
  --annotation "io.backstage.dynamic-packages=<base64-encoded-json>" \
  -t <image-tag> -f Containerfile .
```

## Verifying a Working Image

```bash
# Check annotation exists
podman inspect <image> | jq '.[0].Annotations["io.backstage.dynamic-packages"]'

# Decode and pretty-print annotation
podman inspect <image> | jq -r '.[0].Annotations["io.backstage.dynamic-packages"]' | base64 -d | jq .

# Mount and check directory structure
ID=$(podman create <image>)
podman cp $ID:/<plugin-short-name>/package.json /dev/stdout | head -5
podman rm $ID
```
