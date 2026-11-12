"""Evidence-first disposition policy.

The model does not get to assert a confidence number. It supplies claims with
citations; this module grades the evidence, applies the close thresholds, and
downgrades anything that fails the gate. Every close proposal must survive three
checks: a direct citation, a reviewed second pass, and a non-customer ticket.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .duplicates import DUPLICATE_CLOSE_THRESHOLD, DuplicateCandidate
from .model import DEFAULT_CURRENT_RELEASE, JIRA_KEY_RE, Ticket

POLICY_VERSION = 1

FIXED_CLOSE_THRESHOLD = 0.80
OBSOLETE_CLOSE_THRESHOLD = 0.80
COMMENT_THRESHOLD = 0.60

DISPOSITIONS = {
    "duplicate",
    "already_fixed",
    "still_valid",
    "no_longer_valid",
    "needs_repro",
    "unclear",
}

CLOSE_ACTIONS = {
    "propose_close_duplicate",
    "propose_close_fixed",
    "propose_close_obsolete",
}

EVIDENCE_STRENGTHS = {"direct": 1.0, "strong": 0.8, "supporting": 0.5}
EVIDENCE_TYPES = {
    "jira",
    "pr",
    "commit",
    "release_note",
    "code",
    "doc",
    "repro",
    "comment",
}
DIRECT_EVIDENCE_TYPES = {"jira", "pr", "commit", "release_note", "code", "doc", "repro"}


@dataclass
class Evidence:
    type: str
    ref: str
    why: str
    strength: str = "supporting"

    def to_dict(self) -> Dict[str, str]:
        return {
            "type": self.type,
            "ref": self.ref,
            "why": self.why,
            "strength": self.strength,
        }


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
    repro_result: str = ""
    repro_release: str = ""
    notes: str = ""
    comment: str = ""
    independent_passes: int = 0
    agreement: bool = False
    invalid_evidence: List[Dict[str, str]] = field(default_factory=list)


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
    invalid_evidence: List[Dict[str, str]] = field(default_factory=list)
    policy_version: int = POLICY_VERSION

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
            "review": {
                "independentPasses": self.independent_passes,
                "agree": self.agreement,
            },
            "proposedComment": self.proposed_comment,
            "verificationErrors": self.verification_errors,
            "invalidEvidence": self.invalid_evidence,
            "policyVersion": self.policy_version,
        }


def _evidence_from(item: Any) -> Optional[Evidence]:
    if not isinstance(item, dict):
        return None
    evidence_type = str(item.get("type") or "").strip().lower()
    ref = str(item.get("ref") or "").strip()
    why = str(item.get("why") or "").strip()
    strength = str(item.get("strength") or "supporting").strip().lower()
    if evidence_type not in EVIDENCE_TYPES or not ref or not why:
        return None
    if strength not in EVIDENCE_STRENGTHS:
        return None
    return Evidence(type=evidence_type, ref=ref, why=why, strength=strength)


def load_assessment(path: str) -> Assessment:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    return parse_assessment(document)


def parse_assessment(document: Dict[str, Any]) -> Assessment:
    if not isinstance(document, dict):
        raise ValueError("assessment must be an object")
    key = str(document.get("key") or "").strip()
    if not key:
        raise ValueError("assessment has no key")
    evidence: List[Evidence] = []
    invalid: List[Dict[str, str]] = []
    for item in document.get("evidence") or []:
        parsed = _evidence_from(item)
        if parsed is None:
            invalid.append(item if isinstance(item, dict) else {"value": str(item)})
            continue
        evidence.append(parsed)
    fix = document.get("fix") if isinstance(document.get("fix"), dict) else {}
    repro = document.get("repro") if isinstance(document.get("repro"), dict) else {}
    review = document.get("review") if isinstance(document.get("review"), dict) else {}
    passes = review.get("independentPasses", document.get("independentPasses", 0))
    try:
        independent_passes = int(passes)
    except (TypeError, ValueError):
        independent_passes = 0
    return Assessment(
        key=key,
        disposition=str(document.get("disposition") or "").strip().lower(),
        duplicate_of=str(document.get("duplicateOf") or "").strip(),
        evidence=evidence,
        fix_pr=str(fix.get("pr") or "").strip(),
        fix_commit=str(fix.get("commit") or "").strip(),
        fix_release=str(fix.get("release") or "").strip(),
        fix_released=bool(fix.get("released")),
        repro_result=str(repro.get("result") or "").strip().lower(),
        repro_release=str(repro.get("release") or "").strip(),
        notes=str(document.get("notes") or "").strip(),
        comment=str(document.get("comment") or "").strip(),
        independent_passes=independent_passes,
        agreement=bool(review.get("agree", document.get("agree", False))),
        invalid_evidence=invalid,
    )


def evidence_confidence(evidence: Iterable[Evidence]) -> tuple[float, List[str]]:
    items = list(evidence)
    if not items:
        return 0.0, ["no valid evidence"]
    best = max(EVIDENCE_STRENGTHS[item.strength] for item in items)
    independent = {item.ref for item in items if item.strength in ("direct", "strong")}
    bonus = min(0.08, 0.04 * max(0, len(independent) - 1))
    basis = [
        f"best evidence: {max(items, key=lambda item: EVIDENCE_STRENGTHS[item.strength]).strength}"
    ]
    if len(independent) > 1:
        basis.append(f"{len(independent)} independent strong/direct citations")
    return min(0.98, best + bonus), basis


def _reviewed(passes: int, agree: bool) -> bool:
    return passes >= 2 and agree


def _release_tuple(value: str):
    """Plain numeric release tuple, or None when the string is not a version."""
    match = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", value.strip())
    if match is None:
        return None
    return tuple(int(part or 0) for part in match.groups())


def _release_after(release: str, base: str) -> bool:
    """True only when ``release`` parses and is strictly newer than ``base``.

    Unparsable strings return False: this guard can only prove that a fix is
    absent from the release under review, never that it is present. Presence
    stays a supplied claim, so independent release verification is a separate
    step.
    """
    left = _release_tuple(release)
    right = _release_tuple(base)
    if left is None or right is None:
        return False
    return left > right


def _close_gate(
    ticket: Ticket,
    confidence: float,
    threshold: float,
    evidence: List[Evidence],
    passes: int,
    agree: bool,
) -> tuple[bool, List[str]]:
    reasons = []
    if ticket.customer_signals:
        reasons.append("customer-linked ticket; close is never proposed")
    if confidence < threshold:
        reasons.append(f"confidence {confidence:.2f} below {threshold:.2f}")
    if not any(item.strength == "direct" for item in evidence):
        reasons.append("no direct evidence")
    if not _reviewed(passes, agree):
        reasons.append("second independent pass missing or disagreed")
    return (not reasons, reasons)


JIRA_BROWSE_URL = "https://redhat.atlassian.net/browse/"


def ref_link(ref: str, label: str = "") -> str:
    """Render a citation as a terse Markdown link when it points somewhere."""
    value = (ref or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return f"[{label or _link_label(value)}]({value})"
    if JIRA_KEY_RE.fullmatch(value):
        return f"[{value}]({JIRA_BROWSE_URL}{value})"
    return f"`{value}`"


def _link_label(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    if "/pull/" in url:
        return f"PR #{tail}"
    if "/merge_requests/" in url:
        return f"MR !{tail}"
    if "/releases/tag/" in url:
        return url.split("/releases/tag/", 1)[1].strip("/") or "release"
    if "/commit/" in url:
        return f"commit {tail[:7]}"
    return url


def _first_why(assessment: Assessment, limit: int = 220) -> str:
    for item in assessment.evidence:
        why = " ".join(item.why.split())
        if not why:
            continue
        if len(why) <= limit:
            return why
        return why[: limit - 1].rstrip() + "\u2026"
    return ""


def _evidence_line(assessment: Assessment, limit: int = 2) -> str:
    links = []
    seen = set()
    for item in assessment.evidence:
        link = ref_link(item.ref)
        if not link or link in seen:
            continue
        seen.add(link)
        links.append(link)
        if len(links) >= limit:
            break
    return "; ".join(links)


def _duplicate_comment(
    ticket: Ticket, assessment: Assessment, candidate: Optional[DuplicateCandidate]
) -> str:
    target = ref_link(assessment.duplicate_of)
    lines = [f"Closing as a duplicate of {target}."]
    why = _first_why(assessment)
    if why:
        lines.extend(["", why])
    lines.extend(["", "Reopen with a distinct error signature if this is a different failure."])
    return "\n".join(lines)


def _duplicate_hint_comment(
    ticket: Ticket, assessment: Assessment, candidate: Optional[DuplicateCandidate]
) -> str:
    target = ref_link(assessment.duplicate_of)
    lines = [f"Possible duplicate of {target}. This is a triage hint, not a close proposal."]
    why = _first_why(assessment)
    if why:
        lines.extend(["", why])
    if candidate:
        lines.extend(
            [
                "",
                f"Match score {candidate.score:.2f}, below the "
                f"{DUPLICATE_CLOSE_THRESHOLD:.2f} close floor.",
            ]
        )
    lines.extend(["", "Confirm the match before linking or closing."])
    return "\n".join(lines)


def _release_link(assessment: Assessment) -> str:
    """Prefer a linked release note; fall back to the release name."""
    for item in assessment.evidence:
        if item.type == "release_note" and item.ref:
            return ref_link(item.ref, f"{assessment.fix_release or 'release'} note")
    return assessment.fix_release


def _fixed_comment(ticket: Ticket, assessment: Assessment) -> str:
    artifact = ref_link(assessment.fix_pr or assessment.fix_commit)
    release = _release_link(assessment)
    opening = f"Fixed by {artifact}" if artifact else "The reported behavior is fixed"
    if release:
        opening += f" and included in {release}"
    lines = [opening + ". Closing as fixed."]
    lines.extend(["", "Reopen with a current-release reproduction if it recurs."])
    return "\n".join(lines)


def _obsolete_comment(ticket: Ticket, assessment: Assessment) -> str:
    why = _first_why(assessment)
    link = _evidence_line(assessment, limit=1)
    opening = "This behavior no longer applies"
    if why:
        opening += f": {why}"
    lines = [opening + "."]
    if link:
        lines.extend(["", f"Evidence: {link}."])
    lines.extend(
        ["", "Closing as no longer valid. Reopen with a current reproduction if it returns."]
    )
    return "\n".join(lines)


def _obsolete_hint_comment(ticket: Ticket, assessment: Assessment) -> str:
    why = _first_why(assessment)
    link = _evidence_line(assessment, limit=1)
    lines = [
        "Possible no-longer-valid report. The evidence does not meet the close floor, "
        "so this is a comment only."
    ]
    if why:
        lines.extend(["", why])
    if link:
        lines.extend(["", f"Evidence: {link}."])
    lines.extend(["", "Confirm the removal or failed reproduction before closing."])
    return "\n".join(lines)


def _needs_repro_comment(ticket: Ticket, current_release: str) -> str:
    return (
        f"This report does not contain enough information to confirm whether it still "
        f"occurs on {current_release}. Please add:\n"
        "- the exact RHDH version and installation method\n"
        "- minimal reproduction steps and the full error text\n\n"
        "Recommendation: keep this open until we can reproduce it or confirm it is gone."
    )


def _unclear_comment(ticket: Ticket, assessment: Assessment, current_release: str) -> str:
    """A comment for an abstention, so every triaged ticket leaves a trace."""
    lines = [f"Re-checked against {current_release}; we could not reach a confident disposition."]
    why = _first_why(assessment)
    if why:
        lines.extend(["", why])
    link = _evidence_line(assessment, limit=2)
    if link:
        lines.extend(["", f"Evidence: {link}."])
    lines.extend(["", "Recommendation: keep open and add a current-release reproduction."])
    return "\n".join(lines)


def _still_valid_comment(ticket: Ticket, assessment: Assessment, current_release: str) -> str:
    release = assessment.repro_release or current_release
    why = _first_why(assessment)
    if why:
        lines = [f"Still reproducible on {release}: {why}"]
    else:
        lines = [f"Still reproducible on {release}."]
    link = _evidence_line(assessment, limit=2)
    if link:
        lines.extend(["", f"Evidence: {link}."])
    lines.extend(["", "Recommendation: keep this open for the owning team; no close is proposed."])
    return "\n".join(lines)


def _duplicate_support(
    query: Ticket, assessment: Assessment, candidates: List[DuplicateCandidate]
) -> tuple[Optional[DuplicateCandidate], bool]:
    candidate = next((item for item in candidates if item.key == assessment.duplicate_of), None)
    # Jira's Duplicate link is directional: outward is "duplicates" (this ticket
    # is the duplicate), inward is "is duplicated by" (the linked ticket is the
    # duplicate, so this one is the canonical report). Only an outward link
    # supports closing the queried ticket. An unknown direction fails closed.
    explicit_link = any(
        link.key == assessment.duplicate_of
        and "duplicate" in link.type.lower()
        and link.direction == "outward"
        for link in query.links
    )
    return candidate, explicit_link


def evaluate(
    ticket: Ticket,
    candidates: List[DuplicateCandidate],
    assessment: Optional[Assessment],
    current_release: str = DEFAULT_CURRENT_RELEASE,
) -> Packet:
    """Turn a ticket, candidates, and an optional assessment into one packet."""
    if assessment is None or not assessment.disposition:
        return Packet(
            key=ticket.key,
            summary=ticket.summary,
            status=ticket.status,
            disposition="unclear",
            confidence=0.0,
            confidence_basis=["no adjudication supplied"],
            action="needs_repro",
            recommended_step="Ask for a current-release reproduction before any decision.",
            evidence=[],
            duplicate_candidates=candidates,
            customer_signals=list(ticket.customer_signals),
            current_release=current_release,
            proposed_comment=_needs_repro_comment(ticket, current_release),
        )

    if assessment.disposition not in DISPOSITIONS:
        return Packet(
            key=ticket.key,
            summary=ticket.summary,
            status=ticket.status,
            disposition="unclear",
            confidence=0.0,
            confidence_basis=[f"unknown disposition {assessment.disposition!r}"],
            action="needs_repro",
            recommended_step="Correct the assessment disposition and rerun.",
            evidence=assessment.evidence,
            duplicate_candidates=candidates,
            customer_signals=list(ticket.customer_signals),
            current_release=current_release,
            invalid_evidence=assessment.invalid_evidence,
        )

    confidence, basis = evidence_confidence(assessment.evidence)
    gaps: List[str] = []
    if assessment.invalid_evidence:
        gaps.append(f"{len(assessment.invalid_evidence)} evidence item(s) lacked a citation")
    if ticket.customer_signals:
        gaps.append("customer-linked; close is disabled")

    disposition = assessment.disposition
    action = "comment_only"
    recommended = "Review the evidence and decide the next step."
    comment = ""
    threshold = 0.0
    explicit_duplicate_link = False

    if disposition == "duplicate":
        candidate, explicit_link = _duplicate_support(ticket, assessment, candidates)
        explicit_duplicate_link = explicit_link
        match_score = candidate.score if candidate is not None else 0.0
        if explicit_link:
            match_score = max(match_score, 0.90)
            basis.append("Jira Duplicate link present")
        if candidate is not None:
            basis.append(f"duplicate candidate {candidate.key} scored {candidate.score:.2f}")
        if not assessment.duplicate_of:
            gaps.append("duplicateOf is missing")
            disposition = "unclear"
            action = "needs_repro"
            recommended = "Name the duplicate target or downgrade the finding."
            comment = _needs_repro_comment(ticket, current_release)
        else:
            threshold = DUPLICATE_CLOSE_THRESHOLD
            confidence = min(confidence, match_score)
            if candidate is None and not explicit_link:
                gaps.append(
                    "duplicate target is not in the candidate set and has no Duplicate link"
                )
            elif match_score < threshold:
                gaps.append(
                    f"duplicate match {match_score:.2f} is below the {threshold:.2f} "
                    "close floor; only a comment is proposed"
                )
            allowed, reasons = _close_gate(
                ticket,
                confidence,
                threshold,
                assessment.evidence,
                assessment.independent_passes,
                assessment.agreement,
            )
            if allowed and match_score >= threshold:
                action = "propose_close_duplicate"
                recommended = f"Close as duplicate of {assessment.duplicate_of}."
                comment = assessment.comment or _duplicate_comment(ticket, assessment, candidate)
            else:
                gaps.extend(reasons)
                action = "comment_only" if confidence >= COMMENT_THRESHOLD else "needs_repro"
                recommended = (
                    f"Comment that this may duplicate {assessment.duplicate_of}; do not close."
                )
                comment = _duplicate_hint_comment(ticket, assessment, candidate)

    elif disposition == "already_fixed":
        artifact = assessment.fix_pr or assessment.fix_commit
        if not artifact:
            gaps.append("no fix PR or commit")
        if not assessment.fix_release:
            gaps.append("no release carrying the fix")
        if not assessment.fix_released:
            gaps.append("fix is not confirmed released")
        # The release under review must contain the fix. A fix that only landed
        # in a later release cannot close this ticket yet.
        fix_ahead_of_review = _release_after(assessment.fix_release, current_release)
        if fix_ahead_of_review:
            gaps.append(
                f"fix release {assessment.fix_release} is newer than the release "
                f"under review {current_release}"
            )
        threshold = FIXED_CLOSE_THRESHOLD
        allowed, reasons = _close_gate(
            ticket,
            confidence,
            threshold,
            assessment.evidence,
            assessment.independent_passes,
            assessment.agreement,
        )
        if (
            not artifact
            or not assessment.fix_released
            or not assessment.fix_release
            or fix_ahead_of_review
        ):
            allowed = False
        if allowed:
            action = "propose_close_fixed"
            recommended = f"Close as fixed by {artifact}" + (
                f", released in {assessment.fix_release}." if assessment.fix_release else "."
            )
            comment = assessment.comment or _fixed_comment(ticket, assessment)
        else:
            gaps.extend(reasons)
            action = "comment_only" if confidence >= COMMENT_THRESHOLD else "needs_repro"
            recommended = (
                "Comment with the fix lead; keep open until the fix is on a supported release."
            )
            release = _release_link(assessment)
            comment = (
                f"Possible fix: {ref_link(artifact) if artifact else 'unknown artifact'}."
                + (f" Reported fixed in {release}." if release else " No release is confirmed.")
                + "\n\nDo not close until the fix is verified on a supported release."
            )

    elif disposition == "no_longer_valid":
        threshold = OBSOLETE_CLOSE_THRESHOLD
        allowed, reasons = _close_gate(
            ticket,
            confidence,
            threshold,
            assessment.evidence,
            assessment.independent_passes,
            assessment.agreement,
        )
        direct_types = {item.type for item in assessment.evidence if item.strength == "direct"}
        if not direct_types & {"code", "doc", "repro", "release_note"}:
            allowed = False
            gaps.append("no direct code, doc, repro, or release-note evidence")
        if allowed:
            action = "propose_close_obsolete"
            recommended = "Close as no longer valid; cite the removal or failed reproduction."
            comment = assessment.comment or _obsolete_comment(ticket, assessment)
        else:
            gaps.extend(reasons)
            action = "comment_only" if confidence >= COMMENT_THRESHOLD else "needs_repro"
            recommended = "Comment only; the evidence does not prove the behavior is gone."
            comment = _obsolete_hint_comment(ticket, assessment)

    elif disposition == "still_valid":
        action = "keep_open"
        recommended = (
            "Keep open and assign to the owning team; add current-release reproduction "
            "detail to the ticket."
        )
        has_direct = any(item.strength == "direct" for item in assessment.evidence)
        if not assessment.evidence:
            gaps.append("still-valid claim has no citation")
            confidence = 0.0
            action = "needs_repro"
            recommended = "Ask for a reproduction; do not keep the claim uncited."
            comment = _needs_repro_comment(ticket, current_release)
        elif not has_direct:
            # "Still valid" asserts a behavior on a supported release. Supporting
            # context alone cannot prove that, so it degrades to an information
            # request instead of a confident classification.
            gaps.append("still-valid claim has no direct reproduction or code citation")
            action = "needs_repro"
            recommended = (
                "Ask for a current-release reproduction or a direct code citation "
                "before keeping this as still valid."
            )
            comment = _needs_repro_comment(ticket, current_release)
        else:
            comment = assessment.comment or _still_valid_comment(
                ticket, assessment, current_release
            )

    elif disposition == "needs_repro":
        action = "needs_repro"
        recommended = "Ask for the exact version, environment, and reproduction steps."
        comment = assessment.comment or _needs_repro_comment(ticket, current_release)

    else:  # unclear
        action = "unclear"
        recommended = "Do not act; collect more evidence first."
        if assessment.evidence:
            confidence, basis = evidence_confidence(assessment.evidence)
        comment = assessment.comment or _unclear_comment(ticket, assessment, current_release)

    packet = Packet(
        key=ticket.key,
        summary=ticket.summary,
        status=ticket.status,
        disposition=disposition,
        confidence=confidence,
        confidence_basis=basis,
        action=action,
        recommended_step=recommended,
        evidence=assessment.evidence,
        duplicate_candidates=candidates,
        target=assessment.duplicate_of if disposition == "duplicate" else "",
        explicit_duplicate_link=explicit_duplicate_link,
        gaps=gaps,
        notes=assessment.notes,
        customer_signals=list(ticket.customer_signals),
        current_release=current_release,
        independent_passes=assessment.independent_passes,
        agreement=assessment.agreement,
        proposed_comment=comment,
        invalid_evidence=assessment.invalid_evidence,
    )
    packet.verification_errors = verify_packet(packet, ticket)
    if packet.verification_errors:
        # Fail closed: a close proposal that cannot be verified becomes a comment.
        if packet.action in CLOSE_ACTIONS:
            packet.action = "comment_only"
            packet.recommended_step = (
                "Verifier rejected the close proposal; keep open and review the evidence."
            )
        packet.confidence_basis.append("verifier downgraded the action")
    if ticket.is_done and packet.action in CLOSE_ACTIONS:
        # A control may be an already-closed ticket. Classify it, but never
        # propose closing something that is already Done.
        packet.action = "comment_only"
        packet.gaps.append("ticket is already Done; close action suppressed")
        packet.recommended_step = (
            "Already closed. Use the classification as a control check; no close is proposed."
        )
        packet.proposed_comment = (
            assessment.comment
            or "This ticket is already closed. The triage classification is recorded "
            "for comparison only; no action is proposed."
        )
    return packet


def verify_packet(packet: Packet, ticket: Ticket) -> List[str]:
    """Re-check a packet against the close gate. Returns every violation."""
    errors: List[str] = []
    if packet.action not in CLOSE_ACTIONS:
        return errors
    if ticket.customer_signals or packet.customer_signals:
        errors.append("customer-linked ticket cannot receive a close proposal")
    if not packet.evidence:
        errors.append("close proposal has no evidence")
    if not any(item.strength == "direct" for item in packet.evidence):
        errors.append("close proposal has no direct evidence")
    if not _reviewed(packet.independent_passes, packet.agreement):
        errors.append("close proposal lacks a agreeing second independent pass")
    if packet.action == "propose_close_duplicate":
        if not packet.target:
            errors.append("duplicate close has no target key")
        strong_candidate = any(
            candidate.key == packet.target and candidate.score >= DUPLICATE_CLOSE_THRESHOLD
            for candidate in packet.duplicate_candidates
        )
        cited = any(
            item.type == "jira" and item.strength == "direct" and item.ref == packet.target
            for item in packet.evidence
        )
        if not (packet.explicit_duplicate_link or strong_candidate):
            errors.append("duplicate close needs a >=0.85 candidate or an explicit Duplicate link")
        if not (cited or packet.explicit_duplicate_link):
            errors.append("duplicate close has no direct citation of the target")
    if packet.action == "propose_close_fixed":
        if not any(
            item.type in ("pr", "commit") and item.strength == "direct" for item in packet.evidence
        ):
            errors.append("fixed close has no direct PR or commit citation")
    if packet.action == "propose_close_obsolete":
        if not any(
            item.type in ("code", "doc", "repro", "release_note") and item.strength == "direct"
            for item in packet.evidence
        ):
            errors.append("obsolete close has no direct code, doc, repro, or release-note citation")
    if packet.confidence < _threshold_for(packet.action):
        errors.append(
            f"confidence {packet.confidence:.2f} below {_threshold_for(packet.action):.2f}"
        )
    return errors


def _threshold_for(action: str) -> float:
    if action == "propose_close_duplicate":
        return DUPLICATE_CLOSE_THRESHOLD
    if action == "propose_close_fixed":
        return FIXED_CLOSE_THRESHOLD
    if action == "propose_close_obsolete":
        return OBSOLETE_CLOSE_THRESHOLD
    return 0.0


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
