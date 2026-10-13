#!/usr/bin/env python3
"""Validate the promoted RHDH skill catalog and composition graph."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import itertools
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

CATALOG_PATH = Path("skills/meta/setup-rhdh-skills/assets/catalog.json")
PROMOTED_CATEGORIES = ("jira", "plugins", "ci", "release", "refinement", "reference", "meta")
# A cited skill, as `/name`. It must follow a space, a line start, or an opening
# bracket or backtick, never another path segment, so `~/rhdh-local-setup` and
# `redhat-developer/rhdh-plugin-catalog` stay paths. Matching only the rhdh-
# prefixes missed every skill
# whose subject is not RHDH — prose-editing, clean-prose, mutation-gate,
# skill-authoring — so renaming one left its callers dangling silently. Every
# promoted name is kebab-case, but a skill can still be a single token. Route-like
# tokens are filtered against the promoted/external/retired name sets below. A
# trailing slash or dot means the token is a path, not a skill.
NAMED_INVOCATION = re.compile(
    r"""(?:^|(?<=[\s(\[`'"]))/([a-z0-9]+(?:-[a-z0-9]+)*)(?![\w-])(?![/.])""",
    re.MULTILINE,
)
EXTERNAL_SKILLS = {"code-review", "grilling", "handoff"}
RETIRED_SKILLS = {"humanizer"}
# A bundled script reading a file that ships *with it*, such as
# `_DATA_DIR / "jql-release.md"`. Anchored to the handful of names that mean
# "this script's own directory", because a bare `dir / "config.json"` is usually
# a file in the user's home or checkout, which the skill neither ships nor should.
SCRIPT_DATA_READ = re.compile(
    r"(_DATA_DIR|_HERE|_SKILL_DIR|SKILL_DIR|_REFERENCES_DIR|script_dir)\s*/\s*"
    r'"([\w.-]+\.(?:md|json|ya?ml|txt))"'
)
HOST_SKILL_PATHS = (".claude/skills", ".agents/skills", ".cursor/skills", ".codex/skills")
SHIPPED_SUFFIXES = {".md", ".py", ".sh", ".mjs"}
DUPLICATE_BLOCK_LINES = 25
FENCE_OPEN = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})[^\r\n]*(?:\r?\n|$)")
BLOCKQUOTE_MARKER = re.compile(r" {0,3}> ?")


def _frontmatter(text: str) -> dict[str, Any]:
    """Parse the small frontmatter subset used by catalog validation."""
    normalized = text.replace("\r\n", "\n")
    match = re.match(r"^---\n(.*?)\n---(?:\n|$)", normalized, re.DOTALL)
    if not match:
        return {}

    result: dict[str, Any] = {}
    lines = match.group(1).splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        scalar = re.match(r"^([a-zA-Z][a-zA-Z0-9-]*):\s*(.*?)\s*$", line)
        if not scalar:
            index += 1
            continue
        key, value = scalar.groups()
        if value in {"|", ">", "|-", ">-"}:
            block: list[str] = []
            index += 1
            while index < len(lines) and (not lines[index].strip() or lines[index][0].isspace()):
                block.append(lines[index].strip())
                index += 1
            result[key] = "\n".join(block).strip()
            continue
        unquoted = value.strip("\"'")
        if unquoted.lower() in {"true", "false"}:
            result[key] = unquoted.lower() == "true"
        else:
            result[key] = unquoted
        index += 1
    return result


def _body(text: str) -> str:
    """Return the document with its frontmatter removed."""
    normalized = text.replace("\r\n", "\n")
    return re.sub(r"^---\n.*?\n---(?:\n|$)", "", normalized, count=1, flags=re.DOTALL)


def _blockquote_layers(line: str) -> list[str]:
    """Return the line after each valid nested CommonMark blockquote marker."""
    layers = [line]
    remainder = line
    while marker := BLOCKQUOTE_MARKER.match(remainder):
        remainder = remainder[marker.end() :]
        layers.append(remainder)
    return layers


def _without_noninstructions(text: str) -> str:
    """Remove fenced examples and comments that an agent does not follow."""
    instructions: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    fence_blockquote_depth = 0
    for line in text.splitlines(keepends=True):
        blockquote_layers = _blockquote_layers(line)
        blockquote_depth = len(blockquote_layers) - 1
        if fence_character is not None:
            if blockquote_depth >= fence_blockquote_depth:
                fence_line = blockquote_layers[fence_blockquote_depth]
                closing = (
                    rf" {{0,3}}{re.escape(fence_character)}{{{fence_length},}}"
                    r"[ \t]*(?:\r?\n)?"
                )
                if re.fullmatch(closing, fence_line):
                    fence_character = None
                    fence_length = 0
                    fence_blockquote_depth = 0
                continue
            fence_character = None
            fence_length = 0
            fence_blockquote_depth = 0

        fence_line = blockquote_layers[-1]
        opening = FENCE_OPEN.match(fence_line)
        if opening:
            fence = opening.group("fence")
            info = fence_line[opening.end("fence") :].rstrip("\r\n")
            if fence[0] == "`" and "`" in info:
                instructions.append(line)
                continue
            fence_character = fence[0]
            fence_length = len(fence)
            fence_blockquote_depth = blockquote_depth
            continue
        instructions.append(line)

    text = "".join(instructions)
    return re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)


# A wrapper delegates and stops, so its body is one short sentence. Anything
# past that is substance, and substance owes a '## Completion' section.
WRAPPER_MAX_LINES = 1
WRAPPER_MAX_WORDS = 15


def _delegation_target(body: str) -> str | None:
    """Return the one skill a delegating wrapper runs, or None if it is not one.

    A delegating wrapper is an entry point a person types that holds no substance
    of its own: it delegates and stops. Recognising it by shape rather than by a
    roster is what lets a new one arrive without amending a rule, so the shape has
    to be narrow enough that a real skill cannot fall into it and thereby escape
    the '## Completion' requirement. Three tests do that work: no heading of any
    level, a body of at most a few lines, and exactly one skill named in prose.

    Fenced code and HTML comments are removed first. A skill named only inside
    either one is not an instruction the agent follows, so it cannot be the
    delegation, and a body whose visible text delegates to nothing must fail.
    """
    body = _without_noninstructions(body)
    if re.search(r"(?m)^#{1,6}\s+\S", body):
        return None
    lines = [line for line in body.splitlines() if line.strip()]
    if len(lines) > WRAPPER_MAX_LINES:
        return None
    if len(re.findall(r"[A-Za-z0-9][\w'-]*", " ".join(lines))) > WRAPPER_MAX_WORDS:
        return None
    # A setext heading underlines its text, so it needs no '#' to be a section.
    if any(re.fullmatch(r"\s*(?:=+|-{2,})\s*", line) for line in lines):
        return None
    targets = {match.group(1) for match in re.finditer(r"/([a-z0-9]+(?:-[a-z0-9]+)*)\b", body)}
    if len(targets) != 1:
        return None
    return targets.pop()


def _mentions(body: str, term: str) -> bool:
    """Report whether the body names a skill or artifact rather than a longer token.

    ``/rhdh-jira`` and `` `rhdh-jira` `` both count; ``rhdh-jira-legacy`` does not.
    """
    body = _without_noninstructions(body)
    return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", body) is not None


def _dependency_instructions(skill_dir: Path, skill_body: str) -> str:
    """Return instruction prose that can own a catalog dependency citation.

    A skill may route the relevant operation into a workflow or keep supporting
    protocol in a reference. Requiring the parent SKILL.md to repeat that citation
    would make the prompt say the same thing in two places.
    """
    documents = [skill_body]
    for directory in ("workflows", "references"):
        instruction_root = skill_dir / directory
        if not instruction_root.is_dir():
            continue
        documents.extend(
            path.read_text(encoding="utf-8", errors="replace")
            for path in sorted(instruction_root.rglob("*.md"))
        )
    return "\n".join(documents)


def _shipped_files(skill_dir: Path) -> Iterator[Path]:
    """Yield the prose a skill ships, skipping build residue and implementation.

    Duplication is judged by layer (ADR-0006). Prompt duplication is forbidden, so
    every file an agent reads as instructions is compared. Code duplication is
    expected — bundled scripts are self-contained so a skill installs alone — so
    anything under ``scripts/`` is exempt, including the data files those scripts
    parse.
    """
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SHIPPED_SUFFIXES:
            continue
        if "__pycache__" in path.parts or "scripts" in path.relative_to(skill_dir).parts:
            continue
        yield path


def _duplicate_files(root: Path, skill_dirs: dict[str, Path]) -> list[tuple[str, str]]:
    """Return file pairs from different skills that ship the same content.

    Compares whole files and every window of ``DUPLICATE_BLOCK_LINES`` significant
    lines, so a copy that only differs in its header block is still reported.
    """
    groups: dict[str, set[tuple[str, str]]] = {}
    for name, skill_dir in skill_dirs.items():
        for path in _shipped_files(skill_dir):
            text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            if not lines:
                continue
            owner = (name, path.relative_to(root).as_posix())
            keys = ["\n".join(lines)]
            keys.extend(
                "\n".join(lines[start : start + DUPLICATE_BLOCK_LINES])
                for start in range(len(lines) - DUPLICATE_BLOCK_LINES + 1)
            )
            for key in keys:
                digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
                groups.setdefault(digest, set()).add(owner)

    pairs: set[tuple[str, str]] = set()
    for group in groups.values():
        if len({name for name, _ in group}) < 2:
            continue
        for left, right in itertools.combinations(sorted(group), 2):
            if left[0] != right[0]:
                pairs.add((left[1], right[1]))
    return sorted(pairs)


def _resembles_a_skill(cited: str, known: set[str]) -> bool:
    """Report whether an unknown ``/name`` is a stale skill citation or a URL path.

    Skill documentation writes a route the same way it writes a skill: ``/my-plugin``
    in backticks is a mount point, ``/prose-editing`` in backticks is an invocation.
    Nothing in the syntax separates them, so use what a stale citation actually is —
    the residue of a rename or a split, which leaves a name that still resembles the
    skill that replaced it. ``/rhdh-jira`` survives as a prefix of ``rhdh-jira-create``;
    ``/image-registry`` resembles nothing in the catalog.
    """
    if cited in RETIRED_SKILLS:
        return True
    for name in known:
        if cited.startswith(f"{name}-") or name.startswith(f"{cited}-"):
            return True
    return bool(difflib.get_close_matches(cited, sorted(known), n=1, cutoff=0.8))


def _validate_named_invocations(
    root: Path,
    skill_dirs: dict[str, Path],
    catalog_names: set[str],
    errors: list[dict[str, str]],
) -> None:
    """Every ``/rhdh-name`` a skill cites must be a skill that exists.

    Skills compose by name, so a name is the whole interface. A rename leaves the
    citing prose pointing at nothing, and neither a link check nor a dependency
    check catches it — the reference is not a path and not a declared dependency.
    Four dangling ``/rhdh-jira`` citations survived a split this way.
    """
    known = catalog_names | EXTERNAL_SKILLS
    for name, skill_dir in sorted(skill_dirs.items()):
        for path in _shipped_files(skill_dir):
            text = path.read_text(encoding="utf-8", errors="replace")
            # A `/name` inside a fenced block is sample code — a React route, a
            # URL path, a shell argument — not an instruction to invoke a skill.
            text = _without_noninstructions(text)
            for cited in sorted(set(NAMED_INVOCATION.findall(text))):
                if cited in known or not _resembles_a_skill(cited, known):
                    continue
                errors.append(
                    {
                        "code": "UNKNOWN_SKILL_REFERENCE",
                        "message": (
                            f"{path.relative_to(root).as_posix()} invokes /{cited}, which is "
                            f"not a promoted skill or a required external one; it was likely "
                            f"renamed or split"
                        ),
                    }
                )


def _validate_script_data_files(
    root: Path, skill_dirs: dict[str, Path], errors: list[dict[str, str]]
) -> None:
    """Every data file a bundled script opens must ship inside that same skill.

    A script is self-contained by design, so nothing else checks what it reads. The
    duplicate-file rule deliberately exempts ``scripts/``, which means the data
    those scripts parse is exempt too — and that is exactly how four release skills
    came to ship a parser without its templates. Eleven subcommands raised an
    uncaught ``FileNotFoundError`` while catalog validation and 366 tests stayed
    green, because only one of the four skills had a test.
    """
    for name, skill_dir in sorted(skill_dirs.items()):
        for script in sorted(skill_dir.rglob("*.py")):
            if "__pycache__" in script.parts:
                continue
            text = script.read_text(encoding="utf-8", errors="replace")
            for directory, filename in SCRIPT_DATA_READ.findall(text):
                base = script.parent if directory in {"_DATA_DIR", "_HERE"} else skill_dir
                if not (base / filename).exists() and not (script.parent / filename).exists():
                    errors.append(
                        {
                            "code": "SCRIPT_DATA_MISSING",
                            "message": (
                                f"{script.relative_to(root).as_posix()} reads {filename}, "
                                f"which {name} does not ship; the skill cannot run installed "
                                f"alone"
                            ),
                        }
                    )


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, path: list[str]) -> list[str] | None:
        if node in visiting:
            return path[path.index(node) :] + [node]
        if node in visited:
            return None
        visiting.add(node)
        for dependency in graph.get(node, []):
            if dependency not in graph:
                continue
            cycle = visit(dependency, [*path, dependency])
            if cycle:
                return cycle
        visiting.remove(node)
        visited.add(node)
        return None

    for name in graph:
        cycle = visit(name, [name])
        if cycle:
            return cycle
    return None


def _validate_internal_skills(root: Path, errors: list[dict[str, str]]) -> None:
    """Require drafts to declare the nested internal metadata gate."""
    draft_root = root / "internal" / "in-progress"
    for skill_file in draft_root.glob("*/SKILL.md"):
        content = skill_file.read_text(encoding="utf-8")
        frontmatter_match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", content, re.DOTALL)
        frontmatter = frontmatter_match.group(1) if frontmatter_match else ""
        metadata_match = re.search(
            r"(?m)^metadata:\s*$\r?\n(?P<body>(?:^[ \t]+[^\r\n]*(?:\r?\n|$))*)",
            frontmatter,
        )
        metadata = metadata_match.group("body") if metadata_match else ""
        is_internal = bool(re.search(r"(?m)^[ \t]+internal:\s*true\s*$", metadata))
        if not is_internal:
            errors.append({"code": "IN_PROGRESS_PUBLIC", "message": str(skill_file)})


def _validate_local_links(
    root: Path, document: Path, content: str, errors: list[dict[str, str]]
) -> None:
    """Validate real skill/workflow links without interpreting template examples."""
    relative = document.relative_to(root)
    if document.name != "SKILL.md" and "workflows" not in relative.parts:
        return
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", content):
        target = match.group(1).strip().split("#", 1)[0]
        if (
            not target
            or "://" in target
            or target.startswith(("/", "#", "mailto:"))
            or "<" in target
        ):
            continue
        resolved = (document.parent / target).resolve()
        if not resolved.exists():
            errors.append(
                {
                    "code": "LINK_MISSING",
                    "message": f"{relative.as_posix()} -> {target}",
                }
            )


def validate_repository(root: Path) -> dict[str, Any]:
    """Return an observable validation report for a repository checkout."""
    root = root.resolve()
    catalog_file = root / CATALOG_PATH
    errors: list[dict[str, str]] = []

    if not catalog_file.is_file():
        return {
            "valid": False,
            "errors": [{"code": "CATALOG_MISSING", "message": str(catalog_file)}],
            "promotedSkills": [],
            "humanInvokedSkills": [],
            "requiredExternalSkills": [],
        }

    try:
        catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "valid": False,
            "errors": [{"code": "CATALOG_INVALID", "message": str(exc)}],
            "promotedSkills": [],
            "humanInvokedSkills": [],
            "requiredExternalSkills": [],
        }

    if catalog.get("schemaVersion") != 1:
        errors.append({"code": "SCHEMA_VERSION", "message": "schemaVersion must be 1"})

    entries = catalog.get("skills")
    if not isinstance(entries, list):
        entries = []
        errors.append({"code": "SKILLS_TYPE", "message": "skills must be an array"})

    promoted_names: list[str] = []
    human_names: list[str] = []
    wrapper_delegations: dict[str, tuple[str, Path]] = {}
    entry_by_name: dict[str, dict[str, Any]] = {}
    external_entries = catalog.get("pack", {}).get("requiredExternalSkills", [])
    external_names = [item.get("name") for item in external_entries if isinstance(item, dict)]
    external_set = {name for name in external_names if isinstance(name, str)}

    catalog_names = {
        entry.get("name")
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append({"code": "SKILL_ENTRY_TYPE", "message": repr(entry)})
            continue
        name = entry.get("name")
        category = entry.get("category")
        invocation = entry.get("invocation")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            errors.append({"code": "SKILL_NAME", "message": repr(name)})
            continue
        if name in entry_by_name:
            errors.append({"code": "SKILL_DUPLICATE", "message": name})
            continue
        entry_by_name[name] = entry
        promoted_names.append(name)
        if category not in PROMOTED_CATEGORIES:
            errors.append({"code": "SKILL_CATEGORY", "message": f"{name}: {category}"})
            continue
        if invocation not in {"human", "model"}:
            errors.append({"code": "SKILL_INVOCATION", "message": f"{name}: {invocation}"})
        if invocation == "human":
            human_names.append(name)

        skill_dir = root / "skills" / category / name
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            errors.append({"code": "SKILL_MISSING", "message": str(skill_file)})
            continue
        skill_text = skill_file.read_text(encoding="utf-8")
        body = _body(skill_text)
        frontmatter = _frontmatter(skill_text)
        if frontmatter.get("name") != name:
            errors.append(
                {
                    "code": "FRONTMATTER_NAME",
                    "message": f"{skill_file}: expected {name!r}",
                }
            )
        description = frontmatter.get("description")
        if not isinstance(description, str) or not 0 < len(description) <= 1024:
            errors.append({"code": "FRONTMATTER_DESCRIPTION", "message": str(skill_file)})
        human_flag = frontmatter.get("disable-model-invocation") is True
        if human_flag != (invocation == "human"):
            remedy = (
                "set disable-model-invocation: true in the frontmatter"
                if invocation == "human"
                else "drop disable-model-invocation from the frontmatter"
            )
            errors.append(
                {
                    "code": "INVOCATION_MISMATCH",
                    "message": (
                        f"{name}: catalog={invocation}, frontmatter human={human_flag}; "
                        f"{remedy} or change the catalog invocation"
                    ),
                }
            )

        delegates_to = _delegation_target(body) if invocation == "human" else None
        if delegates_to is not None:
            # A delegating wrapper is an entry point a person types that holds no
            # substance of its own. Its completion is its delegate's completion,
            # so restating one here would put the same rule in two places. What it
            # owes instead is that the delegate exists and can be reached.
            wrapper_delegations[name] = (delegates_to, skill_file)
        elif not re.search(r"(?m)^##\s+Completion\s*$", body):
            errors.append(
                {
                    "code": "MISSING_COMPLETION",
                    "message": (
                        f"{skill_file.relative_to(root).as_posix()}: add a '## Completion' "
                        "section stating what the skill leaves behind when it finishes"
                    ),
                }
            )

        harness_file = skill_dir / "agents" / "openai.yaml"
        if not harness_file.is_file():
            errors.append({"code": "HARNESS_METADATA_MISSING", "message": str(harness_file)})
        else:
            harness = harness_file.read_text(encoding="utf-8")
            if not re.search(r"(?m)^\s{2}display_name:\s*\S", harness) or not re.search(
                r"(?m)^\s{2}short_description:\s*\S", harness
            ):
                errors.append({"code": "HARNESS_METADATA_INVALID", "message": str(harness_file)})
            implicit_disabled = bool(
                re.search(
                    r"(?ms)^policy:\s*$.*?^\s{2}allow_implicit_invocation:\s*false\s*$",
                    harness,
                )
            )
            if implicit_disabled != (invocation == "human"):
                errors.append(
                    {
                        "code": "HARNESS_INVOCATION_MISMATCH",
                        "message": f"{name}: catalog={invocation}, implicit disabled={implicit_disabled}",
                    }
                )

        dependency_instructions = _dependency_instructions(skill_dir, body)
        for dependency in entry.get("requiresSkills") or []:
            if isinstance(dependency, str) and not _mentions(dependency_instructions, dependency):
                errors.append(
                    {
                        "code": "DEPENDENCY_NOT_DOCUMENTED",
                        "message": (
                            f"{name}: requiresSkills declares {dependency} but its SKILL.md, "
                            "workflows, and references never name it; document when to invoke "
                            f"{dependency} and what it returns, or drop the dependency"
                        ),
                    }
                )

        for path in _shipped_files(skill_dir):
            content = path.read_text(encoding="utf-8", errors="replace").replace("\\", "/")
            _validate_local_links(root, path, content, errors)
            if name != "setup-rhdh-skills":
                for host_path in HOST_SKILL_PATHS:
                    if host_path in content:
                        errors.append(
                            {
                                "code": "HOST_LAYOUT_LEAK",
                                "message": f"{path.relative_to(root)} contains {host_path}",
                            }
                        )
            for other_name in catalog_names:
                if other_name == name:
                    continue
                cross_path_patterns = (
                    f"../{other_name}/",
                    *(f"skills/{category}/{other_name}/" for category in PROMOTED_CATEGORIES),
                )
                if any(pattern in content for pattern in cross_path_patterns):
                    errors.append(
                        {
                            "code": "CROSS_SKILL_PATH",
                            "message": f"{path.relative_to(root)} references {other_name} by path",
                        }
                    )

    internal_names = set(entry_by_name)
    graph: dict[str, list[str]] = {}
    for name, entry in entry_by_name.items():
        dependencies = entry.get("requiresSkills", [])
        optional_dependencies = entry.get("optionalSkills", [])
        external_dependencies = entry.get("requiresExternalSkills", [])
        if not isinstance(dependencies, list):
            errors.append({"code": "REQUIRES_TYPE", "message": name})
            dependencies = []
        if not isinstance(optional_dependencies, list):
            errors.append({"code": "OPTIONAL_REQUIRES_TYPE", "message": name})
            optional_dependencies = []
        if not isinstance(external_dependencies, list):
            errors.append({"code": "EXTERNAL_REQUIRES_TYPE", "message": name})
            external_dependencies = []
        required_names = [dep for dep in dependencies if isinstance(dep, str)]
        optional_names = [dep for dep in optional_dependencies if isinstance(dep, str)]
        graph[name] = [*required_names, *optional_names]
        for dependency in graph[name]:
            if dependency not in internal_names:
                errors.append({"code": "DEPENDENCY_MISSING", "message": f"{name} -> {dependency}"})
        for dependency in external_dependencies:
            if dependency not in external_set:
                errors.append(
                    {"code": "EXTERNAL_DEPENDENCY_MISSING", "message": f"{name} -> {dependency}"}
                )

    cycle = _find_cycle(graph) if graph else None
    if cycle:
        errors.append({"code": "DEPENDENCY_CYCLE", "message": " -> ".join(cycle)})

    skill_dirs: dict[str, Path] = {}
    for category in PROMOTED_CATEGORIES:
        for skill_file in (root / "skills" / category).glob("*/SKILL.md"):
            skill_dirs[skill_file.parent.name] = skill_file.parent
    for left, right in _duplicate_files(root, skill_dirs):
        errors.append(
            {
                "code": "DUPLICATE_FILE",
                "message": (
                    f"{left} and {right} ship the same content; extract it into a foundation "
                    "skill both invoke by name, or delete the copy and cross the owner's seam"
                ),
            }
        )

    _validate_named_invocations(root, skill_dirs, catalog_names, errors)
    _validate_script_data_files(root, skill_dirs, errors)

    discovered = set(skill_dirs)
    undeclared = sorted(discovered - internal_names)
    missing = sorted(internal_names - discovered)
    if undeclared:
        errors.append({"code": "SKILLS_UNDECLARED", "message": ", ".join(undeclared)})
    if missing:
        errors.append({"code": "SKILLS_NOT_DISCOVERED", "message": ", ".join(missing)})

    legacy = sorted(path.parent.name for path in (root / "skills").glob("*/SKILL.md"))
    if legacy:
        errors.append({"code": "LEGACY_SKILL_LAYOUT", "message": ", ".join(legacy)})

    _validate_internal_skills(root, errors)

    for wrapper, (target, wrapper_file) in sorted(wrapper_delegations.items()):
        location = wrapper_file.relative_to(root).as_posix()
        target_entry = entry_by_name.get(target)
        if target_entry is None:
            errors.append(
                {
                    "code": "WRAPPER_TARGET_MISSING",
                    "message": (
                        f"{location}: delegates to /{target}, which is not a promoted skill. "
                        "A wrapper holds no substance, so a dead delegate leaves it doing nothing"
                    ),
                }
            )
        elif target_entry.get("invocation") != "model":
            errors.append(
                {
                    "code": "WRAPPER_TARGET_NOT_MODEL",
                    "message": (
                        f"{location}: delegates to /{target}, which is human-invoked. "
                        "A wrapper delegates to a model-invoked skill; chaining entry points "
                        "leaves neither one reachable by the router"
                    ),
                }
            )

    return {
        "valid": not errors,
        "errors": errors,
        "promotedSkills": sorted(promoted_names),
        "humanInvokedSkills": sorted(human_names),
        "delegatingWrappers": {name: target for name, (target, _) in wrapper_delegations.items()},
        "requiredExternalSkills": sorted(external_set),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the categorized RHDH skill catalog and dependency graph."
    )
    parser.add_argument("--root", default=".", help="Repository root (default: current directory)")
    parser.add_argument("--json", action="store_true", help="Emit the full JSON report")
    args = parser.parse_args(argv)

    report = validate_repository(Path(args.root))
    if args.json or not sys.stdout.isatty():
        json.dump(report, sys.stdout, indent=2 if args.json else None)
        sys.stdout.write("\n")
    elif report["valid"]:
        print(f"Skill catalog valid: {len(report['promotedSkills'])} promoted skills")
    else:
        print("Skill catalog invalid:", file=sys.stderr)
        for error in report["errors"]:
            print(f"- {error['code']}: {error['message']}", file=sys.stderr)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
