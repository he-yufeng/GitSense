"""Watch state for `find --watch`: remember which issues a search already showed.

The state file lives at `.gitsense/watch.json` next to where the command runs.
Each distinct filter signature keeps its own seen-set, so tightening a label
filter does not flush the history of a looser one.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any


def watch_path(root: str = ".") -> str:
    """Where the watch state lives for a working directory."""
    return os.path.join(root, ".gitsense", "watch.json")


def query_key(
    skills: list[str],
    min_stars: int,
    labels: list[str],
    updated_days: int,
    include_assigned: bool,
    include_linked: bool,
    max_comments: int | None,
) -> str:
    """A stable signature for one filter combination, so each keeps its own history."""
    canonical = json.dumps(
        {
            "skills": sorted(s.lower() for s in skills),
            "stars": min_stars,
            "labels": sorted(l.lower() for l in labels),
            "updated_days": updated_days,
            "include_assigned": include_assigned,
            "include_linked": include_linked,
            "max_comments": max_comments,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def load_watch(path: str) -> dict[str, Any]:
    """Load the watch state, tolerating a missing or corrupt file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_watch(state: dict[str, Any], path: str) -> None:
    """Persist the watch state for the next run."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)


def diff_watch(
    state: dict[str, Any], key: str, results: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    """Split results into those not seen before under this filter signature.

    Returns ``(new_results, first_seen_date)``. ``first_seen_date`` is None on
    the first watch of this signature. Only records results; the seen-set grows
    by union, so an issue that vanishes from search results stays seen.
    """
    entry = state.get(key) or {}
    seen = set(entry.get("seen", []))
    first_seen = entry.get("first_seen")
    new = [r for r in results if r.get("url") and r["url"] not in seen]
    seen |= {r["url"] for r in results if r.get("url")}
    state[key] = {"seen": sorted(seen), "first_seen": first_seen or _today()}
    state[key]["last_seen"] = _today()
    return new, first_seen


def _today() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date().isoformat()
