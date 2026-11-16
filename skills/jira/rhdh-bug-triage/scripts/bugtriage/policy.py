"""Surface proven duplicate/fixed recommendations; otherwise abstain silently.

Structural gates cannot establish the truth of a citation. Independent reviewers
must read the artifacts; a score or an assessment boolean is never that proof.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

from .duplicates import DUPLICATE_CLOSE_THRESHOLD, DuplicateCandidate
from .model import DEFAULT_CURRENT_RELEASE, JIRA_KEY_RE, Ticket, parse_datetime

POLICY_VERSION = 2
FIXED_CLOSE_THRESHOLD = 0.80
DISPOSITIONS = {
    "duplicate",
    "already_fixed",
    "still_valid",
    "no_longer_valid",
    "needs_repro",
    "unclear",
}
CLOSE_ACTIONS = {"propose_close_duplicate", "propose_close_fixed"}
EVIDENCE_STRENGTHS = {"direct": 1.0, "strong": 0.8, "supporting": 0.5}
EVIDENCE_TYPES = {"jira", "pr", "commit", "release_note", "code", "doc", "repro", "comment"}
JIRA_BROWSE_URL = "https://redhat.atlassian.net/browse/"
PROOF_FIELDS = {
    "duplicate": ("sameFailure", "sameTrigger", "sameFix", "canonical"),
    "already_fixed": ("fixMatches", "releaseContains", "validation"),
}


@dataclass
class Evidence:
    type: str
    ref: str
    why: str
    strength: str = "supporting"

    def to_dict(self) -> Dict[str, str]:
        return dict(type=self.type, ref=self.ref, why=self.why, strength=self.strength)


@dataclass
class Assessment:
    key: str
    disposition: str = ""
    duplicate_of: str = ""
    evidence: List[Evidence] = field(default_factory=list)
    fix_pr: str = ""
    fix_commit: str = ""
    fix_release: str = ""
    fix_released: bool = False
    fix_merged: bool = False
    fix_covers_whole_issue: bool = False
    fix_review_release: str = ""
    fix_contained_in_review: bool = False
    proof: Dict[str, Any] = field(default_factory=dict)
    repro_result: str = ""
    repro_release: str = ""
    notes: str = ""
    # Legacy free-form drafts are accepted as input, never emitted or trusted.
    comment: str = ""
    recommended_step: str = ""
    follow_up: Dict[str, Any] = field(default_factory=dict)
    independent_passes: int = 0
    agreement: bool = False
    invalid_evidence: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Packet:
    key: str
    summary: str
    status: str
    disposition: str
    confidence: float
    confidence_basis: List[str]
    action: str
    recommended_step: str
    evidence: List[Evidence]
    duplicate_candidates: List[DuplicateCandidate]
    target: str = ""
    explicit_duplicate_link: bool = False
    gaps: List[str] = field(default_factory=list)
    notes: str = ""
    customer_signals: List[str] = field(default_factory=list)
    current_release: str = DEFAULT_CURRENT_RELEASE
    independent_passes: int = 0
    agreement: bool = False
    proposed_comment: str = ""
    verification_errors: List[str] = field(default_factory=list)
    invalid_evidence: List[Dict[str, Any]] = field(default_factory=list)
    policy_version: int = POLICY_VERSION
    comment_plan: Dict[str, Any] = field(default_factory=dict)
    proof: Dict[str, Any] = field(default_factory=dict)
    fix: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "summary": self.summary,
            "status": self.status,
            "disposition": self.disposition,
            "confidence": round(self.confidence, 3),
            "confidenceBasis": self.confidence_basis,
            "action": self.action,
            "recommendedStep": self.recommended_step,
            "target": self.target,
            "explicitDuplicateLink": self.explicit_duplicate_link,
            "evidence": [item.to_dict() for item in self.evidence],
            "duplicateCandidates": [item.to_dict() for item in self.duplicate_candidates],
            "gaps": self.gaps,
            "notes": self.notes,
            "customerSignals": self.customer_signals,
            "currentRelease": self.current_release,
            "review": {"independentPasses": self.independent_passes, "agree": self.agreement},
            "proposedComment": self.proposed_comment,
            "verificationErrors": self.verification_errors,
            "invalidEvidence": self.invalid_evidence,
            "policyVersion": self.policy_version,
            "commentPlan": self.comment_plan,
            "proof": self.proof,
            "fix": self.fix,
        }


def valid_ref(ref: str) -> bool:
    if JIRA_KEY_RE.fullmatch(ref):
        return True
    try:
        url = urlsplit(ref)
        return bool(
            url.scheme == "https"
            and url.hostname
            and not url.username
            and not url.password
            and not re.search(r"[\s<>\[\]()]", ref)
        )
    except ValueError:
        return False


def _evidence_from(item: Any) -> Optional[Evidence]:
    if not isinstance(item, dict):
        return None
    kind = str(item.get("type") or "").strip().lower()
    ref = str(item.get("ref") or "").strip()
    why = str(item.get("why") or "").strip()
    strength = str(item.get("strength") or "supporting").strip().lower()
    if (
        kind not in EVIDENCE_TYPES
        or not valid_ref(ref)
        or not why
        or strength not in EVIDENCE_STRENGTHS
    ):
        return None
    return Evidence(kind, ref, why, strength)


def load_assessment(path: str) -> Assessment:
    with open(path, encoding="utf-8") as handle:
        return parse_assessment(json.load(handle))


def parse_assessment(document: Dict[str, Any]) -> Assessment:
    if not isinstance(document, dict):
        raise ValueError("assessment must be an object")
    key = str(document.get("key") or "").strip()
    if not JIRA_KEY_RE.fullmatch(key):
        raise ValueError("assessment has no valid issue key")
    disposition = str(document.get("disposition") or "").strip().lower()
    if disposition and disposition not in DISPOSITIONS:
        raise ValueError(f"unknown disposition {disposition!r}")
    evidence, invalid = [], []
    for item in document.get("evidence") or []:
        parsed = _evidence_from(item)
        if parsed is None:
            invalid.append(item if isinstance(item, dict) else {"value": str(item)})
        else:
            evidence.append(parsed)
    fix = document.get("fix") if isinstance(document.get("fix"), dict) else {}
    repro = document.get("repro") if isinstance(document.get("repro"), dict) else {}
    review = document.get("review") if isinstance(document.get("review"), dict) else {}
    passes = review.get("independentPasses", 0)
    return Assessment(
        key=key,
        disposition=disposition,
        duplicate_of=str(document.get("duplicateOf") or "").strip(),
        evidence=evidence,
        invalid_evidence=invalid,
        fix_pr=str(fix.get("pr") or "").strip(),
        fix_commit=str(fix.get("commit") or "").strip(),
        fix_release=str(fix.get("release") or "").strip(),
        fix_released=fix.get("released") is True,
        fix_merged=fix.get("merged") is True,
        fix_covers_whole_issue=fix.get("coversWholeIssue") is True,
        fix_review_release=str(fix.get("reviewRelease") or "").strip(),
        fix_contained_in_review=fix.get("containedInReviewRelease") is True,
        proof=document.get("proof") if isinstance(document.get("proof"), dict) else {},
        repro_result=str(repro.get("result") or ""),
        repro_release=str(repro.get("release") or ""),
        notes=str(document.get("notes") or ""),
        comment=str(document.get("comment") or ""),
        recommended_step=str(document.get("recommendedStep") or ""),
        follow_up=document.get("followUp") if isinstance(document.get("followUp"), dict) else {},
        independent_passes=passes if type(passes) is int else 0,
        agreement=review.get("agree") is True,
    )


def evidence_confidence(evidence: Iterable[Evidence]) -> tuple[float, List[str]]:
    items = list(evidence)
    if not items:
        return 0.0, ["no valid evidence"]
    best = max(EVIDENCE_STRENGTHS.get(item.strength, 0.0) for item in items)
    # Two line ranges in the same file are not independent artifacts.
    artifacts = {
        item.ref.split("#", 1)[0] for item in items if item.strength in ("direct", "strong")
    }
    bonus = min(0.08, 0.04 * max(0, len(artifacts) - 1))
    return min(0.98, best + bonus), [
        f"best evidence weight: {best:.2f}",
        "citation-strength score, not a calibrated probability",
    ]


def _release_tuple(value: str):
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", value.strip())
    return tuple(int(part or 0) for part in match.groups()) if match else None


def _jira_ref(ref: str) -> str:
    if JIRA_KEY_RE.fullmatch(ref):
        return ref
    if ref.startswith(JIRA_BROWSE_URL):
        key = urlsplit(ref).path.rsplit("/", 1)[-1]
        return key if JIRA_KEY_RE.fullmatch(key) else ""
    return ""


def ref_link(ref: str, label: str = "") -> str:
    if not ref:
        return ""
    if JIRA_KEY_RE.fullmatch(ref):
        return f"[{label or ref}]({JIRA_BROWSE_URL}{ref})"
    if ref.startswith("https://"):
        tail = ref.rstrip("/").rsplit("/", 1)[-1]
        if not label:
            label = (
                f"PR #{tail}"
                if "/pull/" in ref
                else f"commit {tail[:7]}"
                if "/commit/" in ref
                else ref
            )
        return f"[{label}]({ref})"
    return f"`{ref}`"


def _proof_errors(packet: Packet) -> List[str]:
    errors = []
    cited = {item.ref: item for item in packet.evidence}
    for name in PROOF_FIELDS.get(packet.disposition, ()):
        claim = packet.proof.get(name)
        if (
            not isinstance(claim, dict)
            or not isinstance(claim.get("summary"), str)
            or not claim["summary"].strip()
        ):
            errors.append(f"proof.{name} needs a clear summary and cited references")
            continue
        refs = claim.get("refs")
        if (
            not isinstance(refs, list)
            or not refs
            or any(not isinstance(ref, str) or ref not in cited for ref in refs)
        ):
            errors.append(f"proof.{name} references missing or uncited evidence")
        elif not any(cited[ref].strength == "direct" for ref in refs):
            errors.append(f"proof.{name} lacks direct evidence")
    return errors


def _claim_evidence(packet: Packet, name: str) -> List[Evidence]:
    claim = packet.proof.get(name)
    refs = claim.get("refs", []) if isinstance(claim, dict) else []
    return [
        item
        for item in packet.evidence
        if isinstance(refs, list) and item.ref in refs and item.strength == "direct"
    ]


def verify_packet(packet: Packet, ticket: Ticket) -> List[str]:
    """Independently recheck every structural close gate, including saved fix proof."""
    if packet.action == "abstain":
        return []
    errors = []
    expected = {"duplicate": "propose_close_duplicate", "already_fixed": "propose_close_fixed"}
    if packet.action not in CLOSE_ACTIONS or packet.action != expected.get(packet.disposition):
        return ["only duplicate and already-fixed closure recommendations are supported"]
    if packet.key != ticket.key:
        errors.append("packet does not match the issue under review")
    if _release_tuple(packet.current_release) is None:
        errors.append("release under review is not numerically comparable")
    if ticket.is_done:
        errors.append("ticket is already Done")
    if ticket.customer_signals or packet.customer_signals:
        errors.append("customer-linked ticket cannot receive a close proposal")
    if packet.invalid_evidence:
        errors.append("invalid evidence must be reconciled before a close")
    if not packet.evidence or any(
        _evidence_from(item.to_dict()) is None for item in packet.evidence
    ):
        errors.append("missing or invalid cited evidence")
    if not any(item.strength == "direct" for item in packet.evidence):
        errors.append("close proposal has no direct evidence")
    if packet.independent_passes < 2 or packet.agreement is not True:
        errors.append("close proposal lacks two agreeing independent passes")
    threshold = (
        DUPLICATE_CLOSE_THRESHOLD if packet.disposition == "duplicate" else FIXED_CLOSE_THRESHOLD
    )
    if not math.isfinite(packet.confidence) or not threshold <= packet.confidence <= 0.98:
        errors.append(f"confidence does not meet the {threshold:.2f} close gate")
    errors.extend(_proof_errors(packet))
    if packet.disposition == "duplicate":
        target = next((c for c in packet.duplicate_candidates if c.key == packet.target), None)
        if not JIRA_KEY_RE.fullmatch(packet.target) or packet.target == ticket.key:
            errors.append("duplicate needs one distinct canonical issue")
        if target is None:
            errors.append("canonical issue was not retrieved")
        else:
            source_time, target_time = (
                parse_datetime(ticket.created),
                parse_datetime(target.created),
            )
            if source_time is None or target_time is None or target_time >= source_time:
                errors.append("canonical issue is not demonstrably older; human selection required")
            if target.customer_signals:
                errors.append("customer-linked canonical issue requires separate human review")
            if target.duplicate_of or target.resolution.casefold() == "duplicate":
                errors.append(
                    "canonical issue is itself a duplicate; retrieve the authoritative tracker"
                )
            if not math.isfinite(target.score) or (
                target.score < threshold and not packet.explicit_duplicate_link
            ):
                errors.append("duplicate needs a >=0.85 candidate or an outward Duplicate link")
            if "candidate duplicates this ticket" in target.reasons:
                errors.append("canonical issue duplicates this ticket; reverse closure refused")
        # A flag on a packet cannot manufacture an outward Jira relationship.
        outward = any(
            link.key == packet.target
            and "duplicate" in link.type.lower()
            and link.direction == "outward"
            for link in ticket.links
        )
        if packet.explicit_duplicate_link and not outward:
            errors.append("outward Duplicate link could not be verified")
        if not any(
            item.type == "jira"
            and item.strength == "direct"
            and _jira_ref(item.ref) == packet.target
            for item in packet.evidence
        ):
            errors.append("duplicate close has no direct citation of the canonical issue")
        if not any(
            item.type == "jira" and _jira_ref(item.ref) == packet.target
            for item in _claim_evidence(packet, "canonical")
        ):
            errors.append("canonical selection needs a direct citation of its tracker")
        for claim in ("sameFailure", "sameTrigger"):
            compared = {
                _jira_ref(item.ref)
                for item in _claim_evidence(packet, claim)
                if item.type == "jira"
            }
            if not {ticket.key, packet.target} <= compared:
                errors.append(f"proof.{claim} must directly cite both compared Jira reports")
    else:
        fix = packet.fix
        artifacts = {fix.get("pr"), fix.get("commit")} - {None, ""}
        if not artifacts or not all(
            isinstance(ref, str) and ref.startswith("https://") and valid_ref(ref)
            for ref in artifacts
        ):
            errors.append("fix needs a linked PR or commit")
        if fix.get("merged") is not True:
            errors.append("fix is not confirmed merged/incorporated")
        if fix.get("coversWholeIssue") is not True:
            errors.append("fix does not establish resolution of the whole reported failure")
        if fix.get("released") is not True:
            errors.append("fix is not confirmed released")
        if fix.get("containedInReviewRelease") is not True or _release_tuple(
            str(fix.get("reviewRelease") or "")
        ) != _release_tuple(packet.current_release):
            errors.append("fix inclusion in the exact release under review is unverified")
        release = _release_tuple(str(fix.get("release") or ""))
        current = _release_tuple(packet.current_release)
        if release is None or current is None:
            errors.append("fix/review release is not numerically comparable")
        elif release > current:
            errors.append("fix release is newer than the release under review")
        if not any(
            item.type in ("pr", "commit") and item.ref in artifacts
            for item in _claim_evidence(packet, "fixMatches")
        ):
            errors.append("matching fix needs a direct citation of the named PR or commit")
        if not any(
            item.type == "release_note" for item in _claim_evidence(packet, "releaseContains")
        ):
            errors.append("release inclusion needs direct release evidence")
        if not any(
            item.type in ("pr", "commit", "code", "repro")
            for item in _claim_evidence(packet, "validation")
        ):
            errors.append("validation needs direct regression-test/code or reproduction evidence")
    return errors


def recommendation_comment(packet: Packet, ticket: Ticket) -> str:
    """One deterministic, linked Re / verdict / Recommendation / Proof payload."""
    if packet.action not in CLOSE_ACTIONS:
        return ""
    lines = [f"Re: {ref_link(ticket.key)} — {' '.join(ticket.summary.split())}", ""]
    if packet.disposition == "duplicate":
        lines += [
            f"Duplicate: This issue duplicates {ref_link(packet.target)}.",
            "",
            f"Recommendation: keep {ref_link(packet.target)} as the canonical tracker and close {ref_link(ticket.key)} as its duplicate, subject to human approval.",
        ]
    else:
        artifact = packet.fix.get("pr") or packet.fix.get("commit", "")
        lines += [
            f"Already Fixed: The reported failure is resolved by {ref_link(artifact)}, included in release {packet.fix.get('release', '')}.",
            "",
            f"Recommendation: close {ref_link(ticket.key)} as fixed in {packet.fix.get('release', '')}, subject to human approval.",
        ]
    lines += ["", "Proof:"]
    labels = {
        "sameFailure": "Same failure",
        "sameTrigger": "Same trigger",
        "sameFix": "Same required fix",
        "canonical": "Canonical tracker",
        "fixMatches": "Matching implementation",
        "releaseContains": "Released inclusion",
        "validation": "Validation",
    }
    for name in PROOF_FIELDS[packet.disposition]:
        claim = packet.proof[name]
        summary = " ".join(claim["summary"].split())
        # Claim summaries are plain text; render embedded Jira keys as links too.
        summary = JIRA_KEY_RE.sub(lambda m: ref_link(m.group()), summary)
        lines.append(
            f"- {labels[name]}: {summary} " + "; ".join(ref_link(ref) for ref in claim["refs"])
        )
    lines += [
        "",
        f"Confidence: {packet.confidence:.2f} (evidence-derived policy score; not a probability).",
    ]
    return "\n".join(lines)


def evaluate(
    ticket: Ticket,
    candidates: List[DuplicateCandidate],
    assessment: Optional[Assessment],
    current_release: str = DEFAULT_CURRENT_RELEASE,
) -> Packet:
    disposition = (
        assessment.disposition
        if assessment and assessment.disposition in DISPOSITIONS
        else "unclear"
    )
    evidence = assessment.evidence if assessment else []
    confidence, basis = evidence_confidence(evidence)
    packet = Packet(
        key=ticket.key,
        summary=ticket.summary,
        status=ticket.status,
        disposition=disposition,
        confidence=confidence,
        confidence_basis=basis,
        action="abstain",
        recommended_step="",
        evidence=evidence,
        duplicate_candidates=candidates,
        customer_signals=list(ticket.customer_signals),
        current_release=current_release,
    )
    if assessment is None or not assessment.disposition:
        packet.gaps.append("no adjudication supplied; left unchanged")
        return packet
    packet.notes = assessment.notes
    packet.proof = assessment.proof
    packet.invalid_evidence = assessment.invalid_evidence
    packet.independent_passes, packet.agreement = (
        assessment.independent_passes,
        assessment.agreement,
    )
    if assessment.key != ticket.key:
        packet.gaps.append("assessment does not match the issue under review")
        return packet
    if disposition not in PROOF_FIELDS:
        packet.gaps.append("outside duplicate/already-fixed recommendation scope; left unchanged")
        return packet
    if disposition == "duplicate":
        packet.target = assessment.duplicate_of
        packet.explicit_duplicate_link = any(
            link.key == packet.target
            and "duplicate" in link.type.lower()
            and link.direction == "outward"
            for link in ticket.links
        )
        target = next((c for c in candidates if c.key == packet.target), None)
        match = max(
            target.score if target else 0.0, 0.90 if packet.explicit_duplicate_link else 0.0
        )
        packet.confidence = min(confidence, match)
        packet.action = "propose_close_duplicate"
        packet.recommended_step = f"Close as duplicate of {packet.target}."
    else:
        packet.fix = dict(
            pr=assessment.fix_pr,
            commit=assessment.fix_commit,
            release=assessment.fix_release,
            released=assessment.fix_released,
            merged=assessment.fix_merged,
            coversWholeIssue=assessment.fix_covers_whole_issue,
            reviewRelease=assessment.fix_review_release,
            containedInReviewRelease=assessment.fix_contained_in_review,
        )
        packet.action = "propose_close_fixed"
        packet.recommended_step = f"Close as fixed in {assessment.fix_release}."
    packet.verification_errors = verify_packet(packet, ticket)
    if packet.verification_errors:
        packet.gaps.extend(packet.verification_errors)
        packet.action, packet.recommended_step = "abstain", ""
    else:
        packet.proposed_comment = recommendation_comment(packet, ticket)
    return packet


def summarize_actions(packets: Iterable[Packet]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for packet in packets:
        counts[packet.action] = counts.get(packet.action, 0) + 1
    return dict(sorted(counts.items()))


def summarize_dispositions(packets: Iterable[Packet]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for packet in packets:
        counts[packet.disposition] = counts.get(packet.disposition, 0) + 1
    return dict(sorted(counts.items()))
