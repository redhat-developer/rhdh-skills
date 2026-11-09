"""Deterministic duplicate candidate generation and lexical scoring.

This is the retrieval half of the hybrid duplicate check. It never declares a
duplicate on its own: it ranks candidates and explains the score, and the
assessment plus policy decide whether the evidence is strong enough to propose a
close. The agent is expected to read the top candidates and adjudicate meaning;
the score is the auditable floor, not the verdict.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence, Set

from .model import Ticket

DUPLICATE_CLOSE_THRESHOLD = 0.85
DUPLICATE_HINT_THRESHOLD = 0.70
MIN_CANDIDATE_SCORE = 0.35

STOPWORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "but",
    "by",
    "can",
    "cannot",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "done",
    "for",
    "from",
    "get",
    "gets",
    "getting",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "him",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "like",
    "may",
    "me",
    "might",
    "more",
    "most",
    "must",
    "my",
    "no",
    "not",
    "now",
    "of",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "out",
    "over",
    "own",
    "same",
    "she",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
}

ERROR_MARKERS = (
    "error",
    "exception",
    "traceback",
    "failed",
    "failure",
    "fails",
    "panic",
    "segfault",
    "timeout",
    "timed out",
    "refused",
    "denied",
    "not found",
    "unable",
    "cannot",
    "crash",
    "warning",
    "cve-",
)

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.@/:-]*[a-z0-9]|[a-z0-9]", re.IGNORECASE)
QUOTED_RE = re.compile(r"[\"'`]([^\"'`]{3,80})[\"'`]")
IDENTIFIER_RE = re.compile(r"\b(?:[A-Za-z][\w.-]*/)?[A-Za-z][\w.-]*@?[\w./-]*\b")


def normalize_token(token: str) -> str:
    token = token.strip(".,;:()[]{}<>!?\"'`").lower()
    if token.endswith("'s"):
        token = token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "is", "us")):
        token = token[:-1]
    return token


def tokenize(text: str) -> Set[str]:
    if not text:
        return set()
    tokens = set()
    for raw in TOKEN_RE.findall(text):
        token = normalize_token(raw)
        if len(token) < 3 or token in STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def jaccard(left: Set[str], right: Set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def containment(left: Set[str], right: Set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def extract_signatures(text: str) -> Set[str]:
    """Return tokens from error-bearing lines plus quoted strings.

    A stack trace, exception name, HTTP status, CVE id, or quoted error is the
    strongest affordable duplicate signal in a bug report. Keeping only those
    tokens stops ordinary prose from inflating the score.
    """
    signatures: Set[str] = set()
    for line in text.splitlines():
        lowered = line.lower()
        marker = any(term in lowered for term in ERROR_MARKERS)
        has_specific = bool(re.search(r"\d{3,}|[A-Z][a-z]+(?:Error|Exception)|/", line))
        if not (marker or has_specific):
            continue
        for raw in TOKEN_RE.findall(line):
            token = normalize_token(raw)
            if len(token) >= 3 and token not in STOPWORDS:
                signatures.add(token)
    for quoted in QUOTED_RE.findall(text):
        for raw in TOKEN_RE.findall(quoted):
            token = normalize_token(raw)
            if len(token) >= 3 and token not in STOPWORDS:
                signatures.add(token)
    return signatures


def _link_relationship(query: Ticket, candidate: Ticket) -> str:
    """Describe the Jira link between the query and a candidate.

    ``duplicate`` means the query carries an outward Duplicate link to the
    candidate, so the query is the duplicate. ``reverse-duplicate`` means the
    candidate duplicates the query, so the query is the canonical report.
    """
    for link in query.links:
        if link.key != candidate.key:
            continue
        if "duplicate" in link.type.lower():
            return "duplicate" if link.direction == "outward" else "reverse-duplicate"
        return "related"
    for link in candidate.links:
        if link.key != query.key:
            continue
        if "duplicate" in link.type.lower() and link.direction == "outward":
            return "reverse-duplicate"
        return "related"
    return ""


def _same_reporter(left: Ticket, right: Ticket) -> bool:
    return bool(left.reporter and right.reporter and left.reporter == right.reporter)


def _same_team(left: Ticket, right: Ticket) -> bool:
    return bool(left.team and right.team and left.team == right.team)


@dataclass
class DuplicateCandidate:
    key: str
    summary: str
    status: str
    score: float
    components: List[str] = field(default_factory=list)
    signals: dict = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "summary": self.summary,
            "status": self.status,
            "score": round(self.score, 3),
            "components": self.components,
            "signals": {name: round(value, 3) for name, value in self.signals.items()},
            "reasons": self.reasons,
        }


def score_candidate(query: Ticket, candidate: Ticket) -> DuplicateCandidate:
    query_summary = tokenize(query.summary)
    candidate_summary = tokenize(candidate.summary)
    query_description = tokenize(query.description)
    candidate_description = tokenize(candidate.description)
    query_signatures = extract_signatures(query.search_text)
    candidate_signatures = extract_signatures(candidate.search_text)

    signals = {
        "summaryJaccard": jaccard(query_summary, candidate_summary),
        "summaryContainment": containment(query_summary, candidate_summary),
        "descriptionJaccard": jaccard(query_description, candidate_description),
        "signatureJaccard": jaccard(query_signatures, candidate_signatures),
        "componentJaccard": jaccard(set(query.components), set(candidate.components)),
    }

    # Renormalize over the signals both tickets can supply. A missing description
    # should weaken the evidence, not manufacture a low score for a real match.
    weights = {
        "summaryJaccard": 0.30,
        "summaryContainment": 0.15,
        "descriptionJaccard": 0.20,
        "signatureJaccard": 0.25,
        "componentJaccard": 0.10,
    }
    available = {
        "summaryJaccard": bool(query_summary and candidate_summary),
        "summaryContainment": bool(query_summary and candidate_summary),
        "descriptionJaccard": bool(query_description and candidate_description),
        "signatureJaccard": bool(query_signatures and candidate_signatures),
        "componentJaccard": bool(query.components and candidate.components),
    }
    total_weight = sum(weight for name, weight in weights.items() if available[name])
    if total_weight:
        score = (
            sum(signals[name] * weight for name, weight in weights.items() if available[name])
            / total_weight
        )
    else:
        score = 0.0

    reasons = []
    if signals["summaryJaccard"] >= 0.5:
        reasons.append("summary shares most content words")
    if signals["signatureJaccard"] >= 0.5:
        reasons.append("error signatures overlap")
    if signals["componentJaccard"] >= 0.5:
        reasons.append("same component")
    relationship = _link_relationship(query, candidate)
    if relationship == "duplicate":
        score += 0.10
        reasons.append("outward Duplicate link")
    elif relationship == "reverse-duplicate":
        # The candidate is the duplicate and the query is the canonical report.
        # Keep the pair visible for a human, but never let this path reach the
        # close floor: closing the canonical ticket would be backwards.
        score = min(score, DUPLICATE_CLOSE_THRESHOLD - 0.01)
        reasons.append("candidate duplicates this ticket")
    elif relationship == "related":
        score += 0.02
        reasons.append("linked issue")
    if _same_reporter(query, candidate):
        score += 0.03
        reasons.append("same reporter")
    if _same_team(query, candidate):
        score += 0.02
        reasons.append("same team")
    if not reasons:
        reasons.append("lexical similarity only")

    return DuplicateCandidate(
        key=candidate.key,
        summary=candidate.summary,
        status=candidate.status,
        score=min(0.99, max(0.0, score)),
        components=list(candidate.components),
        signals=signals,
        reasons=reasons,
    )


def rank_candidates(
    query: Ticket,
    corpus: Iterable[Ticket],
    limit: int = 3,
    min_score: float = MIN_CANDIDATE_SCORE,
) -> List[DuplicateCandidate]:
    scored = []
    for candidate in corpus:
        if candidate.key == query.key:
            continue
        result = score_candidate(query, candidate)
        if result.score >= min_score:
            scored.append(result)
    scored.sort(key=lambda item: (-item.score, item.key))
    return scored[:limit]


def distinctive_phrases(ticket: Ticket, limit: int = 3) -> List[str]:
    """Return JQL-friendly phrases for a broader live search.

    The first phrase prefers a quoted error from the report; the rest use the
    most distinctive summary tokens. Each phrase is OR-joined by the caller, so
    precision matters more than recall here — the deterministic scorer reranks
    whatever the search returns.
    """
    phrases: List[str] = []
    quoted = [value.strip() for value in QUOTED_RE.findall(ticket.summary) if value.strip()]
    for value in quoted:
        words = [part for part in re.split(r"\W+", value) if len(part) >= 3]
        if len(words) >= 2:
            phrases.append(" ".join(words[:6]))
    identifiers = [
        token
        for token in IDENTIFIER_RE.findall(ticket.summary)
        if any(char.isdigit() for char in token) or "/" in token or "@" in token
    ]
    for value in identifiers:
        if value not in phrases:
            phrases.append(value)
    summary_tokens = sorted(
        tokenize(ticket.summary),
        key=lambda token: (-len(token), token),
    )
    for token in summary_tokens:
        if token in {part.lower() for phrase in phrases for part in phrase.split()}:
            continue
        phrases.append(token)
        if len(phrases) >= limit:
            break
    return phrases[:limit]


def candidate_threshold(score: float) -> str:
    if score >= DUPLICATE_CLOSE_THRESHOLD:
        return "propose-close-eligible"
    if score >= DUPLICATE_HINT_THRESHOLD:
        return "comment-only"
    return "below-threshold"


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Kept for callers that swap in vector scores; no dependency is required."""
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)
