# Scoring rubric

The score is computed by `scripts/score.ts` — never by hand. This document
explains the model so you can interpret results and explain them to the user.

## Model

Each package gets an additive score, clamped to 0–10 internally and displayed
×10 as 0–100. Score bands (configurable via `bands:` in `.dependency-risk.yaml`):

| Internal score | Band |
|---|---|
| 0–2 | LOW |
| 3–5 | MEDIUM |
| ≥ 6 | HIGH |

The **overall rating** is the highest package band, escalated one band when
more than `manyPackagesThreshold` (default 100) packages changed AND fewer than
80% could be fully analyzed.

## Default weights

Every key can be overridden in the target repo's `.dependency-risk.yaml` under
`weights:`. Source of truth: `DEFAULT_WEIGHTS` in `scripts/score.ts`.

| Signal | Weight key | Points |
|---|---|---|
| Minor version bump (or patch bump on 0.x) | `deltaMinor` | +1 |
| Major version bump (or minor bump on 0.x) | `deltaMajor` | +3 |
| Major bump whose only breaking change is dropping EOL Node.js | `majorNodeDropOnly` | +1 (replaces `deltaMajor`) |
| Version downgrade | `downgrade` | +3 |
| Prerelease target version (beta/rc/next) | `prereleaseTarget` | +2 |
| Published < `minAgeDays` (default 3) ago | `ageBelowMin` | +3 |
| Published 3–14 days ago | `ageUnder14Days` | +1 |
| < 1k weekly downloads | `downloadsUnder1k` | +2 |
| 1k–100k weekly downloads | `downloadsUnder100k` | +1 |
| Known vulnerability **introduced** by the update, severity HIGH or CRITICAL | `osvIntroduced` | +5 and band forced to HIGH |
| Known vulnerability **introduced**, severity LOW or MODERATE | — | 0 — dropped, see "Vulnerability severity" below |
| Known vulnerability **fixed** by the update (any severity) | `osvFixed` | −2 |
| Target version is deprecated | `deprecated` | +3 |
| Update **adds** an install script (pre/post/install) | `installScriptAdded` | +4 |
| Different npm publisher than the previous version | `publisherChanged` | +2 |
| License changed | `licenseChanged` | +2 |
| npm provenance attestation present | `provenance` | −1 |
| Matches the pinned Backstage release manifest | `backstageMatch` | −2 |
| Does NOT match the Backstage release manifest | `backstageMismatch` | +3 |
| Changelog judged bugfixes-only | `changelogBugfixOnly` | −1 |
| Changelog judged significant | `changelogSignificant` | +2 |
| OpenSSF Scorecard < 4 | `scorecardLow` | 0 (informational; set > 0 to enable) |
| Support level (from the skill's `scripts/data/support-levels.yaml`) | — | production 0 / tech-preview +1 / dev-preview +2 / unknown +1 (ecosystem packages only) |

Notes on 0.x versions: for `0.x` packages a minor bump is treated as major and
a patch bump as minor (`effectiveType` in the delta), because semver makes no
compatibility promise below 1.0 and the Backstage ecosystem bumps minor for
breaking changes.

## Vulnerability severity

Only an **introduced** vulnerability of GHSA severity `HIGH` or `CRITICAL`
(Red Hat "Important" and above) raises the score and forces the band to HIGH.
`LOW` and `MODERATE` introductions are dropped: on a large lockfile refresh
they are the dominant source of CVE churn, and letting one of them force HIGH
would block merges over advisories nobody would act on.

Two deliberate rules around that:

- **Unresolved severity fails closed.** If the severity lookup fails, the
  vulnerability is treated as significant and still forces HIGH, labelled
  `(severity unknown)`. A lookup error must never silently downgrade a real
  regression.
- **Dropped introductions leave no trace in the report.** They remain in
  `metrics.json` under `osv.introduced` with their severity in
  `osv.severities`, so re-scoring under a different policy never needs a
  refetch — but they produce no row in the table.

**`osvFixed` is deliberately not severity-gated.** The asymmetry is
intentional: `osvIntroduced` is +5 and forces a band, so a trivial advisory
there changes the verdict; `osvFixed` is −2, forces nothing, and is usually
absorbed by the 0 floor on the low-signal transitive packages where it would
apply. Measured on a real 93-package PR, gating it changed 0 bands and 1
package's score, at 41× the API lookups (164 fixed ids vs 4 introduced).

## Analysis tiers and what each one checks

`maxPackagesDetailed` (default 20) and the fixed `PACKUMENT_HARD_CAP` of 150
rank packages direct-first, then by severity of the version delta, then by
name:

| Rank | Tier | Checks |
|---|---|---|
| 0–19 | `detailed` | packument, weekly downloads, OSV, OpenSSF Scorecard (direct only) |
| 20–149 | `light` | packument, OSV |
| 150+ | `none` | version delta only |

OSV deliberately spans both analyzed tiers rather than being capped at
`maxPackagesDetailed`. The cap exists to bound *per-package* HTTP fan-out —
packument, downloads and Scorecard are one request each — whereas OSV batches
500 queries per request, so widening its scope costs no extra round trips.
Rationing the one signal that can force a band would make catching a
supply-chain regression depend on where a package happened to sort.

Known limitation: packages ranked 150+ still receive no OSV check.

## Trusted packages

Packages matching `trustedPackages` (default `@red-hat-developer-hub/*`) are
capped at LOW ("a change is always okay"). Exception: when
`trustedOverridesSecurity: true` (default), a security signal still surfaces —
an introduced HIGH/CRITICAL vulnerability forces HIGH, and a newly added
install script keeps its real score. A compromised trusted scope must never be
hidden by the allowlist.

## Confidence vs. score

- **Assessment confidence** (high/medium/low) reflects data completeness:
  API failures and light-analysis packages lower it. It never changes the score.
- **Test confidence** (from codecov coverage or `testConfidence` config)
  shapes only the recommendation text: high coverage → "a green CI run is a
  strong signal"; low coverage → "verify manually".

## Worked example

`tiny-evil-lib 1.4.2 → 2.0.0`, published 5 hours ago, 412 weekly downloads,
adds a postinstall script, new publisher, changelog judged significant:

    major (+3) + age<3d (+3) + downloads<1k (+2) + install script (+4)
    + publisher change (+2) + changelog significant (+2) = 16 → clamped 10
    → HIGH (100/100)

`lodash 4.17.20 → 4.17.21`, 4+ years old, 45M downloads/week, fixes a CVE,
changelog bugfixes-only:

    patch (0) + fixes CVE (−2) + bugfix-only (−1) = −3 → clamped 0 → LOW (0/100)

Severity gating, from a real PR. Two transitive packages, each fixing several
advisories while introducing one:

`shell-quote 1.8.2 → 1.10.0` introduces GHSA-pqg4-j6r4-53mv (**CRITICAL**),
fixes two:

    minor (+1) + INTRODUCES critical (+5) + fixes 2 CVEs (−2) = 4
    → forced HIGH, score floored at bands.high → HIGH (60/100)

`fast-uri 3.0.6 → 3.1.7` introduces GHSA-wjr9-j795-jxcr (**MODERATE**),
fixes eight, and changed npm publisher:

    minor (+1) + fixes 8 CVEs (−2) + publisher change (+2) = 1 → LOW (10/100)

The MODERATE introduction contributes nothing and is not mentioned in the
table — the bump reads as a straightforward security improvement. That is the
intended trade (less CVE-churn noise), but it does mean a real regression
below the threshold is invisible in the report. It is still recorded in
`metrics.json`.
