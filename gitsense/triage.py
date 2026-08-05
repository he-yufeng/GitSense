"""Triage every open PR you have across GitHub, in one table.

``predict`` answers "will this one PR merge". This answers the question you
actually have once a few dozen PRs are in flight: which of *my* open PRs need
me today, and what do they need. The search API gives the list; each PR is
then enriched with the same signals ``predict`` uses (review decision, CI,
conflicts, diff size) and collapsed into a single next action. Rows sort
worst-first so the top of the table is your todo list.

The scoring reuses :func:`gitsense.predictor.score_pr`; everything new here —
:func:`next_action` and :func:`build_row` — is pure so it can be tested
without network access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from gitsense.predictor import analyze_pr

_ACTION_READY = "approved & green — nudge for merge"
_ACTION_WAIT = "waiting on reviewer"


@dataclass
class TriageRow:
    repo: str
    number: int
    title: str
    url: str
    action: str
    score: int | None = None
    age_days: float = 0.0
    updated_days: float = 0.0
    draft: bool = False
    notes: list[str] = field(default_factory=list)


def _days_since(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - when).total_seconds() / 86400)


def next_action(
    *,
    review_decision: str | None,
    is_draft: bool,
    mergeable_state: str | None,
    ci_failing: bool,
    updated_days: float,
    stale_days: int,
) -> str:
    """Collapse a PR's state into the one thing you should do next.

    Ordered by what unblocks the merge fastest: you can't do anything about a
    reviewer until the draft flag, requested changes, red CI and conflicts are
    out of the way.
    """
    if is_draft:
        return "mark ready for review"
    if (review_decision or "").upper() == "CHANGES_REQUESTED":
        return "address the review"
    if ci_failing:
        return "fix CI"
    if (mergeable_state or "").upper() in {"DIRTY", "CONFLICTING"}:
        return "rebase to clear conflicts"
    if (review_decision or "").upper() == "APPROVED":
        return _ACTION_READY
    if updated_days >= stale_days:
        return f"no review in {int(updated_days)}d — ping"
    return _ACTION_WAIT


def build_row(
    item: dict[str, Any],
    *,
    pr: dict[str, Any] | None = None,
    review_decision: str | None = None,
    ci_failing: bool = False,
    touches_tests: bool = False,
    stale_days: int = 14,
) -> TriageRow:
    """Build one triage row.

    ``item`` is a search-API issue item (has draft/created_at/updated_at).
    ``pr`` is the full pulls payload from enrichment; without it the row is
    shallow — no score, action derived from search signals only.
    """
    repo = (item.get("repository_url") or "").rsplit("/", 2)[-2:]
    repo_name = "/".join(repo) if len(repo) == 2 else "?"
    draft = bool(item.get("draft", False))
    updated_days = _days_since(item.get("updated_at"))

    score: int | None = None
    notes: list[str] = []
    decision = review_decision
    mergeable = None
    if pr is not None:
        prediction = analyze_pr(
            pr,
            review_decision=review_decision,
            ci_failing=ci_failing,
            touches_tests=touches_tests,
        )
        score = prediction.score
        notes = prediction.notes
        mergeable = pr.get("mergeable_state")
    else:
        # shallow mode: no per-PR calls, so reviews/CI are unknown
        decision = None

    return TriageRow(
        repo=repo_name,
        number=int(item.get("number", 0) or 0),
        title=item.get("title") or "",
        url=item.get("html_url") or "",
        action=next_action(
            review_decision=decision,
            is_draft=draft,
            mergeable_state=mergeable,
            ci_failing=ci_failing if pr is not None else False,
            updated_days=updated_days,
            stale_days=stale_days,
        ),
        score=score,
        age_days=_days_since(item.get("created_at")),
        updated_days=updated_days,
        draft=draft,
        notes=notes,
    )


def sort_rows(rows: list[TriageRow]) -> list[TriageRow]:
    """Worst first: low score, then longest since last activity. Unscored last."""
    return sorted(
        rows,
        key=lambda r: (r.score is None, r.score if r.score is not None else 0, -r.updated_days),
    )


def fetch_authored_prs(username: str, limit: int) -> list[dict[str, Any]]:
    """Search GitHub for open PRs authored by the user, most recently active first."""
    from gitsense.github_client import search_issues

    return search_issues(
        f"is:pr is:open author:{username}",
        sort="updated",
        order="desc",
        per_page=min(limit, 100),
    )


def enrich_row(
    row_item: dict[str, Any],
    *,
    stale_days: int = 14,
) -> TriageRow:
    """Build a row with per-PR API calls (review decision, CI, files)."""
    from gitsense import github_client
    from gitsense.predictor import derive_review_decision, files_touch_tests

    repo = (row_item.get("repository_url") or "").rsplit("/", 2)[-2:]
    owner, name = repo[0], repo[1]
    number = int(row_item["number"])
    pr = github_client.get_pull_request(owner, name, number)
    reviews = github_client.get_pull_request_reviews(owner, name, number)
    files = github_client.get_pull_request_files(owner, name, number)
    head_sha = (pr.get("head") or {}).get("sha") or ""
    ci_state = github_client.get_commit_status_state(owner, name, head_sha) if head_sha else ""
    return build_row(
        row_item,
        pr=pr,
        review_decision=derive_review_decision(reviews),
        ci_failing=(ci_state == "failure"),
        touches_tests=files_touch_tests(files),
        stale_days=stale_days,
    )


# ---------------------------------------------------------------------------
# --since-last: snapshot diffing
# ---------------------------------------------------------------------------


def snapshot_path(root: str = ".") -> str:
    """Where the last triage snapshot lives for a working directory."""
    import os

    return os.path.join(root, ".gitsense", "triage-last.json")


def load_snapshot(path: str) -> list[dict[str, Any]]:
    """Load the previous snapshot, tolerating a missing or corrupt file."""
    import json
    import os

    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_snapshot(rows: list[TriageRow], path: str) -> None:
    """Persist today's rows so the next run can diff against them."""
    import json
    import os
    from dataclasses import asdict as _asdict

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([_asdict(r) for r in rows], fh, indent=1)


def diff_snapshots(
    old: list[dict[str, Any]], new_rows: list[TriageRow]
) -> dict[str, list[dict[str, Any]]]:
    """Diff a previous snapshot against today's rows.

    Returns ``{"new", "changed", "gone"}``:

    - ``new``: PRs that were not open (or not triaged) last time.
    - ``changed``: PRs whose next action moved, e.g. "fix CI" to "waiting on
      reviewer" after your push. Action text is what you act on, so score
      drift alone does not count as a change.
    - ``gone``: PRs no longer open, with the last recorded action for context.
    """
    old_by_key = {(o.get("repo"), o.get("number")): o for o in old}
    new_by_key = {(r.repo, r.number): r for r in new_rows}

    added = [
        {"repo": r.repo, "number": r.number, "title": r.title, "action": r.action, "url": r.url}
        for key, r in new_by_key.items()
        if key not in old_by_key
    ]
    changed = []
    for key, r in new_by_key.items():
        prev = old_by_key.get(key)
        if prev is None or prev.get("action") == r.action:
            continue
        changed.append(
            {
                "repo": r.repo,
                "number": r.number,
                "title": r.title,
                "was": prev.get("action") or "?",
                "now": r.action,
                "url": r.url,
            }
        )
    gone = [
        {
            "repo": o.get("repo"),
            "number": o.get("number"),
            "title": o.get("title") or "",
            "was": o.get("action") or "?",
            "url": o.get("url") or "",
        }
        for key, o in old_by_key.items()
        if key not in new_by_key
    ]
    return {"new": added, "changed": changed, "gone": gone}
