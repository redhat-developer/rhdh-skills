"""Evaluation harness for a dry-run triage pass.

Ground truth is a small JSON map supplied by the reviewer. The harness reports
coverage, decision-ready rate, precision/recall for the closeable dispositions,
and — most importantly — every false close proposal. A false close is a hard
failure even when every other number looks good.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .policy import CLOSE_ACTIONS, Packet

DISPOSITION_ALIASES = {
    "fixed": "already_fixed",
    "duplicate": "duplicate",
    "still_valid": "still_valid",
    "no_longer_valid": "no_longer_valid",
    "needs_repro": "needs_repro",
    "unclear": "unclear",
}

CLOSE_FOR_DISPOSITION = {
    "duplicate": "propose_close_duplicate",
    "already_fixed": "propose_close_fixed",
    "no_longer_valid": "propose_close_obsolete",
}


@dataclass
class Evaluation:
    total: int
    matched: int
    decision_ready: int
    classified: int
    close_proposals: int
    false_closes: List[Dict[str, str]]
    disposition_mismatches: List[Dict[str, str]]
    precision: Dict[str, float]
    recall: Dict[str, float]
    support: Dict[str, int]
    predicted: Dict[str, int]
    abstained: int
    gaps: int

    @property
    def coverage(self) -> float:
        return self.matched / self.total if self.total else 0.0

    @property
    def decision_ready_rate(self) -> float:
        return self.decision_ready / self.matched if self.matched else 0.0

    @property
    def classified_rate(self) -> float:
        return self.classified / self.matched if self.matched else 0.0

    @property
    def abstain_rate(self) -> float:
        return self.abstained / self.matched if self.matched else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "totalLabels": self.total,
            "matched": self.matched,
            "coverage": round(self.coverage, 3),
            "decisionReady": self.decision_ready,
            "decisionReadyRate": round(self.decision_ready_rate, 3),
            "classified": self.classified,
            "classifiedRate": round(self.classified_rate, 3),
            "closeProposals": self.close_proposals,
            "falseCloses": self.false_closes,
            "dispositionMismatches": self.disposition_mismatches,
            "precision": {key: round(value, 3) for key, value in self.precision.items()},
            "recall": {key: round(value, 3) for key, value in self.recall.items()},
            "support": self.support,
            "predicted": self.predicted,
            "abstained": self.abstained,
            "abstainRate": round(self.abstain_rate, 3),
            "gaps": self.gaps,
        }


def load_truth(path: str) -> Dict[str, Dict[str, str]]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    if isinstance(document, dict) and isinstance(document.get("labels"), dict):
        document = document["labels"]
    if not isinstance(document, dict):
        raise ValueError("truth must map issue keys to labels")
    truth: Dict[str, Dict[str, str]] = {}
    for key, value in document.items():
        if not isinstance(value, dict):
            continue
        disposition = str(value.get("disposition") or "").strip().lower()
        disposition = DISPOSITION_ALIASES.get(disposition, disposition)
        truth[key] = {
            "disposition": disposition,
            "duplicateOf": str(value.get("duplicateOf") or "").strip(),
        }
    return truth


def _is_close_for(packet: Packet, truth: Dict[str, str]) -> bool:
    expected = CLOSE_FOR_DISPOSITION.get(truth["disposition"])
    if expected is None:
        return False
    if packet.action != expected:
        return False
    if expected == "propose_close_duplicate":
        return packet.target == truth.get("duplicateOf", "")
    return True


def evaluate(packets: Iterable[Packet], truth: Dict[str, Dict[str, str]]) -> Evaluation:
    by_key = {packet.key: packet for packet in packets}
    matched = [key for key in truth if key in by_key]
    false_closes: List[Dict[str, str]] = []
    mismatches: List[Dict[str, str]] = []
    decision_ready = 0
    classified = 0
    close_proposals = 0
    abstained = 0
    gaps = 0

    true_positive: Dict[str, int] = {}
    false_positive: Dict[str, int] = {}
    false_negative: Dict[str, int] = {}
    support: Dict[str, int] = {}
    predicted: Dict[str, int] = {}
    for label in CLOSE_FOR_DISPOSITION:
        true_positive[label] = 0
        false_positive[label] = 0
        false_negative[label] = 0
        support[label] = 0
        predicted[label] = 0

    for key in matched:
        packet = by_key[key]
        expected = truth[key]
        gaps += len(packet.gaps)
        if packet.action != "unclear":
            decision_ready += 1
        if packet.disposition not in ("unclear", "needs_repro"):
            classified += 1
        if packet.action in CLOSE_ACTIONS:
            close_proposals += 1
            if not _is_close_for(packet, expected):
                false_closes.append(
                    {
                        "key": key,
                        "action": packet.action,
                        "target": packet.target,
                        "expected": expected["disposition"],
                    }
                )
        if packet.disposition != expected["disposition"]:
            mismatches.append(
                {
                    "key": key,
                    "observed": packet.disposition,
                    "expected": expected["disposition"],
                }
            )
        if packet.disposition in ("unclear", "needs_repro"):
            abstained += 1
        for label in CLOSE_FOR_DISPOSITION:
            if expected["disposition"] == label:
                support[label] += 1
            if packet.disposition == label:
                predicted[label] += 1
            if expected["disposition"] == label and packet.disposition == label:
                true_positive[label] += 1
            elif expected["disposition"] == label and packet.disposition != label:
                false_negative[label] += 1
            elif expected["disposition"] != label and packet.disposition == label:
                false_positive[label] += 1

    precision = {
        label: (true_positive[label] / (true_positive[label] + false_positive[label]))
        if (true_positive[label] + false_positive[label])
        else 0.0
        for label in CLOSE_FOR_DISPOSITION
    }
    recall = {
        label: (true_positive[label] / (true_positive[label] + false_negative[label]))
        if (true_positive[label] + false_negative[label])
        else 0.0
        for label in CLOSE_FOR_DISPOSITION
    }

    return Evaluation(
        total=len(truth),
        matched=len(matched),
        decision_ready=decision_ready,
        classified=classified,
        close_proposals=close_proposals,
        false_closes=false_closes,
        disposition_mismatches=mismatches,
        precision=precision,
        recall=recall,
        support=support,
        predicted=predicted,
        abstained=abstained,
        gaps=gaps,
    )


def render_evaluation(evaluation: Evaluation, *, strict: bool = False) -> str:
    lines = [
        "# Bug-triage evaluation",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Labels | {evaluation.total} |",
        f"| Packets matched | {evaluation.matched} |",
        f"| Coverage | {evaluation.coverage:.0%} |",
        f"| Decision-ready | {evaluation.decision_ready}/{evaluation.matched} "
        f"({evaluation.decision_ready_rate:.0%}) |",
        f"| Classified disposition | {evaluation.classified}/{evaluation.matched} "
        f"({evaluation.classified_rate:.0%}) |",
        f"| Close proposals | {evaluation.close_proposals} |",
        f"| False close proposals | {len(evaluation.false_closes)} |",
        f"| Abstain rate | {evaluation.abstain_rate:.0%} |",
        f"| Evidence gaps | {evaluation.gaps} |",
        "",
        "## Precision and recall",
        "",
        "| Disposition | Precision | Recall |",
        "|---|---|---|",
    ]
    # A label with no ground truth and no packet says nothing about precision or
    # recall; printing 0% would read as a miss when the label was never exercised.
    for label in CLOSE_FOR_DISPOSITION:
        if evaluation.support[label] == 0 and evaluation.predicted[label] == 0:
            continue
        lines.append(
            f"| `{label}` | {evaluation.precision[label]:.0%} | {evaluation.recall[label]:.0%} |"
        )
    if evaluation.false_closes:
        lines.extend(["", "## False close proposals", ""])
        for item in evaluation.false_closes:
            lines.append(
                f"- {item['key']}: proposed `{item['action']}` but truth is `{item['expected']}`"
            )
    if evaluation.disposition_mismatches:
        lines.extend(["", "## Disposition mismatches", ""])
        for item in evaluation.disposition_mismatches:
            lines.append(
                f"- {item['key']}: observed `{item['observed']}`, expected `{item['expected']}`"
            )
    lines.extend(
        [
            "",
            "A false close is the only hard-fail metric. Precision below 100% on a "
            "small control set is informational; a proposed close with the wrong "
            "ground truth is not.",
            "",
        ]
    )
    return "\n".join(lines)


def write_evaluation(
    packets_path: str,
    truth_path: str,
    *,
    output_path: str = "",
    strict: bool = False,
) -> tuple[Evaluation, str]:
    with open(packets_path, encoding="utf-8") as handle:
        document = json.load(handle)

    packets = []
    for item in document.get("packets", []):
        packet = Packet(
            key=item["key"],
            summary=item.get("summary", ""),
            status=item.get("status", ""),
            disposition=item.get("disposition", "unclear"),
            confidence=float(item.get("confidence", 0.0)),
            confidence_basis=item.get("confidenceBasis", []),
            action=item.get("action", "unclear"),
            recommended_step=item.get("recommendedStep", ""),
            evidence=[],
            duplicate_candidates=[],
            gaps=item.get("gaps", []),
            target=item.get("target", ""),
        )
        packets.append(packet)
    evaluation = evaluate(packets, load_truth(truth_path))
    rendered = render_evaluation(evaluation, strict=strict)
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(rendered, encoding="utf-8")
    return evaluation, rendered
