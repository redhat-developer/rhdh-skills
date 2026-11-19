"""Independent, bounded lead generation. Nothing in this module proves a verdict."""

from __future__ import annotations

import re
from typing import Iterable

from .duplicates import QUOTED_RE, rank_candidates, score_candidate
from .jira import JiraAdapterError, hydrate_acli, search_acli
from .model import JIRA_KEY_RE, Ticket, normalize_issue, parse_datetime

PASSES = (
    "link_graph",
    "burst",
    "open_corpus",
    "closed_corpus",
    "comments",
    "defect_search",
    "fix_first",
)
SIGNALS = {
    "fix_claim": r"\b(?:fixed|resolved|merged|fix being handled)\b",
    "uncertain_claim": r"\b(?:should|seems?|believe|potentially)\b",
    "negative_or_followup": r"\b(?:not fixed|unmerged|still|however|cannot reproduce|can not reproduce|could not reproduce|work.?around|retest)\b",
}


def query_plan(ticket: Ticket) -> list[dict]:
    """Search keys separately: aliases and mentioned trackers are different concepts."""
    keys = sorted(
        {
            ticket.key,
            *ticket.former_keys,
            *JIRA_KEY_RE.findall(ticket.search_text),
            *[link.key for link in ticket.links],
        }
    )
    # Scoring signatures contain ordinary words from error-bearing lines. They
    # are not suitable independent live queries ("each", "additional", "403").
    report = ticket.summary + "\n" + ticket.description
    phrases = [
        value.strip()
        for value in QUOTED_RE.findall(report)
        if len(value.split()) >= 2 or re.search(r"[._/]", value)
    ]
    phrases += re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)\b|\b[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+\b|\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b",
        report,
    )
    phrases = [
        phrase
        for phrase in phrases
        if not re.search(
            r"https?://|drive.google|docs.redhat|\.com\b|\.png\b|\.mov\b", phrase, re.I
        )
    ]
    title = re.sub(r"\[[^]]+\]", " ", ticket.summary)
    phrases.append(" ".join(title.split()[:12]))
    terms = [(ticket.key, "key")]
    seen = set(keys)
    for phrase in phrases:
        phrase = phrase.strip()
        if phrase and phrase not in seen:
            terms.append((phrase, "signature"))
            seen.add(phrase)
    # Keep individually searched aliases/pointers visible without starving every
    # content query on heavily linked reports. Budget overflow remains explicit.
    terms = terms[:2] + [(key, "key") for key in keys if key != ticket.key] + terms[2:]
    return [
        {
            "term": term,
            "kind": kind,
            "jql": 'project in (RHDHBUGS, RHIDP) AND text ~ "\\"'
            + term.replace("\\", "\\\\").replace('"', '\\"')
            + '\\""',
            "outcome": "not_run",
        }
        for term, kind in terms
    ]


def discover(
    ticket: Ticket,
    backlog: Iterable[Ticket],
    *,
    live: bool = False,
    max_queries: int = 4,
    query_limit: int = 20,
    hydrate_limit: int = 10,
    field_names: dict | None = None,
) -> dict:
    """Run every local route even if another route found a strong-looking lead.

    Live search is opt-in. Limits bound calls, not conclusions; skipped work and
    partial reads remain visible. Candidate exports are private, not postable.
    """
    if max_queries < 0 or query_limit < 1 or hydrate_limit < 0:
        raise ValueError("discovery limits must be nonnegative; query limit must be positive")
    backlog = list(backlog)
    by_key = {item.key: item for item in backlog}
    by_key[ticket.key] = ticket
    leads: dict[str, dict] = {}
    signals = []
    gaps = list(ticket.read_gaps)

    def add(key, route, why, source="", direction=""):
        if key == ticket.key or key in ticket.former_keys:
            return
        candidate = by_key.get(key)
        # Verified alias identity is not a redundant tracker.
        if candidate and (
            {candidate.key, *candidate.former_keys} & {ticket.key, *ticket.former_keys}
        ):
            return
        lead = leads.setdefault(
            key, {"key": key, "foundBy": [], "reasons": [], "available": candidate is not None}
        )
        if route not in lead["foundBy"]:
            lead["foundBy"].append(route)
        reason = {"pass": route, "why": why, "source": source, "direction": direction}
        if reason not in lead["reasons"]:
            lead["reasons"].append(reason)

    # Bounded duplicate graph traversal; related links expand only at the seed.
    frontier, visited = {ticket.key}, set()
    for depth in range(3):
        following = set()
        for key in sorted(frontier - visited):
            visited.add(key)
            node = by_key.get(key)
            if node is None:
                continue
            edges = [(link.key, link.type, link.direction) for link in node.links]
            edges += [
                (other.key, link.type, "reverse:" + link.direction)
                for other in backlog
                for link in other.links
                if link.key == key
            ]
            for target, kind, direction in edges:
                duplicate = "duplicate" in kind.lower()
                if depth == 0 or duplicate:
                    add(
                        target,
                        "link_graph",
                        f"{kind} edge at depth {depth + 1}; link direction is not canonical proof",
                        key,
                        direction,
                    )
                    if duplicate:
                        following.add(target)
        frontier = following
    if frontier - visited:
        gaps.append("duplicate graph depth limit reached; remaining trackers require inspection")

    created = parse_datetime(ticket.created)
    for other in backlog:
        when = parse_datetime(other.created)
        if other.key == ticket.key or not created or not when:
            continue
        if abs((created - when).total_seconds()) <= 3600:
            scored = score_candidate(ticket, other)
            if max(scored.signals["summaryJaccard"], scored.signals["descriptionJaccard"]) >= 0.45:
                add(
                    other.key,
                    "burst",
                    "reports created within one hour with overlapping report content; not duplicate proof",
                    ticket.key,
                )

    for done, route in [(False, "open_corpus"), (True, "closed_corpus")]:
        for candidate in rank_candidates(
            ticket, [item for item in backlog if item.is_done == done], limit=10
        ):
            add(
                candidate.key,
                route,
                f"lexical/signature rank score {candidate.score:.3f}; not evidence confidence",
                ticket.key,
            )

    # Read seed comments and all currently found partners; retain contradictory
    # claims and pointers instead of choosing the most optimistic comment.
    comment_partners = [
        by_key[key]
        for key in sorted(leads)
        if key in by_key and "link_graph" in leads[key]["foundBy"]
    ]
    for node in [ticket, *comment_partners]:
        for comment in node.comments:
            kinds = [
                name for name, pattern in SIGNALS.items() if re.search(pattern, comment.body, re.I)
            ]
            refs = sorted(set(JIRA_KEY_RE.findall(comment.body)))
            if kinds or refs:
                signals.append(
                    {
                        "source": node.key,
                        "commentId": comment.id,
                        "kinds": kinds,
                        "mentionedKeys": refs,
                        "excerpt": " ".join(comment.body.split())[:300],
                    }
                )
                if kinds and node.key != ticket.key:
                    add(
                        node.key,
                        "comments",
                        "partner comment contains fix/uncertainty/follow-up signal; inspect full comment",
                        node.key + "#comment-" + comment.id,
                    )
                for key in refs:
                    add(
                        key,
                        "comments",
                        "comment pointer; relationship and fix coverage unverified",
                        node.key + "#comment-" + comment.id,
                    )

    queries = query_plan(ticket)
    candidate_records = {}
    full_reads = 0
    attempted = 0
    for query in queries:
        query["reason"] = "live Jira search disabled" if not live else "query budget exhausted"
        if not live or attempted >= max_queries:
            continue
        attempted += 1
        query.pop("reason")
        try:
            hits = search_acli(query["jql"], limit=query_limit)
        except JiraAdapterError as error:
            query.update(outcome="failed", error=str(error))
            continue
        query.update(
            outcome="capped" if len(hits) >= query_limit else "returned" if hits else "empty",
            returned=len(hits),
            limit=query_limit,
            keys=[hit["key"] for hit in hits],
        )
        for hit in hits:
            key = hit["key"]
            if key == ticket.key or key in ticket.former_keys:
                continue
            if key not in by_key:
                if full_reads >= hydrate_limit:
                    gaps.append(f"full-read budget exhausted: {key}")
                else:
                    full_reads += 1
                    try:
                        record = hydrate_acli(hit, field_names)
                        by_key[key] = normalize_issue(record, field_names)
                        candidate_records[key] = record
                    except (JiraAdapterError, ValueError) as error:
                        gaps.append(f"full read failed for {key}: {error}")
            add(
                key,
                "defect_search",
                "separately executed Jira text query; search hit is not a match verdict",
                query["jql"],
            )

    # Fix -> report direction, even if a link/lexical route already found it.
    for fixed in backlog:
        if (
            fixed.key == ticket.key
            or not fixed.is_done
            or not (fixed.fix_versions and fixed.pr_urls)
        ):
            continue
        scored = score_candidate(ticket, fixed)
        if (
            scored.signals["summaryJaccard"] >= 0.3
            or any(link.key == ticket.key for link in fixed.links)
            or any(link.key == fixed.key for link in ticket.links)
        ):
            add(
                fixed.key,
                "fix_first",
                "closed versioned tracker with a PR overlaps this open report; merge, scope and released inclusion unverified",
                fixed.key,
            )

    for key, lead in leads.items():
        other = by_key.get(key)
        if not other:
            gaps.append(f"candidate full record unavailable: {key}")
            continue
        lead.update(
            available=True,
            created=other.created,
            status=other.status,
            resolution=other.resolution,
            customerSignals=other.customer_signals,
            fixVersions=other.fix_versions,
            prUrls=other.pr_urls,
        )
        if created and parse_datetime(other.created) and parse_datetime(other.created) >= created:
            lead.setdefault("warnings", []).append(
                "candidate is not older; do not infer canonical direction"
            )
        if any(
            link.key == ticket.key
            and "duplicate" in link.type.lower()
            and link.direction == "outward"
            for link in other.links
        ):
            lead.setdefault("warnings", []).append(
                "candidate points back as a duplicate; reconcile direction/chain"
            )
    return {
        "key": ticket.key,
        "passesRun": list(PASSES),
        "liveSearch": live,
        "leads": [leads[key] for key in sorted(leads)],
        "commentSignals": signals,
        "queries": queries,
        "candidateRecords": list(candidate_records.values()),
        "gaps": sorted(set(gaps)),
        "corpusExhaustive": False,
        "limits": {
            "graphDepth": 3,
            "burstSeconds": 3600,
            "rankedPerPartition": 10,
            "maxQueries": max_queries,
            "queryLimit": query_limit,
            "hydrateLimit": hydrate_limit,
        },
    }
