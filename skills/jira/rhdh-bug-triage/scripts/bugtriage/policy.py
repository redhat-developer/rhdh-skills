"""Draft evidence-bounded triage findings, with separate advisory close gates.

Structural gates cannot establish the truth of a citation. Independent reviewers
must read the artifacts; a score or an assessment boolean is never that proof.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urlsplit

from .duplicates import DUPLICATE_CLOSE_THRESHOLD, DuplicateCandidate
from .model import JIRA_KEY_RE, Ticket, parse_datetime

POLICY_VERSION = 3
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
EVIDENCE_STRENGTHS = {"direct": 1.0, "strong": 0.8, "supporting": 0.5, "limited": 0.0}
EVIDENCE_TYPES = {"jira", "pr", "commit", "release_note", "code", "doc", "repro", "comment"}
NEXT_CHECK_METHODS = {"code", "runtime", "documentation", "dependency", "artifact"}
VALIDATION_TYPES = {
    "code": {"code", "pr", "commit"},
    "runtime": {"repro"},
    "documentation": {"doc", "release_note"},
    "dependency": {"code", "doc", "pr", "commit", "release_note"},
}
REPRO_RESULTS = {
    "",
    "not_run",
    "unknown",
    "reproduced",
    "not_reproduced",
    "fails",
    "passes",
    "persists",
    "resolved",
}
JIRA_BROWSE_URL = "https://redhat.atlassian.net/browse/"
PROOF_FIELDS = {
    "duplicate": ("sameFailure", "sameTrigger", "sameFix", "canonical"),
    "already_fixed": ("fixMatches", "releaseContains", "validation"),
    "no_longer_valid": ("scopeRemoval",),
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
    validation: Dict[str, Any] = field(default_factory=dict)
    history_review: Dict[str, Any] = field(default_factory=dict)
    next_check: Dict[str, Any] = field(default_factory=dict)


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
    current_release: str = ""
    independent_passes: int = 0
    agreement: bool = False
    proposed_comment: str = ""
    verification_errors: List[str] = field(default_factory=list)
    invalid_evidence: List[Dict[str, Any]] = field(default_factory=list)
    policy_version: int = POLICY_VERSION
    comment_plan: Dict[str, Any] = field(default_factory=dict)
    proof: Dict[str, Any] = field(default_factory=dict)
    fix: Dict[str, Any] = field(default_factory=dict)
    validation: Dict[str, Any] = field(default_factory=dict)
    repro: Dict[str, Any] = field(default_factory=dict)
    next_check: Dict[str, Any] = field(default_factory=dict)

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
            "validation": self.validation,
            "repro": self.repro,
            "nextCheck": self.next_check,
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
        validation=(document["validation"] if isinstance(document.get("validation"), dict) else {}),
        history_review=(
            document["historyReview"] if isinstance(document.get("historyReview"), dict) else {}
        ),
        repro_result=str(repro.get("result") or ""),
        repro_release=str(repro.get("release") or ""),
        notes=str(document.get("notes") or ""),
        comment=str(document.get("comment") or ""),
        recommended_step=str(document.get("recommendedStep") or ""),
        next_check=document.get("nextCheck") if isinstance(document.get("nextCheck"), dict) else {},
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
        "structural citation-strength score, not a probability or factual reliability guarantee",
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
        url = urlsplit(ref)
        tail = url.path.rstrip("/").rsplit("/", 1)[-1]
        if not label:
            label = (
                f"PR #{tail}"
                if "/pull/" in ref
                else f"commit {tail[:7]}"
                if "/commit/" in ref
                else f"{tail}:{url.fragment}"
                if "/blob/" in url.path and url.fragment
                else tail
                if "/blob/" in url.path
                else f"{tail} comment {parse_qs(url.query)['focusedCommentId'][0]}"
                if "focusedCommentId" in parse_qs(url.query)
                else "release record"
                if "/releases/" in url.path or "/errata/" in url.path
                else f"{url.hostname}: {tail}"
                if tail
                else str(url.hostname)
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


def _validation_errors(packet: Packet, result: str = "") -> List[str]:
    """A citation-strength score and historical reproduction are not validation."""
    validation = packet.validation
    if not isinstance(validation, dict) or not validation:
        return ["current-release validation is missing"]
    errors = []
    if _release_tuple(packet.current_release) is None:
        errors.append("validation needs an exact numeric current release")
    if validation.get("release") != packet.current_release:
        errors.append("validation must name the exact current release")
    method = validation.get("method")
    if not isinstance(method, str) or method not in VALIDATION_TYPES:
        errors.append("validation method must be code, runtime, documentation or dependency")
    outcome = validation.get("result")
    if outcome not in ("persists", "resolved", "unknown") or (result and outcome != result):
        errors.append(f"validation result must be {result or 'persists, resolved or unknown'}")
    if not isinstance(validation.get("summary"), str) or not validation["summary"].strip():
        errors.append("validation needs a causal summary")
    refs = validation.get("refs")
    cited = {item.ref: item for item in packet.evidence}
    if (
        not isinstance(refs, list)
        or not refs
        or any(not isinstance(ref, str) or ref not in cited for ref in refs)
    ):
        errors.append("validation references missing or uncited evidence")
    elif any(cited[ref].strength != "direct" for ref in refs):
        errors.append("validation requires direct cited evidence")
    elif isinstance(method, str) and method in VALIDATION_TYPES:
        if not any(cited[ref].type in VALIDATION_TYPES[method] for ref in refs):
            errors.append("validation citations do not support the named method")
    return errors


def input_errors(ticket: Ticket, *, require_customer_coverage: bool = True) -> List[str]:
    """Require screened delivery inputs separately from private behavior evidence."""
    errors = []
    if ticket.status.strip().casefold() in ("", "unknown", "none", "n/a", "unavailable"):
        errors.append("Jira status is unknown; retrieve it before a confident finding")
    if not ticket.description.strip():
        errors.append("Jira description is missing; retrieve the reported failure")
    payload = ticket.raw.get("fields", ticket.raw)
    if not isinstance(payload, dict):
        payload = {}
    if require_customer_coverage and (
        ticket.customer_fields_complete is not True
        or not ticket.customer_fields_read
        or ticket.unmapped_custom_fields
        or not isinstance(payload.get("labels"), list)
        or not isinstance(payload.get("issuelinks"), list)
    ):
        errors.append(
            "customer-field read coverage is incomplete; retrieve mapped fields, labels and links"
        )
    return errors


def _contradiction_errors(packet: Packet, result: str) -> List[str]:
    errors = []
    repro_result = packet.repro.get("result", "")
    current_release = _release_tuple(packet.current_release)
    repro_release = _release_tuple(str(packet.repro.get("release") or ""))
    if not isinstance(repro_result, str) or repro_result not in REPRO_RESULTS:
        errors.append("repro result is not a recognized outcome")
    elif current_release is not None and repro_release == current_release:
        contradicts = (
            repro_result in ("reproduced", "fails", "persists")
            if result == "resolved"
            else repro_result in ("not_reproduced", "passes", "resolved")
        )
        if contradicts:
            errors.append("current-release reproduction contradicts the claimed validation outcome")
    return errors


def verify_packet(packet: Packet, ticket: Ticket) -> List[str]:
    """Recheck saved findings; this checks structure, not a source's factual truth."""
    if packet.action == "abstain":
        return []
    errors = []
    if packet.key != ticket.key:
        errors.append("packet does not match the issue under review")
    if packet.action == "comment_only":
        if packet.disposition not in DISPOSITIONS - {"duplicate", "already_fixed"}:
            errors.append("duplicate/fixed findings require the full advisory proof gate")
        if packet.disposition in ("still_valid", "no_longer_valid"):
            errors.extend(input_errors(ticket, require_customer_coverage=False))
            if packet.invalid_evidence:
                errors.append("invalid evidence must be reconciled before a validity finding")
            errors.extend(
                _validation_errors(
                    packet, "persists" if packet.disposition == "still_valid" else "resolved"
                )
            )
            errors.extend(
                _contradiction_errors(
                    packet, "persists" if packet.disposition == "still_valid" else "resolved"
                )
            )
            if packet.independent_passes > 0 and packet.agreement is not True:
                errors.append("independent reviews disagree; validity remains unclear")
            if packet.disposition == "no_longer_valid":
                errors.extend(_proof_errors(packet))
                if not any(
                    item.type in ("code", "doc", "release_note", "commit")
                    for item in _claim_evidence(packet, "scopeRemoval")
                ):
                    errors.append("no-longer-valid finding needs direct scope-removal evidence")
        return errors
    expected = {"duplicate": "propose_close_duplicate", "already_fixed": "propose_close_fixed"}
    if packet.action not in CLOSE_ACTIONS or packet.action != expected.get(packet.disposition):
        return errors + ["unsupported triage action/disposition"]
    errors.extend(input_errors(ticket))
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
        errors.extend(_contradiction_errors(packet, "resolved"))
        if packet.validation:
            errors.extend(_validation_errors(packet, "resolved"))
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


def _usable_next_check(packet: Packet) -> bool:
    """A cited investigation question is not proof or an executable instruction."""
    check = packet.next_check
    if packet.disposition != "unclear" or packet.verification_errors or not check:
        return False
    question = check.get("question")
    refs = check.get("refs")
    return bool(
        isinstance(check.get("method"), str)
        and check["method"] in NEXT_CHECK_METHODS
        and isinstance(question, str)
        and 1 < len(question) <= 400
        and question.strip() == question
        and question.endswith("?")
        and not re.search(r"[\r\n]", question)
        and isinstance(refs, list)
        and refs
        and all(
            isinstance(ref, str) and ref in {item.ref for item in packet.evidence} for ref in refs
        )
    )


def next_step_kind(packet: Packet) -> str:
    """Stable intent for generated advice; free-form assessment advice is untrusted."""
    if _release_tuple(packet.current_release) is None:
        return "identify_current_release"
    if packet.disposition == "duplicate":
        return "review_duplicate_recommendation"
    if packet.disposition == "already_fixed":
        return "review_fixed_recommendation"
    if packet.disposition == "still_valid":
        return "trace_validated_failure"
    if packet.disposition == "no_longer_valid":
        return "review_scope_removal"
    if packet.disposition == "needs_repro":
        return "validate_reported_trigger"
    if _usable_next_check(packet):
        return f"investigate_{packet.next_check['method']}"
    if (
        packet.disposition == "unclear"
        and packet.validation.get("result") == "resolved"
        and not _validation_errors(packet)
    ):
        return "identify_fix_provenance"
    if packet.target:
        return "compare_duplicate_reports"
    if packet.fix:
        return (
            "verify_fix_in_current_release"
            if packet.fix.get("pr") or packet.fix.get("commit")
            else "find_fix_evidence"
        )
    if not packet.evidence:
        return "collect_missing_assessment_evidence"
    return "inspect_current_release"


def _next_step(packet: Packet) -> str:
    if _usable_next_check(packet):
        check = packet.next_check
        return (
            f"Investigate ({check['method']}): {_linked_text(check['question'])} Sources: "
            + "; ".join(ref_link(ref) for ref in sorted(set(check["refs"])))
        )
    validation_refs = (
        packet.validation["refs"] if packet.validation and not _validation_errors(packet) else []
    )
    focus = (
        sorted(validation_refs)[0]
        if validation_refs
        else next(
            (
                item.ref
                for item in sorted(packet.evidence, key=lambda item: item.ref)
                if item.strength == "direct"
            ),
            packet.key,
        )
    )
    return {
        "identify_current_release": (
            "Next, identify the current released product version from the authoritative release source."
        ),
        "review_duplicate_recommendation": (
            f"Review the recommendation to retain {ref_link(packet.target)} as the canonical "
            f"tracker and close {ref_link(packet.key)} as its duplicate; human approval is required."
        ),
        "review_fixed_recommendation": (
            f"Review the recommendation to close {ref_link(packet.key)} as fixed in "
            f"{packet.fix.get('release', '')}; human approval is required."
        ),
        "trace_validated_failure": (
            "Prioritize the validated finding for the next y-stream release. Keep this issue open."
        ),
        "review_scope_removal": (
            "Next, compare the documented scope removal against the original reported trigger."
        ),
        "validate_reported_trigger": (
            f"Next, validate the reported trigger on release {packet.current_release} "
            f"using {ref_link(focus)} and record the observed result."
        ),
        "compare_duplicate_reports": (
            "Next, compare the reported failure and trigger in both Jira reports "
            "to resolve the missing duplicate proof."
        ),
        "verify_fix_in_current_release": (
            f"Next, trace the cited change into release {packet.current_release} "
            "to check whether it addresses the reported failure."
        ),
        "find_fix_evidence": (
            "Next, inspect the Jira development records for a fix artifact relevant to the reported failure."
        ),
        "identify_fix_provenance": (
            f"Next, identify the incorporated corrective commit behind {ref_link(focus)} and verify its ancestry "
            f"to release {packet.current_release} before recommending closure."
        ),
        "collect_missing_assessment_evidence": (
            f"Next, inspect {ref_link(packet.key)} to collect the missing assessment evidence."
        ),
        "inspect_current_release": (
            f"Next, inspect the reported failure path in release {packet.current_release} "
            f"using {ref_link(focus)} and record whether the triggering condition remains."
        ),
    }[next_step_kind(packet)]


def _linked_text(value: str) -> str:
    """Render source summaries as text, not executable Markdown or new advice."""
    text = " ".join(value.split())
    # Prose can contain CVE-2025-1234 or SHA-512. Syntactic similarity to a
    # Jira key does not authorize inventing a browse URL for that terminology.
    parts = re.split(
        r"(https://[^\s<>]+|(?<![\w-])(?:RHDHBUGS|RHIDP|RHDHPLAN|RHDHSUPP)-\d+(?![\w-]))",
        text,
    )
    return "".join(
        ref_link(part)
        if valid_ref(part)
        and (
            part.startswith("https://")
            or re.fullmatch(r"(?:RHDHBUGS|RHIDP|RHDHPLAN|RHDHSUPP)-\d+", part)
        )
        else part.replace("[", r"\[").replace("]", r"\]")
        for part in parts
    )


def recommendation_comment(packet: Packet, ticket: Ticket) -> str:
    """Deterministic draft; visibility never implies eligibility or a Jira write."""
    if packet.action not in CLOSE_ACTIONS | {"comment_only"}:
        return ""
    lines = [f"Re: {ref_link(ticket.key)} — {_linked_text(ticket.summary)}", ""]
    verdicts = {
        "duplicate": f"The reported failure duplicates {ref_link(packet.target)}.",
        "already_fixed": (
            f"The reported failure is resolved by "
            f"{ref_link(packet.fix.get('pr') or packet.fix.get('commit', ''))}, "
            f"included in release {packet.fix.get('release', '')}."
        ),
        "still_valid": f"The reported failure persists on release {packet.current_release}.",
        "no_longer_valid": (
            f"The reported trigger is outside the current scope on release {packet.current_release}."
        ),
        "needs_repro": "Current-release behavior needs validation; the outcome is unknown.",
        "unclear": "The evidence is incomplete or conflicting; no definitive triage conclusion is established.",
    }
    lines += [
        f"Disposition: {packet.disposition} — {verdicts[packet.disposition]}",
        "",
        "Evidence:",
    ]
    lines.append(f"- {ref_link(ticket.key)} — Jira reports: {_linked_text(ticket.summary)}")
    # Failed gates must not leak an unverified old proof or its conclusion via
    # evidence.why. Those assertions remain available in the local audit.
    limited = bool(packet.verification_errors) and packet.disposition == "unclear"
    for item in sorted(packet.evidence, key=lambda item: (item.ref, item.type, item.why)):
        summary = (
            f"Supplied {item.type} citation; the claimed conclusion has not passed verification."
            if limited
            else _linked_text(item.why)
        )
        qualifier = "Limited source (not proof)" if item.strength == "limited" else "Source summary"
        lines.append(f"- {ref_link(item.ref)} — {qualifier}: {summary}")
    if packet.disposition in ("unclear", "needs_repro"):
        # Collection/reporting may append unrelated data gaps after evaluation;
        # those do not change the adjudication or its deterministic draft.
        reasons = packet.verification_errors or [
            gap
            for gap in packet.gaps
            if gap.startswith(
                (
                    "no assessment",
                    "assessment ",
                    "independent reviews",
                    "invalid evidence",
                    "no cited current-release",
                )
            )
        ]
        reason = "; ".join(reasons) or (
            str(packet.validation.get("summary") or "")
            if packet.validation and not _validation_errors(packet)
            else "no conclusive current-release validation was supplied"
        )
        if packet.verification_errors or not packet.validation or _validation_errors(packet):
            lines += ["", f"Unknown: {_linked_text(reason.rstrip('.'))}."]
    owner = (
        f"Jira assignee: {_linked_text(ticket.assignee)}"
        if ticket.assignee
        else "No assignee is established by the supplied Jira fields"
    )
    if ticket.team:
        owner += f"; Jira team: {_linked_text(ticket.team)}"
    lines += ["", f"Owner: {owner}."]
    if packet.validation and not limited:
        validation = packet.validation
        validation_errors = _validation_errors(packet)
        accepted = not validation_errors
        refs = validation.get("refs", [])
        refs = refs if isinstance(refs, list) else []
        cited = {item.ref for item in packet.evidence}
        lines += [
            "",
            f"{'Validation' if accepted else 'Validation account (not accepted proof)'}: "
            f"{_linked_text(str(validation.get('method') or 'unknown method'))} on release "
            f"{_linked_text(str(validation.get('release') or 'unknown'))}; "
            f"result: {validation['result'] if accepted else 'unknown'} — "
            f"{_linked_text(str(validation.get('summary') or 'No validation summary supplied.'))} "
            + "; ".join(
                ref_link(ref)
                for ref in sorted({ref for ref in refs if isinstance(ref, str) and ref in cited})
            ),
        ]
        if validation_errors:
            lines.append("Validation gaps: " + "; ".join(validation_errors) + ".")
    labels = {
        "sameFailure": "Same failure",
        "sameTrigger": "Same trigger",
        "sameFix": "Same required fix",
        "canonical": "Canonical tracker",
        "fixMatches": "Matching implementation",
        "releaseContains": "Released inclusion",
        "validation": "Validation",
        "scopeRemoval": "Scope removal",
    }
    if packet.disposition in PROOF_FIELDS:
        lines += ["", "Proof:"]
    for name in PROOF_FIELDS.get(packet.disposition, ()):
        claim = packet.proof[name]
        lines.append(
            f"- {labels[name]}: {_linked_text(claim['summary'])} "
            + "; ".join(ref_link(ref) for ref in sorted(set(claim["refs"])))
        )
    lines += [
        "",
        f"Recommended next step: {_next_step(packet)}",
        "",
        (
            "Confidence: not established for a definitive conclusion; current-release uncertainty remains (not a probability)."
            if packet.disposition in ("unclear", "needs_repro")
            else f"Confidence: {packet.confidence:.2f} (structural evidence-policy score; not a probability or factual guarantee)."
        ),
    ]
    return "\n".join(lines)


def evaluate(
    ticket: Ticket,
    candidates: List[DuplicateCandidate],
    assessment: Optional[Assessment],
    current_release: str = "",
) -> Packet:
    disposition = (
        assessment.disposition
        if assessment and assessment.disposition in DISPOSITIONS
        else "unclear"
    )
    matched = assessment is not None and assessment.key == ticket.key
    evidence = (
        [item for item in assessment.evidence if _evidence_from(item.to_dict()) is not None]
        if matched
        else []
    )
    confidence, basis = evidence_confidence(evidence)
    packet = Packet(
        key=ticket.key,
        summary=ticket.summary,
        status=ticket.status,
        disposition=disposition,
        confidence=confidence,
        confidence_basis=basis,
        action="comment_only",
        recommended_step="",
        evidence=evidence,
        duplicate_candidates=candidates,
        customer_signals=list(ticket.customer_signals),
        current_release=current_release,
    )
    if ticket.customer_signals or ticket.is_done:
        packet.disposition, packet.action = "unclear", "abstain"
        packet.gaps.append(
            "customer-linked or completed ticket is outside aged non-customer triage scope"
        )
        if assessment is not None and not matched:
            packet.gaps.append("assessment does not match the issue under review")
        return packet
    if not matched:
        packet.disposition = "unclear"
        if assessment is None:
            packet.gaps.append("no assessment supplied; current-release validation was not checked")
        else:
            packet.gaps.append("assessment does not match the issue under review")
    else:
        packet.notes = assessment.notes
        packet.proof = assessment.proof
        packet.validation = assessment.validation
        packet.next_check = assessment.next_check
        packet.repro = {"result": assessment.repro_result, "release": assessment.repro_release}
        packet.invalid_evidence = assessment.invalid_evidence
        packet.independent_passes, packet.agreement = (
            assessment.independent_passes,
            assessment.agreement,
        )
    if matched and not assessment.disposition:
        packet.gaps.append("assessment has no disposition; current-release outcome is unknown")
    if matched and not packet.evidence:
        packet.gaps.append("assessment has no valid evidence; current-release outcome is unknown")
        packet.disposition = "unclear"
    if matched and assessment.independent_passes > 0 and assessment.agreement is not True:
        packet.gaps.append(
            "independent reviews disagree or have not agreed; outcome remains unclear"
        )
        if disposition in ("unclear", "needs_repro"):
            packet.disposition = "unclear"
    if matched and packet.invalid_evidence and disposition in ("unclear", "needs_repro"):
        packet.gaps.append("invalid evidence must be reconciled before drawing a conclusion")
        packet.disposition = "unclear"
    if matched and disposition == "duplicate":
        packet.target = assessment.duplicate_of
        packet.explicit_duplicate_link = any(
            link.key == packet.target
            and "duplicate" in link.type.lower()
            and link.direction == "outward"
            for link in ticket.links
        )
        # Candidate scores rank retrieval only. Different wording is not a veto
        # on complete, directly cited semantic proof and agreeing reviews.
        packet.disposition = "duplicate"
        packet.action = "propose_close_duplicate"
    elif matched and disposition == "already_fixed":
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
        packet.disposition = "already_fixed"
        packet.action = "propose_close_fixed"
    packet.verification_errors = verify_packet(packet, ticket)
    if packet.verification_errors:
        packet.gaps.extend(packet.verification_errors)
        packet.disposition, packet.action = "unclear", "comment_only"
    if packet.disposition == "needs_repro" and not packet.validation:
        packet.gaps.append("no cited current-release validation result was supplied")
    packet.recommended_step = _next_step(packet)
    packet.proposed_comment = recommendation_comment(packet, ticket)
    return packet
