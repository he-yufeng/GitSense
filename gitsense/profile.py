"""Infer a contributor's skill profile from their public GitHub repos.

The ``find`` command needs skills to seed its search, and making people type
them out is friction: your public repos already say what you work in. This
module reads them and turns the primary-language field into a weighted skill
list, where a language you clearly build serious things in outranks one from
a weekend toy.

The weighting is intentionally simple and honest: each repo contributes its
language once, scaled by ``1 + log10(stars + 1)`` so that a proven repo
counts for more than a fork nobody uses, and capped so one giant cannot
drown everything else. Forks are skipped entirely (they say what you read,
not what you write).
"""

from __future__ import annotations

import math
from typing import Any

from gitsense.github_client import fetch_user_repos

_MAX_REPOS = 100
# a repo this starred (or more) hits the weight ceiling, so extremely
# popular projects do not flatten everything else
_STARS_FOR_MAX_WEIGHT = 1000


def _repo_weight(repo: dict[str, Any]) -> float:
    stars = int(repo.get("stargazers_count") or 0)
    capped = min(stars, _STARS_FOR_MAX_WEIGHT)
    return 1.0 + math.log10(capped + 1)


def infer_skills(username: str, *, max_repos: int = _MAX_REPOS) -> dict[str, Any]:
    """Infer a weighted skill list from a user's public repos.

    Returns a dict with ``languages`` (``[(language, weight)]`` sorted most
    weighted first), ``top`` (just the names), ``repo_count`` (how many
    non-fork repos went in), and ``skipped_forks``.
    """
    repos = fetch_user_repos(username, per_page=min(max_repos, 100))
    weights: dict[str, float] = {}
    repo_count = 0
    skipped_forks = 0
    for repo in repos[:max_repos]:
        if repo.get("fork"):
            skipped_forks += 1
            continue
        language = repo.get("language")
        if not language:
            continue
        repo_count += 1
        weights[language] = weights.get(language, 0.0) + _repo_weight(repo)

    ranked = sorted(weights.items(), key=lambda item: item[1], reverse=True)
    return {
        "languages": [(lang, round(w, 2)) for lang, w in ranked],
        "top": [lang for lang, _ in ranked],
        "repo_count": repo_count,
        "skipped_forks": skipped_forks,
    }
