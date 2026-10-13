# RHDH Skills

Ubiquitous language for the Red Hat Developer Hub skill collection and the
plugin, release, and repository work it supports.

## Language

### Skill architecture

**Promoted skill**:
A public Agent Skill included in the repository catalog and complete
distribution. It is either human-invoked or model-invoked.
_Avoid_: public module, top-level skill

**Promoted catalog**:
The machine-readable record of promoted membership, invocation mode, named
dependencies, artifact contracts, and distribution sources. Human documentation
summarizes it and never defines a competing inventory.
_Avoid_: skill list, manifest, registry

**Human-invoked skill**:
A user-selected entry point that orients or configures the collection. It is
never selected automatically and never invoked by another skill.
_Avoid_: model router, orchestrator

**Model-invoked skill**:
A task-oriented capability that an agent may select automatically or another
model-invoked skill may invoke by name.
_Avoid_: sub-skill, leaf skill

**Reference skill**:
A model-invoked skill whose reason for existing is material that two or more
skills would otherwise each carry. It is reached by name like any other
model-invoked skill. Two callers is the threshold; one caller means the material
belongs inside its single owner.
_Avoid_: foundation skill, base skill, primitive, shared skill

**Trigger phrase**:
The user utterance a skill claims. Two promoted skills must not claim the same
one; where they would, they are one skill. Where one skill answers to several
unrelated utterances, it is several skills.
_Avoid_: intent, route, keyword

**Editorial category**:
A reader-facing grouping of promoted skills by domain — `jira`, `plugins`, `ci`,
`release`, `refinement`, `reference`, `meta`. It is not a namespace, dependency
boundary, or composition path, and it is stripped when the pack is installed.
_Avoid_: package, subsystem

**Named skill composition**:
Composition in which a model-invoked skill calls another model-invoked skill by
its stable name. The caller never opens the callee's files, imports its
implementation, or reaches it through a category path.
_Avoid_: sibling load, relative-path composition

**Write gate**:
The rule that an external change is stated in full, approved, and then reported
on. State every operation with its target, exact command, preview, and failure
behaviour; get approval for that stated set; execute; report the outcome of every
operation including the skipped ones. It renders in the conversation, because
that is where approval happens.
_Avoid_: mutation plan, material hash, confirmation prompt, dry run

**Setup capability**:
A prerequisite such as an installed skill, repository location, tool, or
authenticated external service that is diagnosed and configured through the
human setup entry point.
_Avoid_: hidden prerequisite, skill-local setup

**Authenticated adapter**:
A capability module backed by a native CLI credential store or host connector.
It owns transient credential retrieval, request authentication, and redaction;
the calling workflow sees only credential-free inputs and outputs.
_Avoid_: token file, auth shell variable, raw authenticated fallback

### Plugin overlays

**Workspace**:
The unit of overlay ownership and configuration for one upstream Backstage
plugin.
_Avoid_: project, package, module

**Overlay**:
The RHDH-specific export and build definition applied to an upstream Backstage
plugin. It is not a filesystem or CSS overlay.
_Avoid_: wrapper, shim, adapter

**Publish trigger**:
A `/publish` request that starts the overlay validation and build workflow for a
change request.

**Plugin Owner**:
An external contributor or team responsible for its own plugins and Workspaces.
_Avoid_: contributor, maintainer

**Core Team**:
The COPE/Plugins team responsible for repository-wide triage, merge decisions,
and infrastructure.
_Avoid_: maintainers, admins

### Support tiers

**Supported**:
A generally available plugin fully supported by Red Hat. Its Workspace changes
receive the highest triage priority.

**Tech Preview**:
A productized plugin available as a technology preview. Its Workspace changes
receive high triage priority.

**Community**:
A development-preview or community-maintained plugin. Its Workspace changes
receive lower triage priority.
_Avoid_: mandatory workspace, non-mandatory workspace
