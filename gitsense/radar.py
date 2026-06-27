"""Repository-level contribution fit scoring."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from gitsense.github_client import (
    get_issue_comments,
    get_repo_info,
    get_repo_languages,
    search_issue_count,
    search_issues,
)

MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
OUTSIDER_ASSOCIATIONS = {"NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER"}


@dataclass
class RepoRadarReport:
    repo: str
    score: int
    recommendation: str
    stars: int
    primary_language: str
    merged_prs: int
    open_prs: int
    stale_prs: int
    stale_ratio: float
    median_merge_days: float | None
    median_maintainer_response_days: float | None
    external_merged_ratio: float | None
    open_to_merged_ratio: float | None = None
    skill_matches: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)


def parse_repo_name(repo: str) -> tuple[str, str]:
    cleaned = repo.strip().removeprefix("https://github.com/").strip("/")
    parts = [part for part in cleaned.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"repo must look like 'owner/name', got: {repo!r}")
    return parts[0], parts[1]


def load_target_repos(path: str | Path) -> list[str]:
    repos: list[str] = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        repos.append(line.split(",", 1)[0].strip())
    return repos


def analyze_repo(
    repo: str,
    *,
    days: int = 90,
    stale_days: int = 14,
    skills: list[str] | None = None,
    sample_size: int = 20,
) -> RepoRadarReport:
    if days <= 0:
        raise ValueError("days must be greater than zero")
    if stale_days <= 0:
        raise ValueError("stale_days must be greater than zero")
    if sample_size <= 0:
        raise ValueError("sample_size must be greater than zero")

    owner, name = parse_repo_name(repo)
    full_name = f"{owner}/{name}"
    since = date.today() - timedelta(days=days)
    stale_before = date.today() - timedelta(days=stale_days)

    repo_info = get_repo_info(owner, name)
    languages = get_repo_languages(owner, name)
    primary_language = next(iter(languages.keys()), repo_info.get("language") or "unknown")

    merged_query = f"repo:{full_name} is:pr is:merged merged:>={since.isoformat()}"
    open_query = f"repo:{full_name} is:pr is:open"
    stale_query = f"repo:{full_name} is:pr is:open created:<{stale_before.isoformat()}"

    merged_count = search_issue_count(merged_query)
    open_count = search_issue_count(open_query)
    stale_count = search_issue_count(stale_query)

    merged_sample = search_issues(
        merged_query,
        sort="updated",
        order="desc",
        per_page=min(sample_size, 100),
    )

    merge_days = [
        _days_between(item.get("created_at"), item.get("closed_at"))
        for item in merged_sample
        if item.get("created_at") and item.get("closed_at")
    ]
    merge_days = [value for value in merge_days if value is not None]

    response_days = _sample_maintainer_response_days(owner, name, merged_sample[:10])
    external_ratio = _external_ratio(merged_sample)
    skill_matches = _match_skills(repo_info, languages, skills or [])
    stale_ratio = (stale_count / open_count) if open_count else 0.0
    open_to_merged_ratio = (open_count / merged_count) if merged_count else None

    score, notes = score_repo(
        merged_prs=merged_count,
        open_prs=open_count,
        stale_ratio=stale_ratio,
        median_merge_days=median(merge_days) if merge_days else None,
        median_maintainer_response_days=median(response_days) if response_days else None,
        external_merged_ratio=external_ratio,
        skill_matches=skill_matches,
        stars=int(repo_info.get("stargazers_count") or 0),
    )
    risk_flags = risk_flags_for_repo(
        merged_prs=merged_count,
        open_prs=open_count,
        stale_ratio=stale_ratio,
        median_merge_days=median(merge_days) if merge_days else None,
        median_maintainer_response_days=median(response_days) if response_days else None,
        external_merged_ratio=external_ratio,
    )

    return RepoRadarReport(
        repo=full_name,
        score=score,
        recommendation=recommendation_for_score(score),
        stars=int(repo_info.get("stargazers_count") or 0),
        primary_language=primary_language,
        merged_prs=merged_count,
        open_prs=open_count,
        stale_prs=stale_count,
        stale_ratio=stale_ratio,
        median_merge_days=median(merge_days) if merge_days else None,
        median_maintainer_response_days=median(response_days) if response_days else None,
        external_merged_ratio=external_ratio,
        open_to_merged_ratio=open_to_merged_ratio,
        skill_matches=skill_matches,
        notes=notes,
        risk_flags=risk_flags,
    )


def score_repo(
    *,
    merged_prs: int,
    open_prs: int,
    stale_ratio: float,
    median_merge_days: float | None,
    median_maintainer_response_days: float | None,
    external_merged_ratio: float | None,
    skill_matches: list[str],
    stars: int,
) -> tuple[int, list[str]]:
    score = 50
    notes: list[str] = []

    if merged_prs >= 30:
        score += 15
        notes.append("active merge history")
    elif merged_prs >= 10:
        score += 8
        notes.append("some recent merges")
    elif merged_prs == 0:
        score -= 18
        notes.append("no recent merged PRs")

    if median_merge_days is not None:
        if median_merge_days <= 7:
            score += 14
            notes.append("fast median merge time")
        elif median_merge_days <= 21:
            score += 6
            notes.append("reasonable median merge time")
        elif median_merge_days > 45:
            score -= 12
            notes.append("slow median merge time")

    if stale_ratio >= 0.5 and open_prs:
        score -= 24
        notes.append("many stale open PRs")
    elif stale_ratio >= 0.25:
        score -= 12
        notes.append("noticeable stale PR backlog")
    elif open_prs:
        score += 6
        notes.append("stale PR ratio looks manageable")

    if median_maintainer_response_days is not None:
        if median_maintainer_response_days <= 3:
            score += 10
            notes.append("maintainers respond quickly")
        elif median_maintainer_response_days <= 10:
            score += 4
            notes.append("maintainer response time is acceptable")
        elif median_maintainer_response_days > 21:
            score -= 10
            notes.append("maintainer responses look slow")

    if external_merged_ratio is not None:
        if external_merged_ratio >= 0.5:
            score += 10
            notes.append("outside contributors are getting merged")
        elif external_merged_ratio < 0.2:
            score -= 8
            notes.append("recent merged PRs are mostly internal")

    if open_prs >= 100 and merged_prs < 10:
        score -= 10
        notes.append("open PR queue is much larger than recent merge volume")
    elif open_prs >= 50 and merged_prs < 5:
        score -= 8
        notes.append("crowded open PR queue")

    if skill_matches:
        score += min(10, len(skill_matches) * 3)
        notes.append(f"matches skills: {', '.join(skill_matches[:4])}")

    if stars >= 10_000:
        score += 5
    elif stars >= 1_000:
        score += 3

    return max(0, min(100, score)), notes


def risk_flags_for_repo(
    *,
    merged_prs: int,
    open_prs: int,
    stale_ratio: float,
    median_merge_days: float | None,
    median_maintainer_response_days: float | None,
    external_merged_ratio: float | None,
) -> list[str]:
    flags: list[str] = []

    if merged_prs == 0:
        flags.append("no recent merges")
    if open_prs >= 100 and stale_ratio >= 0.25:
        flags.append("crowded stale PR queue")
    elif open_prs >= 75:
        flags.append("large open PR queue")
    if median_merge_days is not None and median_merge_days > 45:
        flags.append("slow merge time")
    if median_maintainer_response_days is not None and median_maintainer_response_days > 21:
        flags.append("slow maintainer response")
    if external_merged_ratio is not None and external_merged_ratio < 0.2:
        flags.append("mostly internal recent merges")

    return flags


def recommendation_for_score(score: int) -> str:
    if score >= 75:
        return "Go"
    if score >= 60:
        return "Watch"
    if score >= 45:
        return "Comment first"
    return "Avoid for now"


def render_markdown(reports: list[RepoRadarReport]) -> str:
    lines = [
        "# GitSense Radar Report",
        "",
        "| Repo | Score | Action | Merged PRs | Open PRs | Stale PRs | Open/Merged | Median merge | Maintainer response |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for report in reports:
        lines.append(
            "| "
            f"{report.repo} | {report.score} | {report.recommendation} | "
            f"{report.merged_prs} | {report.open_prs} | {report.stale_prs} | "
            f"{_fmt_ratio(report.open_to_merged_ratio)} | "
            f"{_fmt_days(report.median_merge_days)} | "
            f"{_fmt_days(report.median_maintainer_response_days)} |"
        )
    lines.append("")

    for report in reports:
        lines.extend(
            [
                f"## {report.repo}",
                "",
                f"- Score: `{report.score}`",
                f"- Recommendation: `{report.recommendation}`",
                f"- Stars: `{report.stars}`",
                f"- Primary language: `{report.primary_language}`",
                f"- External merged ratio: `{_fmt_percent(report.external_merged_ratio)}`",
            ]
        )
        if report.skill_matches:
            lines.append(f"- Skill matches: `{', '.join(report.skill_matches)}`")
        if report.notes:
            lines.append(f"- Signals: {', '.join(report.notes)}")
        if report.risk_flags:
            lines.append(f"- Risk flags: {', '.join(report.risk_flags)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_json(reports: list[RepoRadarReport]) -> str:
    return json.dumps([asdict(report) for report in reports], indent=2, ensure_ascii=False) + "\n"


def _sample_maintainer_response_days(
    owner: str,
    repo: str,
    pull_requests: list[dict[str, Any]],
) -> list[float]:
    values: list[float] = []
    for item in pull_requests:
        number = _number_from_url(item.get("html_url", ""))
        if number is None:
            continue
        created_at = item.get("created_at")
        try:
            comments = get_issue_comments(owner, repo, number)
        except Exception:
            continue
        maintainer_comments = [
            comment
            for comment in comments
            if comment.get("author_association") in MAINTAINER_ASSOCIATIONS
        ]
        if not maintainer_comments:
            continue
        first_comment = min(maintainer_comments, key=lambda comment: comment.get("created_at", ""))
        value = _days_between(created_at, first_comment.get("created_at"))
        if value is not None and value >= 0:
            values.append(value)
    return values


def _external_ratio(pull_requests: list[dict[str, Any]]) -> float | None:
    if not pull_requests:
        return None
    external = sum(
        1
        for item in pull_requests
        if item.get("author_association") in OUTSIDER_ASSOCIATIONS
    )
    return external / len(pull_requests)


def _match_skills(
    repo_info: dict[str, Any],
    languages: dict[str, int],
    skills: list[str],
) -> list[str]:
    if not skills:
        return []
    haystack = " ".join(
        [
            str(repo_info.get("full_name") or ""),
            str(repo_info.get("description") or ""),
            " ".join(repo_info.get("topics") or []),
            " ".join(languages.keys()),
        ]
    ).lower()
    matches = []
    for skill in skills:
        needle = skill.strip().lower()
        # Match the skill as a whole token, not a bare substring: otherwise a
        # short language name floods false positives ("Go" in "Google", "C" in
        # "category", and single letters match almost any description).
        if needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
            matches.append(skill.strip())
    return matches


def _days_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    start_dt = _parse_github_time(start)
    end_dt = _parse_github_time(end)
    return (end_dt - start_dt).total_seconds() / 86400


def _parse_github_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _number_from_url(url: str) -> int | None:
    try:
        return int(url.rstrip("/").split("/")[-1])
    except ValueError:
        return None


def _fmt_days(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value < 1:
        return "<1d"
    return f"{value:.1f}d"


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.0f}%"


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}x"
