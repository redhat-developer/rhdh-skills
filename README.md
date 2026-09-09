# RHDH Skills

Composable Agent Skills for Red Hat Developer Hub engineering, operations, and
repository maintenance. The pack captures RHDH-specific repository knowledge,
version policy, delivery workflows, CI, release operations, and local testing
behind a small set of task-oriented interfaces.

## Install

Install the pack and the three external skills it depends on. The second
command is one source for `/grilling`, `/code-review`, and `/handoff`. Each
command opens the skills wizard, which asks where to put them:

```bash
npx skills add redhat-developer/rhdh-skills --global
npx skills add mattpocock/skills --global
```

Restart your agent client so it discovers them.

## Set up the tools the skills need

The skills drive external tools: `acli` for Jira, `gh` for pull requests, `gog`
for the team and schedule spreadsheets, `oc` for OpenShift CI, and podman or
docker for local RHDH. Almost nothing works until those are installed and
authenticated.

```text
/setup-rhdh-skills
```

It reports which tools are missing or unauthenticated, walks you through each one,
and finds your RHDH repository checkouts so the other skills stop asking for
paths. Run it again whenever a tool or checkout changes.

It can also install the skills themselves, if you would rather not run the `npx`
commands above: invoke `/setup-rhdh-skills install` after installing that one
skill on its own. It shows you the plan before running anything.

Run `/ask-rhdh` whenever you want help choosing a skill.

## Skill catalog

Run `/ask-rhdh` to find the right skill: describe what you are doing and it names
one. It performs no work itself.

`skills/meta/setup-rhdh-skills/assets/catalog.json` is the machine-readable roster
and the single source of truth for membership. This file does not restate it.

Three skills are human-invoked and never selected automatically: `/ask-rhdh`,
`/setup-rhdh-skills`, and `/clean-prose`. The other 57 are model-invoked, and can
also be called by name.

Skills are grouped into seven folders:

| Folder | Covers |
| --- | --- |
| `jira/` | Creating, refining, updating, and reporting on RHIDP, RHDHPLAN, RHDHBUGS, and RHDHSUPP work, plus sprint ceremonies and linking PRs to issues. |
| `plugins/` | Authoring, wiring, exporting, and fixing Backstage dynamic plugins; the overlays repository; local RHDH; opening and reviewing pull requests; testing rhdh-operator PRs on a cluster; midstream propagation. |
| `ci/` | Prow job configuration and nightly triggers, Konflux and Tekton task updates, release-data admission tags, base images, and Yarn bumps. |
| `release/` | Release status and readiness, candidate-feature capacity through Code Freeze, milestone schedules, freeze announcements, teams, test-plan review, platform lifecycle, plugin CVE export, and RC/GA Helm+Operator smoke. |
| `refinement/` | The OpenSpec artifact-driven change workflow: propose, explore, implement, audit, verify, and archive a change. See [the workflow](docs/refinement/refinement-workflow.md). |
| `reference/` | The reusable layer other skills invoke by name: repository and version context, the forge read seam, the write gate, the OpenSpec journal and RHDH's spec-driven schema, and the Jira and Backstage reference material. |
| `meta/` | The three human-invoked entry points, plus skill authoring and repository agent-readiness. |

## How skills compose

A skill claims one trigger phrase, and invokes another skill by its stable name,
such as `/rhdh-context` or `/rhdh-jira-api`. The folders above are for readers of
this repository. They are stripped at install, so a path is never part of the
interface. Handoffs happen in the conversation: there is no artifact envelope and
no artifact store. When context needs to survive into a later session, run
`/handoff`.

`--all` is the recommended install because skills reach each other by name. A
single skill will work on its own, because bundled scripts are self-contained and
there is no shared runtime package, provided anything it invokes is also present.

`/setup-rhdh-skills` installs and verifies; it never deletes. It cannot tell a
skill it did not install from one you wrote and kept, so removing anything else
is yours to do.

Three skills come from outside this repository and are required rather than
optional. `/grilling` supplies the interview discipline that skill authoring and
Jira creation depend on, so those flows stop rather than guess. `/code-review`
is required on every `/rhdh-pr-review` run, so a missing install stops rather
than substituting. `/handoff` is what carries context into a later session,
which is why this pack ships no artifact store of its own.

Free-form GitHub, GitLab, Jira, and Slack prose goes through `/prose-editing`
exactly once at its final composer. Structured payloads, commands, generated
reports, and local authoring artifacts do not. Run `/clean-prose` with pasted
text or a file path to put your own draft through the same pass.

Every external write goes through the write gate. The skill states each operation
with its target, exact command, preview, and what happens on failure; you approve
that stated set; then it executes and reports the outcome of every operation,
including the ones it skipped. Read-only discovery and analysis need no approval.

`/rhdh-forge` reads GitHub and GitLab and constructs forge payloads, but never
executes a write. A caller that needs one gets a command, not an effect. That
separation is what keeps the gate enforceable.

Shared prose lives in reference skills, invoked by name rather than found by
walking the filesystem. Shared code does not exist: each skill carries its own
helpers.

See [ADR-0005](docs/adr/0005-one-skill-per-trigger-phrase.md),
[ADR-0006](docs/adr/0006-duplication-by-layer.md),
[ADR-0007](docs/adr/0007-write-gate.md), and
[ADR-0008](docs/adr/0008-skill-naming-and-namespace-isolation.md).

## CLI and state

- `rhdh` and `rhdh-local` are bundled wrappers, run from their skill directory.
- Repository configuration lives at `~/.config/rhdh-skills/config.json`.
- Worklog and todo state lives under `.rhdh/`.
- Cross-session handoff is not a pack feature; run `/handoff` when you need it.

## Development

```bash
uv sync --extra dev
git config core.hooksPath .githooks
uv run pytest
```

Tests protect scripts, adapters, and catalog contracts. They do not pin
incidental prose shape. See [CONTRIBUTING.md](CONTRIBUTING.md).

Versions are published exclusively as git tags. Changes to skill behavior or
scripts require the appropriate patch, minor, or major tag after merge.

## License

Apache-2.0. See [LICENSE](LICENSE).
