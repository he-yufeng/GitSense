"""Core logic: find and rank open source contribution opportunities."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any

from openai import OpenAI

from gitsense.github_client import search_issues


def build_search_queries(
    skills: list[str],
    min_stars: int,
    labels: list[str],
    updated_days: int | None = 180,
    include_assigned: bool = False,
) -> list[str]:
    """Build GitHub search queries from user skills and filters."""
    if not skills:
        raise ValueError("skills must not be empty: pass at least one skill")
    queries = []
    filters = ["is:issue", "is:open", "archived:false"]
    if not include_assigned:
        filters.append("no:assignee")
    if min_stars > 0:
        filters.append(f"stars:>={min_stars}")
    if updated_days is not None:
        if updated_days <= 0:
            raise ValueError(f"updated_days must be greater than zero, got {updated_days}")
        since = date.today() - timedelta(days=updated_days)
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
) -> list[dict[str, Any]]:
    """Fetch candidate issues from GitHub."""
    queries = build_search_queries(
        skills,
        min_stars,
        labels or [],
        updated_days=updated_days,
        include_assigned=include_assigned,
    )

    seen_urls = set()
    candidates = []

    for query in queries:
        try:
            issues = search_issues(query, per_page=min(max_results, 20))
        except Exception:
            continue

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

            candidates.append({
                "title": issue.get("title", ""),
                "url": url,
                "repo": repo_name,
                "labels": [lab["name"] for lab in issue.get("labels", [])],
                "comments": comments,
                "created_at": issue.get("created_at", "")[:10],
                "updated_at": issue.get("updated_at", "")[:10],
                "body": (issue.get("body") or "")[:1000],
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

    api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    base_url = base_url or os.environ.get("OPENAI_BASE_URL") or os.environ.get(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
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

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2000,
    )

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
