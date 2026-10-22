"""Difficulty calibration: check effort estimates against your own history.

``matcher.estimate_difficulty`` scores how much effort an issue looks like,
but any such estimate is a prior. The honest check is your own track record:
the issues *you* actually closed, and how long they took from open to close.
This module pulls that history, buckets it by what the estimator would have
said, and reports whether harder-looking issues really took you longer. The
report is persisted so ``find`` can annotate new results with what "easy" or
"hard" has meant in days for you personally.
"""

from __future__ import annotations

import json
import os
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

from gitsense.github_client import search_issues
from gitsense.matcher import estimate_difficulty
from gitsense.state import resolve_state_file

_BUCKETS = ("easy", "medium", "hard")
_STATE_FILE = "calibration.json"


@dataclass
class Bucket:
    name: str
    count: int = 0
    median_days: float | None = None
    closes: list[float] = field(default_factory=list)


@dataclass
class CalibrationReport:
    username: str
    total_closed: int
    buckets: list[Bucket]
    verdict: str

    def days_for(self, difficulty: int) -> float | None:
        """Median close time for the bucket an estimate falls into, if any."""
        return next(
            (b.median_days for b in self.buckets if b.name == bucket_name(difficulty) and b.count),
            None,
        )


def bucket_name(difficulty: int) -> str:
    if difficulty <= 3:
        return "easy"
    if difficulty <= 6:
        return "medium"
    return "hard"


def fetch_closed_issues(username: str, per_page: int = 50) -> list[dict[str, Any]]:
    """Issues assigned to the user that are now closed, newest close first."""
    return search_issues(
        f"is:issue is:closed assignee:{username}",
        sort="updated",
        order="desc",
        per_page=per_page,
    )


def _close_days(item: dict[str, Any]) -> float | None:
    """Days from issue open to close, the observable proxy for effort."""
    from gitsense.radar import _days_between

    return _days_between(item.get("created_at"), item.get("closed_at"))


def build_report(
    username: str, items: list[dict[str, Any]], skills: list[str]
) -> CalibrationReport:
    """Pair each closed issue with the estimate it would have gotten, then
    bucket the observed close times by that estimate."""
    by_name = {name: Bucket(name=name) for name in _BUCKETS}
    usable = 0
    for item in items:
        days = _close_days(item)
        if days is None:
            continue
        estimate, _ = estimate_difficulty(item, skills)
        bucket = by_name[bucket_name(estimate)]
        bucket.count += 1
        bucket.closes.append(days)
        usable += 1

    for bucket in by_name.values():
        if bucket.closes:
            bucket.median_days = round(statistics.median(bucket.closes), 1)

    medians = [b.median_days for b in by_name.values() if b.median_days is not None]
    if usable < 3:
        verdict = (
            f"only {usable} closed issue(s) with usable dates; treat the "
            "calibration as anecdote until more history accumulates"
        )
    elif medians == sorted(medians):
        verdict = (
            "harder-looking issues did take you longer; the estimate tracks "
            "your reality"
        )
    else:
        verdict = (
            "your close times do not rise with the estimate; treat the raw "
            "score with care until more history accumulates"
        )

    return CalibrationReport(
        username=username,
        total_closed=usable,
        buckets=list(by_name.values()),
        verdict=verdict,
    )


def save_report(report: CalibrationReport, state_dir_override: str | None = None) -> str:
    path = resolve_state_file(state_dir_override, _STATE_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(report), fh, indent=1)
    return path


def load_report(state_dir_override: str | None = None) -> CalibrationReport | None:
    path = resolve_state_file(state_dir_override, _STATE_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return CalibrationReport(
        username=data["username"],
        total_closed=data["total_closed"],
        buckets=[Bucket(**b) for b in data["buckets"]],
        verdict=data["verdict"],
    )


def effort_note(difficulty: int, report: CalibrationReport | None) -> str:
    """One-line annotation for a find result, e.g.
    ``effort ~4/10 · your medium closes took a median of 9d``."""
    note = f"effort ~{difficulty}/10"
    if report is not None:
        days = report.days_for(difficulty)
        if days is not None:
            note += f" · your {bucket_name(difficulty)} closes took a median of {days:g}d"
    return note
