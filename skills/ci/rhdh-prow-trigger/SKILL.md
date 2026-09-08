---
name: rhdh-prow-trigger
description: >-
  Runs an RHDH nightly ProwJob on demand through the OpenShift CI Gangway REST
  API, for `periodic-ci-redhat-developer-rhdh-*-nightly` and
  `periodic-ci-redhat-developer-rhdh-plugin-export-overlays-*-nightly` jobs, with
  optional image registry/repo/tag, catalog-index, Helm chart, Playwright, fork,
  and Slack-alert overrides. Use for "trigger the nightly", "run the e2e job
  now", "kick off the AKS operator job on 1.9", RC or GA image verification runs,
  or listing the available nightly jobs and quay.io tags.
compatibility: "Python 3.9+ and uv; the oc CLI with an existing OpenShift CI session in ~/.config/openshift-ci/kubeconfig."
---

# Trigger an RHDH nightly ProwJob

Execute a job that is already configured in `openshift/release`. This skill never
edits CI configuration: changing which jobs exist is `/rhdh-prow-jobs` for test
entries and pools, and `/rhdh-prow-release-branch` for a release branch's whole
job set.

## Route

Load `workflows/trigger-nightly.md`. It covers listing jobs, mapping a
natural-language request to a full job name, the override options, and execution.

## Authentication

`scripts/trigger_nightly_job.py` uses a dedicated kubeconfig at
`~/.config/openshift-ci/kubeconfig` so it never disturbs the user's current
cluster context. It consumes an existing `oc` session and never performs a login.

Live submission and `--status` require that session. When `oc` is missing, the
dedicated kubeconfig is absent, or the session has expired, stop and tell the
user to run `/setup-rhdh-skills openshift-ci`. Setup owns login; this skill does
not. Offline previews and public job/tag listings do not require authentication.

The public script hands `scripts/gangway_adapter.py` only a kubeconfig path and
the request payload. That adapter alone retrieves the transient credential and
authenticates the request, and returns credential-free response data. Keep
tokens out of arguments, output, and anything reported back.

## Execution rules

Triggering a job is an external write; `--dry-run`, `--list`, `--list-tags`, and
`--status` are not. Follow `/mutation-gate`, with the full job name as the target.

- Preview with `--dry-run` first. It validates the supported nightly name and
  flags offline, then prints the adapter request without accessing credentials,
  creating configuration, or making network requests. It does not validate job,
  image, or chart existence. Live submission checks the owning repository's
  configured job list and stops if membership cannot be verified.
- The preview carries the full command, parameters, resource impact, unknown
  cost, abort guidance, failure behavior, and verification steps. Use it in the
  write gate; get explicit approval before running without `--dry-run`.
- GKE and OSD-GCP each share one cluster. Never start a second job on the same
  platform while one is running; warn the user before triggering either.
- Approval to inspect or dry-run is not approval to execute. Ask again.
- `--image-repo` requires `--tag`; `--tag` works alone. `--playwright-version` is
  overlay-only. Image, chart, and alert overrides are rejected for overlay jobs.

## Completion

A trigger is complete when the executed command is shown exactly as run, the
Gangway API response is reported, and the run URL or ID is stated prominently —
or, when the API returned no identifier, that absence is stated rather than
implied. A dry run is complete when the printed request is shown and it is clear
that nothing was executed. A failure is complete when the error is reported with
its likely cause, expired authentication being the common one, and the user is
pointed at `/setup-rhdh-skills openshift-ci` when the session is the problem. No
credential appears in any of it.
