"""Deterministic skill matching for runs without an LLM key.

``find`` asks an LLM to score and explain each candidate when a key is
configured. Without one, the old fallback stamped everything with a flat 5
and "LLM ranking unavailable", which told you nothing about why an issue
matched. This module is the zero-config path: match each skill against the
title, labels and body on word boundaries, fold in the signals we already
have (newcomer labels, freshness, claim status, thread noise), and spell out
which evidence moved the score. No network, no key, fully testable.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# labels that signal an issue is meant for a first-time contributor
_NEWCOMER_LABELS = {
    "good first issue",
    "good-first-issue",
    "help wanted",
    "beginner-friendly",
    "good first bug",
    "starter",
}

_FRESH_DAYS = 14
_NOISY_COMMENTS = 20


def _word_hit(needle: str, haystack: str) -> bool:
    """True when ``needle`` appears in ``haystack`` as a standalone token.

    Plain ``\b`` fails for skills ending in symbols ("c++" never matches), so
    the guards are explicit and only applied on the side where the needle has
    a word character: "c++" still matches "C++17", while "go" stays out of
    "django" and "python" out of "python3".
    """
    n = needle.lower()
    pattern = re.escape(n)
    if n[0].isalnum() or n[0] == "_":
        pattern = r"(?<![\w])" + pattern
    if n[-1].isalnum() or n[-1] == "_":
        pattern = pattern + r"(?![\w])"
    return re.search(pattern, haystack) is not None


def _days_since(date_str: str) -> float | None:
    try:
        when = datetime.fromisoformat(date_str[:10])
    except ValueError:
        return None
    return (datetime.now(timezone.utc).date() - when.date()).days


def score_match(candidate: dict[str, Any], skills: list[str]) -> tuple[int, list[str]]:
    """Score one candidate against the skill list and explain the score.

    Returns ``(score, reasons)`` where score is 1-10 and reasons lists the
    evidence in plain words, strongest first. Skill evidence alone caps at 8;
    newcomer labels and freshness push higher, claims and noisy threads pull
    down.
    """
    title = (candidate.get("title") or "").lower()
    body = (candidate.get("body") or "").lower()
    labels = [str(lab).lower() for lab in candidate.get("labels") or []]

    title_hits = [s for s in skills if _word_hit(s, title)]
    label_hits = [
        s for s in skills if s not in title_hits and any(_word_hit(s, lab) for lab in labels)
    ]
    body_hits = [
        s for s in skills if s not in title_hits and s not in label_hits and _word_hit(s, body)
    ]

    score = 3 + 2 * len(title_hits) + len(label_hits) + len(body_hits)
    score = min(score, 8)

    reasons: list[str] = []
    if title_hits:
        reasons.append("title mentions " + ", ".join(title_hits))
    if label_hits:
        reasons.append("label match: " + ", ".join(label_hits))
    if body_hits:
        reasons.append("body mentions " + ", ".join(body_hits))

    newcomer = next((lab for lab in labels if lab in _NEWCOMER_LABELS), None)
    if newcomer:
        score += 2
        reasons.append(f"labeled '{newcomer}' for newcomers")

    days = _days_since(candidate.get("updated_at") or "")
    if days is not None and days <= _FRESH_DAYS:
        score += 1
        reasons.append("active in the last two weeks")

    comments = int(candidate.get("comments") or 0)
    if comments > _NOISY_COMMENTS:
        score -= 1
        reasons.append(f"busy thread ({comments} comments)")

    claim = candidate.get("claim")
    if claim:
        score -= 2
        reasons.append(f"possibly claimed by @{claim.get('user', 'someone')}")

    if not reasons:
        reasons.append("matched the search query; no direct skill mention in title, labels or body")

    return max(1, min(10, score)), reasons


# An issue untouched for this long is usually hard, abandoned, or both.
_STALE_DAYS = 365
_OLD_DAYS = 180


def estimate_difficulty(candidate: dict[str, Any], skills: list[str]) -> tuple[int, list[str]]:
    """Estimate the effort to *close* an issue, 1-10, with the evidence.

    This is deliberately separate from :func:`score_match`: "fits your skills"
    and "will take a while" are different axes, and the calibration loop
    (``gitsense calibrate``) checks this estimate against how long your own
    closed issues actually took. Signals: newcomer labels and skill overlap
    pull down; noisy threads, staleness and existing claims push up.
    """
    title = (candidate.get("title") or "").lower()
    labels = [str(lab).lower() for lab in candidate.get("labels") or []]

    score = 5
    reasons: list[str] = []

    newcomer = next((lab for lab in labels if lab in _NEWCOMER_LABELS), None)
    if newcomer:
        score -= 2
        reasons.append(f"labeled '{newcomer}' for newcomers")

    title_hits = [s for s in skills if _word_hit(s, title)]
    if title_hits:
        score -= min(2, len(title_hits))
        reasons.append("in your skill area: " + ", ".join(title_hits))

    comments = int(candidate.get("comments") or 0)
    if comments > 50:
        score += 2
        reasons.append(f"very long thread ({comments} comments)")
    elif comments > 20:
        score += 1
        reasons.append(f"long thread ({comments} comments)")

    created = candidate.get("created_at") or candidate.get("updated_at") or ""
    days = _days_since(created)
    if days is not None and days > _STALE_DAYS:
        score += 2
        reasons.append(f"open for over a year ({int(days)}d)")
    elif days is not None and days > _OLD_DAYS:
        score += 1
        reasons.append(f"open for {int(days)}d")

    if candidate.get("claim") or candidate.get("linked_pr"):
        score += 1
        reasons.append("someone may already be on it")

    if not reasons:
        reasons.append("no strong effort signals; assuming a typical issue")

    return max(1, min(10, score)), reasons


def rank_locally(
    candidates: list[dict[str, Any]], skills: list[str], limit: int = 8
) -> list[dict[str, Any]]:
    """Score, explain and sort candidates without touching the network.

    The sort is stable, so ties keep the search API's own ordering. ``limit``
    is a ceiling, not a floor: a small pool returns as-is.
    """
    scored = []
    for candidate in candidates:
        c = candidate.copy()
        score, reasons = score_match(c, skills)
        c["match_score"] = score
        c["reason"] = "; ".join(reasons)
        c["approach"] = ""
        scored.append(c)
    scored.sort(key=lambda c: -c["match_score"])
    return scored[: min(limit, len(scored))]
