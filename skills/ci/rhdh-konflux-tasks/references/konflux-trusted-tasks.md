# Trusted-task / ECP expiry check

Load this reference when the request is an **ECP / Conforma** failure
(`tasks.unsupported`, `tasks.required_untrusted_task_found`,
`trusted_task.trusted`), an **expired** or **untrusted** Konflux task pin, or
when validating YAML against
`quay.io/konflux-ci/tekton-catalog/data-acceptable-bundles:latest`.

This check is **not** a frozen `verify_*` param-drift guard. It reads the live
allow-list Konflux already uses, so a later catalog bump can change the answer.

## Why pins go stale

Enterprise Contract treats a task bundle as trusted only while its digest is in
`trusted_tasks` with `effective_on` not in the future and `expires_on` still in
the future (or omitted). Konflux revokes older digests as newer ones ship. A pin
that built last week can fail ECP without any pipeline-param change. See
[Conforma trusted tasks](https://conforma.dev/docs/policy/trusted_tasks.html).

## Horizon (14 days)

Do not wait until `expires_on <= now`. There is no buffer to test a bump before
release if the pin dies tomorrow.

`cutoff = now + 14 days`. A digest is **usable with buffer** when it is present,
`effective_on` is not in the future, and it has no `expires_on` **or**
`expires_on > cutoff`. `--horizon-days` overrides the window (tests may pass `0`).

## Run

From a checkout that has `.tekton` (or pass paths). The same script is
`build/scripts/checkTrustedTasks.sh` in `rhdh-plugin-catalog`.

```bash
# Live allow-list (needs skopeo)
scripts/check-trusted-tasks.sh --json .tekton

# Rewrite same-tag SHA only (never auto-bumps tags)
scripts/check-trusted-tasks.sh --apply-trusted-digests .tekton
```

Tag bumps still need `updateDigests.sh --minor` plus the live `MIGRATION.md`.
`--strict` fails on `stale` (trusted but not the current record).

`--print-digest IMAGE:TAG` and `--print-latest-tag IMAGE` are for
`updateDigests.sh` so the SHA comes from the allow-list, not a too-new
`skopeo inspect` digest that ECP does not trust yet.

## Statuses

| Status | Meaning | Exit |
|--------|---------|------|
| `trusted` | usable with buffer | 0 |
| `stale` | usable with buffer, not the current record | 0 unless `--strict` |
| `expired` / `untrusted` | missing or `expires_on <= cutoff`, and a successor exists | 1 |
| `expiring-no-successor` | `now < expires_on <= cutoff`, no successor | 0 + **must REPORT** |
| `expired-no-successor` | already past `now` (or missing) and no successor | 1 + **must REPORT** |

Required report when there is no successor (stderr and the user-facing summary):

```
[WARN] <task>:<tag>@sha256:<digest> expires on <expires_on> (horizon is 14 days).
No newer trusted tag/digest is in data-acceptable-bundles yet.
Re-run this check in a few days after Konflux publishes a replacement.
If none appears, ask in Slack #konflux-users.
```

Do not hide that warning as debug. Do not invent a pin when the list has nothing
to pin.
