# AGENTS.md

Agent Skills for Red Hat Developer Hub engineering, operations, and repository
maintenance. Skills follow the Agent Skills open standard. Read `CONTEXT.md`
for domain language and `docs/adr/` for architectural decisions.

## 1. Think Before Coding

Do not assume or hide confusion.

- State assumptions explicitly.
- Surface multiple interpretations and tradeoffs.
- Prefer the simpler approach when it satisfies the request.
- Stop and ask when ambiguity would materially change the result.

## 2. Simplicity First

Write the minimum code that solves the requested problem.

- Add no speculative features or single-use abstractions.
- Keep CLI implementation stdlib-only except for the documented PEP 723 YAML
  exception in ADR-0002.
- If a change can be substantially smaller without losing behavior, simplify it.

## 3. Surgical Changes

Touch only what the request requires. Preserve unrelated work and match the
existing style. Remove only the imports, variables, functions, or files made
obsolete by your own change.

## 4. Goal-Driven Execution

Translate the request into observable success criteria and verify them. Run
`uv run pytest` before reporting repository work complete.

When any `.py` file changed, ship Python that already matches CI. Run ruff
after editing, and again before committing, opening a pull request, or
reporting work complete. Tests passing is not enough — `ruff check` is not
`ruff format --check`.

```bash
uv run ruff format <changed.py> ...
uv run ruff check <changed.py> ...
```

CI (`lint` job) runs the same tools across the tree:

```bash
uv run ruff check .
uv run ruff format --check .
```

Format **and** check. Fix findings, rerun until both pass, then include those
files in the same commit. Prefer ruff's quote style (single quotes when the
string contains `"`). Do not open a pull request until both pass.

## 5. No Irreversible Commands Without Confirmation

Never force-push, reset HEAD, merge branches, or run destructive commands
without explicit confirmation.

## 6. Learn From Corrections

When an implementation is corrected, apply the correction and record reusable
project-specific knowledge in the owning skill reference.

## Skill architecture

Skills are grouped by domain: `skills/jira/`, `skills/plugins/`, `skills/ci/`,
`skills/release/`, `skills/refinement/`, `skills/reference/`, `skills/meta/`.
Those folders are editorial and are stripped at install. Compose through `/skill-name`, never
through sibling category paths.

A promoted skill claims exactly one trigger phrase. Two skills that would claim
the same utterance are one skill; one skill answering several unrelated
utterances is several skills. Split by verb, never by noun, and weight the split
by what a misroute costs — merge where a misroute produces a wrong write, split
where it produces an obvious wrong answer. See ADR-0005.

Human invocation is a class, not a roster. A human-invoked skill is an entry
point a person types by name, and the router never reaches it. Every member
carries `disable-model-invocation: true` in `SKILL.md` and
`policy.allow_implicit_invocation: false` in `agents/openai.yaml`. Admit a new
one only when it holds no substance of its own and delegates to exactly one
model-invoked skill, the way `clean-prose` delegates to `prose-editing`;
`ask-rhdh` and `setup-rhdh-skills` are the other members today. Every other
promoted skill is model-invoked and omits both flags. Every promoted skill has
an `agents/openai.yaml` interface entry.

The complete pack also requires three external skills. Creation and interview
flows use `/grilling`; every `/rhdh-pr-review` run uses `/code-review`;
`/handoff` carries context into a later session, which is why no artifact
store does.

Keep drafts and retired skills outside the promoted discovery root:

- `internal/in-progress/`
- `internal/deprecated/`

Do not add them to promoted manifests or catalogs.

## Composition contracts

- `/ask-rhdh` is a catalog, not an orchestrator. It recommends a named skill
  and performs no setup or mutation.
- `/setup-rhdh-skills` owns setup routing, configuration, authentication, and
  compatibility with existing CLI/state locations.
- Credentials stay inside an authenticated adapter backed by a native tool
  store or host connector. Workflow instructions and non-adapter scripts may
  detect capability, but only that adapter may retrieve a transient credential
  and authenticate a request. Public arguments, output, logs, plans, and
  artifacts remain credential-free. Setup owns login and never creates a
  parallel credential store.
- `/rhdh-context` owns shared repository and version context.
- `/prose-editing` owns the prose pass. The final composer invokes it exactly
  once for free-form GitHub, GitLab, Jira, or Slack prose before anybody sees,
  gates, or posts that text. The caller names the register because it knows what
  it wrote. Helpers invoke it only when they return the final prose directly;
  transport layers never do. Structured payloads, fixed commands, checksums,
  generated reports, and local documents with an owning authoring skill stay
  outside this automatic pass.
- Skills pass context by invoking each other by name. There is no artifact
  envelope and no artifact store. When the user needs context to survive into a
  later session, tell them to run `/handoff`.
- Every external write goes through the write gate in `/mutation-gate`:
  state each operation with its target, exact command, preview, and failure
  behaviour; get approval for that stated set; execute; report the outcome of
  every operation, including the skipped ones. The plan renders as a table in
  the conversation. A plan too large for the transcript goes to a file in the
  temporary directory and the path is printed. Read-only inspection needs no
  gate. See ADR-0007.
- `/rhdh-forge` constructs forge payloads and never executes them. A caller that
  needs a write receives a command, not an effect.
- Adapters isolate external variation such as Jira/GitHub issues, GitHub/GitLab
  forges, Podman/Docker, lifecycle sources, and CI systems.

Keep shared behavior behind the owning skill interface. Do not reach into
another skill's references or scripts.

Duplication is judged by layer. **Prompt duplication is forbidden**: when the
same instructions, protocol, or domain rule would appear in two skills,
**extract** a reference skill when nothing owns it, **enforce** the existing
interface when a module already does, or **document** it once when it is a rule
rather than a capability — here for rules governing this repository, in
`skill-authoring` for rules that must ship with the pack, since this file
does not travel with it. **Code duplication is acceptable**: bundled scripts are
self-contained so a skill can be installed alone, and there is no shared runtime
package. See ADR-0006.

A skill's name describes its subject. `rhdh-` belongs on a skill that is about
Red Hat Developer Hub — its repositories, Jira projects, release train, or
plugins. Most skills here qualify, so the prefix is near-universal, but that is a
fact about this collection rather than a rule about skills.

A skill that is not about RHDH does not take the prefix. `skill-authoring` teaches
the Agent Skills standard and should be usable by someone authoring a skill in an
unrelated repository, so it carries a generic name and generic guidance. Ask what
a skill is *about*; if the answer does not contain "RHDH", neither does its name.

The prefix is not a namespace-isolation mechanism — the router matches
descriptions, not names. Isolation comes from distinct trigger phrases and
literal proper nouns in the description. See ADR-0008.

## A skill may not depend on this repository

Only a skill's own directory is installed. `AGENTS.md`, `CONTEXT.md`,
`CONTRIBUTING.md`, and `docs/adr/` do not travel with it, so nothing under
`skills/` may cite them or any path outside its own directory. A skill that does
is broken for every user who installs it: the pointer resolves to nothing, and
the rule it was carrying is simply absent.

When a decision here produces a rule an agent needs at runtime, restate the rule
in the skill that needs it, in its own words. Cite the ADR in this file, in
`CONTRIBUTING.md`, or in another ADR — never in shipped prose.

## Testing

Test behavior and contracts:

- deterministic scripts and CLIs;
- adapter contracts;
- catalog membership, invocation metadata, distribution exclusions, and links;
- that no promoted skill directory sits outside a domain category;
- workflow integration at named-skill seams.

Do not add tests that require incidental prose, headings, menu numbering, or
exact wording. Prose may change without changing the interface.

## Versioning and cutover

Git tags are the only authoritative versions. The `skills` CLI resolves tags,
not version files.

After merging changes to behavior, scripts, or `SKILL.md` files, create and push
an appropriate semantic-version tag. Use patch for behavior fixes, minor for new
backward-compatible capabilities, and major for breaking changes.

No tag exists yet, so the pack resolves the default branch. Bundled scripts have
no shared runtime dependency to pin alongside it.

## Agent project configuration

### Issue tracker

GitHub Issues via `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default labels are `needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` plus root `docs/adr/`. See
`docs/agents/domain.md`.
