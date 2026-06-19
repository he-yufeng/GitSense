"""Predict how likely a specific open pull request is to get merged.

A transparent heuristic (no ML), in the same spirit as the repo radar: from the
observable signals on a PR — review state, draft flag, conflicts, CI, diff size,
whether it touches tests, and age — produce a 0-100 merge-likelihood score plus
the human-readable notes behind it. The scoring (:func:`score_pr`) is pure, so
it's easy to test; :func:`analyze_pr` pulls those signals out of a GitHub PR
payload and feeds them in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PRPrediction:
    score: int
    label: str
    notes: list[str] = field(default_factory=list)


def score_pr(
    *,
    review_decision: str | None,
    is_draft: bool,
    mergeable_state: str | None,
    ci_failing: bool,
    changed_files: int,
    additions: int,
    touches_tests: bool,
    age_days: float | None,
) -> tuple[int, list[str]]:
    """Estimate a 0-100 merge-likelihood score for an open PR, with notes."""
    score = 50
    notes: list[str] = []

    decision = (review_decision or "").upper()
    if decision == "APPROVED":
        score += 28
        notes.append("already approved by a reviewer")
    elif decision == "CHANGES_REQUESTED":
        score -= 25
        notes.append("changes requested — address the review first")
    else:
        notes.append("no review decision yet")

    if is_draft:
        score -= 18
        notes.append("still a draft — mark it ready for review")

    if (mergeable_state or "").upper() in {"DIRTY", "CONFLICTING"}:
        score -= 18
        notes.append("has merge conflicts — rebase onto the base branch")

    if ci_failing:
        score -= 20
        notes.append("CI is failing — fix the checks")
    else:
        score += 8
        notes.append("CI is not failing")

    if changed_files <= 3 and additions <= 100:
        score += 15
        notes.append("small, focused diff")
    elif changed_files >= 30 or additions >= 1000:
        score -= 15
        notes.append("large diff — big PRs are slower to land")

    if touches_tests:
        score += 10
        notes.append("includes tests")
    else:
        notes.append("no test changes detected")

    if age_days is not None and age_days > 60:
        score -= 12
        notes.append("open for a long time — may be stalled")

    return max(0, min(100, score)), notes


def parse_pr_ref(ref: str) -> tuple[str, str, int]:
    """Parse a PR reference into (owner, repo, number).

    Accepts a full URL (``https://github.com/owner/repo/pull/123``) or the
    short ``owner/repo#123`` form.
    """
    cleaned = ref.strip().removeprefix("https://github.com/").strip("/")
    if "/pull/" in cleaned:
        path, _, num = cleaned.partition("/pull/")
        owner_repo = path
    elif "#" in cleaned:
        owner_repo, _, num = cleaned.partition("#")
    else:
        raise ValueError("PR ref must be a URL or owner/repo#number")
    parts = [p for p in owner_repo.split("/") if p]
    num = num.split("/", 1)[0].strip()
    if len(parts) < 2 or not num.isdigit():
        raise ValueError("PR ref must be a URL or owner/repo#number")
    return parts[0], parts[1], int(num)


def derive_review_decision(reviews: list[dict[str, Any]]) -> str | None:
    """Collapse a PR's review history into a single decision.

    Mirrors how GitHub itself decides: only the latest non-comment review from
    each reviewer counts. CHANGES_REQUESTED from anyone wins; otherwise an
    APPROVED makes it approved; otherwise there's no decision yet.
    """
    latest: dict[str, str] = {}
    for review in reviews:
        state = (review.get("state") or "").upper()
        if state in {"COMMENTED", "DISMISSED", "PENDING", ""}:
            continue
        user = (review.get("user") or {}).get("login") or ""
        latest[user] = state
    states = set(latest.values())
    if "CHANGES_REQUESTED" in states:
        return "CHANGES_REQUESTED"
    if "APPROVED" in states:
        return "APPROVED"
    return None


def files_touch_tests(files: list[dict[str, Any]]) -> bool:
    """True if any changed file looks like a test (path contains 'test' or 'spec')."""
    for f in files:
        name = (f.get("filename") or "").lower()
        if "test" in name or "spec" in name:
            return True
    return False


def prediction_label(score: int) -> str:
    if score >= 70:
        return "Likely to merge"
    if score >= 45:
        return "Could go either way"
    if score >= 25:
        return "Long shot"
    return "Unlikely as-is"


def _age_days(created_at: str | None) -> float | None:
    if not created_at:
        return None
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - created).total_seconds() / 86400


def analyze_pr(
    pr: dict[str, Any],
    *,
    review_decision: str | None = None,
    ci_failing: bool = False,
    touches_tests: bool = False,
) -> PRPrediction:
    """Turn a GitHub PR payload plus a few derived signals into a prediction.

    ``pr`` is a REST pull-request object (draft, additions, changed_files,
    mergeable_state, created_at). ``review_decision``, ``ci_failing`` and
    ``touches_tests`` come from the reviews / checks / files endpoints.
    """
    score, notes = score_pr(
        review_decision=review_decision,
        is_draft=bool(pr.get("draft", False)),
        mergeable_state=pr.get("mergeable_state"),
        ci_failing=ci_failing,
        changed_files=int(pr.get("changed_files", 0) or 0),
        additions=int(pr.get("additions", 0) or 0),
        touches_tests=touches_tests,
        age_days=_age_days(pr.get("created_at")),
    )
    return PRPrediction(score=score, label=prediction_label(score), notes=notes)
