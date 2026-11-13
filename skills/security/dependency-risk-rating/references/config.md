# Configuration reference

Two configuration sources exist:

1. **Target repo config** — `.dependency-risk.yaml` (or `.yml`/`.json`) in the
   root of the repository being analyzed. Per-repo policy: trust list,
   thresholds, weights, codecov mapping.
2. **Skill data** — `scripts/data/support-levels.yaml`, shipped with the skill
   and maintained in the skill repo. Support levels for Backstage-ecosystem
   packages. Target repos never define support levels.

Missing files are fine: every key has a default (`CONFIG_DEFAULTS` in
`scripts/lib/yaml.ts`). Unknown keys are rejected with an error naming this
document. The YAML parser supports a subset (no anchors, no multiline block
scalars) — use the JSON twin for anything exotic.

## `.dependency-risk.yaml` — full schema

```yaml
version: 1                          # schema version, currently always 1

trustedPackages:                    # updates always OK -> capped at LOW
  - "@red-hat-developer-hub/*"      # exact names or trailing-* globs

trustedOverridesSecurity: true      # security signals (introduced CVE, new
                                    # install script) still surface for trusted
                                    # packages; set false for a hard allowlist

minAgeDays: 3                       # versions younger than this are risky

manyPackagesThreshold: 100          # escalate overall band when more packages
                                    # changed AND <80% fully analyzed

maxPackagesDetailed: 20             # packages that get the full API fan-out;
                                    # next up to 150 get age + delta + OSV.
                                    # OSV is always checked for every package,
                                    # whatever this is set to.

bands:                              # internal 0-10 score -> band thresholds
  medium: 3
  high: 6

weights:                            # partial overrides; all keys and defaults
  installScriptAdded: 4             # in references/scoring.md
  scorecardLow: 1                   # example: enable OpenSSF Scorecard penalty

backstage:
  enabled: true                     # false = score.ts ignores the @backstage/*
                                    # manifest check even when it was run

codecov:                            # optional coverage lookup
  service: github                   # codecov "service" segment
  owner: redhat-developer
  tokenEnv: CODECOV_TOKEN           # env var holding the API token
  repos:
    ".": rhdh                       # workspace dir -> codecov repo slug

testConfidence:                     # manual per-workspace setting: high |
  ".": medium                       # medium | low. Always wins over the
  "plugins/foo": high               # automatic codecov number.
```

`--config` on the scripts accepts a repo root directory, a config file path,
or the literal `none` (pure defaults — use in PR mode when the target repo has
no config, so the local checkout's config cannot leak in).

## `scripts/data/support-levels.yaml` — skill data

```yaml
version: 1
source: file                        # v1: this file. Reserved: "remote" +
#remoteUrl: https://...             # remoteUrl, with this file as fallback.

ecosystemScopes:                    # only these scopes have a support-level
  - "@backstage/*"                  # concept; others never get the "unknown"
  - "@backstage-community/*"        # penalty
  - "@red-hat-developer-hub/*"
  - "@janus-idp/*"

levels:                             # pattern -> production | tech-preview |
  "@red-hat-developer-hub/*": production   # dev-preview. Exact beats glob,
  "@backstage/*": production               # longer glob beats shorter.

scoreAdjust:                        # points added by score.ts per level
  production: 0
  tech-preview: 1
  dev-preview: 2
  unknown: 1
```

## Network requirements

Scripts call these hosts (all HTTPS, best-effort — failures become "data
gaps", never crashes): `registry.npmjs.org`, `api.npmjs.org`, `api.osv.dev`,
`api.securityscorecards.dev`, `versions.backstage.io`, `api.codecov.io`, and
`api.github.com`.

File reads — lockfiles, `package.json`, `backstage.json`, and the Backstage
release manifest mirror — all go through `api.github.com`, never
`raw.githubusercontent.com`. A sandboxed runner that allowlists egress by
hostname usually permits `api.github.com` already, so the only host that must
be added for a sound rating is `api.osv.dev`: without it the report loses the
one signal that can force HIGH. Losing `api.npmjs.org` costs download counts,
and losing `versions.backstage.io` is free, because the manifest falls back to
the mirror. A private-repo raw fetch authenticates with the credential
the `gh` CLI already holds; the scripts retrieve it transiently and never print
it. If Node's fetch must go through an explicit proxy, run scripts with
`NODE_USE_ENV_PROXY=1` (and `NODE_EXTRA_CA_CERTS` for a custom CA).
