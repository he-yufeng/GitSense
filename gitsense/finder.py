"""Core logic: find and rank open source contribution opportunities."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from openai import OpenAI, OpenAIError

from gitsense.github_client import get_issue_comments, search_issues

# comment phrases that read like someone holding the issue, EN and CN.
# GitHub has no "claimed" state beyond assignment, so people hold issues in
# comments; treat only recent claims as real, since an old "I'll take this"
# that went nowhere should not scare anyone off.
_CLAIM_PHRASES = (
    "i'll work on this", "i will work on this", "i'd like to work on this",
    "i wanna work on this", "let me work on this", "i can take this",
    "i'll take this", "let me take this", "taking this", "working on this",
    "i'm on it", "assign me", "assign this to me",
    "我来", "我认领", "认领这个", "我来做", "交给我",
)


def detect_claims(comments: list[dict], *, days: int = 60) -> dict[str, str] | None:
    """Spot a recent comment that reads like someone claiming the issue."""
    if not comments:
        return None
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    for comment in comments:
        created = (comment.get("created_at") or "")[:10]
        if created and created < cutoff:
            continue
        body = (comment.get("body") or "").lower()
        for phrase in _CLAIM_PHRASES:
            if phrase in body:
                return {
                    "user": (comment.get("user") or {}).get("login", "someone"),
                    "date": created,
                    "phrase": phrase,
                }
    return None


def build_search_queries(
    skills: list[str],
    min_stars: int,
    labels: list[str],
    updated_days: int | None = 180,
    include_assigned: bool = False,
    include_linked: bool = False,
) -> list[str]:
    """Build GitHub search queries from user skills and filters."""
    if not skills:
        raise ValueError("skills must not be empty: pass at least one skill")
    queries = []
    filters = ["is:issue", "is:open", "archived:false"]
    if not include_assigned:
        filters.append("no:assignee")
    if not include_linked:
        # an unassigned issue with a PR already linked is usually taken in
        # practice, even if nobody was formally assigned
        filters.append("-linked:pr")
    if min_stars > 0:
        filters.append(f"stars:>={min_stars}")
    if updated_days is not None:
        if updated_days <= 0:
            raise ValueError(f"updated_days must be greater than zero, got {updated_days}")
        since = datetime.now(timezone.utc).date() - timedelta(days=updated_days)
        filters.append(f"updated:>={since.isoformat()}")
    if labels:
        filters.extend(f'label:"{lab}"' for lab in labels)
    filter_str = " ".join(filters)

    for skill in skills:
        queries.append(f"{skill} {filter_str}")

    # Also search for "good first issue" across skills
    skill_str = " OR ".join(skills[:3])
    queries.append(f'{skill_str} {filter_str} label:"good first issue"')

    return queries


def fetch_candidates(
    skills: list[str],
    min_stars: int = 100,
    labels: list[str] | None = None,
    max_results: int = 30,
    updated_days: int | None = 180,
    max_comments: int | None = None,
    include_assigned: bool = False,
    include_linked: bool = False,
    check_claims: bool = False,
    claim_days: int = 60,
) -> list[dict[str, Any]]:
    """Fetch candidate issues from GitHub."""
    queries = build_search_queries(
        skills,
        min_stars,
        labels or [],
        updated_days=updated_days,
        include_assigned=include_assigned,
        include_linked=include_linked,
    )

    seen_urls = set()
    candidates = []

    for query in queries:
        try:
            issues = search_issues(query, per_page=min(max_results, 20))
        except httpx.HTTPError:
            issues = []

        for issue in issues:
            url = issue.get("html_url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            comments = issue.get("comments", 0)
            if max_comments is not None and comments > max_comments:
                continue

            repo_url = issue.get("repository_url", "")
            repo_name = "/".join(repo_url.split("/")[-2:]) if repo_url else ""

            claim = None
            if check_claims and comments > 0 and repo_name:
                owner, repo = repo_name.split("/", 1)
                try:
                    number = int(url.rstrip("/").rsplit("/", 1)[-1])
                    claim = detect_claims(
                        get_issue_comments(owner, repo, number), days=claim_days
                    )
                except httpx.HTTPError:
                    # claim check is best-effort; never block a result on it
                    claim = None

            candidates.append({
                "title": issue.get("title", ""),
                "url": url,
                "repo": repo_name,
                "labels": [lab["name"] for lab in issue.get("labels", [])],
                "comments": comments,
                "created_at": issue.get("created_at", "")[:10],
                "updated_at": issue.get("updated_at", "")[:10],
                "body": (issue.get("body") or "")[:1000],
                "claim": claim,
            })

    return candidates[:max_results]


def rank_with_llm(
    candidates: list[dict],
    skills: list[str],
    model: str = "gpt-4o-mini",
    api_key: str | None = None,
    base_url: str | None = None,
) -> list[dict]:
    """Use an LLM to rank and explain candidates based on skill match."""
    if not candidates:
        return []

    if base_url is None:
        base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENROUTER_BASE_URL")
    if api_key is None:
        # Key and host must come from the same provider: an OpenAI key on the
        # OpenAI default host, an OpenRouter key on OpenRouter. The previous
        # default sent OPENAI_API_KEY users to OpenRouter, where the key 401s.
        openai_key = os.environ.get("OPENAI_API_KEY")
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        if openai_key:
            api_key = openai_key
        elif openrouter_key:
            api_key = openrouter_key
            if base_url is None:
                base_url = "https://openrouter.ai/api/v1"
    if not api_key:
        # Without LLM, return candidates as-is with no ranking
        for c in candidates:
            c["match_score"] = 5
            c["reason"] = "LLM ranking unavailable (no API key set)"
            c["approach"] = ""
        return candidates[:10]

    client = OpenAI(api_key=api_key, base_url=base_url)

    # Prepare condensed issue list for the LLM
    issue_summaries = []
    for i, c in enumerate(candidates[:20]):
        issue_summaries.append(
            f"[{i}] {c['repo']}: {c['title']} (labels: {', '.join(c['labels'][:3])}) "
            f"comments: {c.get('comments', 0)}, updated: {c.get('updated_at', '')} — "
            f"{c['body'][:200]}"
        )

    prompt = f"""You are an open source contribution advisor. A developer with these skills wants to contribute:
Skills: {', '.join(skills)}

Here are {len(issue_summaries)} open GitHub issues. For each, evaluate:
1. How well it matches the developer's skills (1-10)
2. A one-line reason why it's a good match (or not)
3. A brief approach hint (how to start fixing it)

Respond as a JSON array of objects, sorted by match score descending. Only include the top 8.
Each object: {{"index": <int>, "score": <1-10>, "reason": "<string>", "approach": "<string>"}}

Issues:
{chr(10).join(issue_summaries)}

Respond with ONLY the JSON array."""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2000,
        )
    except (httpx.HTTPError, OpenAIError):
        # Provider errors (auth, quota, network) degrade to the unranked shape
        # instead of killing the whole run.
        for c in candidates[:10]:
            c["match_score"] = 5
            c["reason"] = "LLM ranking unavailable (provider error)"
            c["approach"] = ""
        return candidates[:10]

    content = resp.choices[0].message.content.strip()
    if content.startswith("```"):
        lines = [line for line in content.split("\n") if not line.strip().startswith("```")]
        content = "\n".join(lines)

    try:
        rankings = json.loads(content)
    except json.JSONDecodeError:
        for c in candidates[:10]:
            c["match_score"] = 5
            c["reason"] = "LLM ranking failed"
            c["approach"] = ""
        return candidates[:10]

    # Merge rankings back into candidates
    result = []
    for r in rankings:
        idx = r.get("index", 0)
        if 0 <= idx < len(candidates):
            c = candidates[idx].copy()
            c["match_score"] = r.get("score", 5)
            c["reason"] = r.get("reason", "")
            c["approach"] = r.get("approach", "")
            result.append(c)

    return result
