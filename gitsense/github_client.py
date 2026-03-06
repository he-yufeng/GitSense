"""GitHub API client for searching issues and repos."""

from __future__ import annotations

import os
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"


def _get_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def search_issues(
    query: str,
    sort: str = "created",
    order: str = "desc",
    per_page: int = 30,
) -> list[dict[str, Any]]:
    """Search GitHub issues matching a query string.

    Uses the GitHub Search API:
    https://docs.github.com/en/rest/search/search#search-issues-and-pull-requests
    """
    resp = httpx.get(
        f"{GITHUB_API}/search/issues",
        params={"q": query, "sort": sort, "order": order, "per_page": per_page},
        headers=_get_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def get_repo_info(owner: str, repo: str) -> dict[str, Any]:
    """Get repository metadata."""
    resp = httpx.get(
        f"{GITHUB_API}/repos/{owner}/{repo}",
        headers=_get_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_repo_languages(owner: str, repo: str) -> dict[str, int]:
    """Get language breakdown for a repo."""
    resp = httpx.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/languages",
        headers=_get_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
