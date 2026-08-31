"""GitHub API client for searching issues and repos."""

from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"


def _gh_cli_token() -> str | None:
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


@lru_cache(maxsize=1)
def _get_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    token = _gh_cli_token()
    if token:
        print("gitsense: using GitHub token from the gh CLI", file=sys.stderr)
    return token


def _get_headers() -> dict[str, str]:
    token = _get_token()
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


def search_issue_count(query: str) -> int:
    """Return the total count for a GitHub issue/PR search."""
    resp = httpx.get(
        f"{GITHUB_API}/search/issues",
        params={"q": query, "per_page": 1},
        headers=_get_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return int(resp.json().get("total_count", 0))


def get_repo_info(owner: str, repo: str) -> dict[str, Any]:
    """Get repository metadata."""
    resp = httpx.get(
        f"{GITHUB_API}/repos/{owner}/{repo}",
        headers=_get_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_issue_comments(owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    """Get issue comments for a GitHub issue or pull request number."""
    resp = httpx.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/issues/{number}/comments",
        params={"per_page": 100},
        headers=_get_headers(),
        timeout=30,
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


def get_pull_request(owner: str, repo: str, number: int) -> dict[str, Any]:
    """Get a single pull request (draft, additions, changed_files, mergeable_state, ...)."""
    resp = httpx.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}",
        headers=_get_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_pull_request_files(owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    """List the files changed by a pull request."""
    resp = httpx.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/files",
        params={"per_page": 100},
        headers=_get_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_pull_request_reviews(owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    """List the reviews on a pull request."""
    resp = httpx.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/reviews",
        params={"per_page": 100},
        headers=_get_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_commit_status_state(owner: str, repo: str, ref: str) -> str:
    """Combined CI status for a commit: 'success', 'failure', 'pending', or ''."""
    resp = httpx.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/commits/{ref}/status",
        headers=_get_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("state", "")


def fetch_user_repos(username: str, per_page: int = 100) -> list[dict[str, Any]]:
    """List a user's public repos, most recently pushed first."""
    resp = httpx.get(
        f"{GITHUB_API}/users/{username}/repos",
        params={"per_page": per_page, "sort": "pushed", "type": "owner"},
        headers=_get_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
