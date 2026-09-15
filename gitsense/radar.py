"""Repository-level contribution fit scoring."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

import httpx

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
class ScoreFactor:
    """One scored signal: the metric, the points it moved, and why.

    The scorecard is what makes a score trustworthy: every factor shows its
    number, not just a label. ``reason`` stays empty for factors that did not
    adjust the score, so derived notes match the historical plain list.
    """

    key: str
    label: str
    value: str
    delta: int
    reason: str = ""


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
    factors: list[ScoreFactor] = field(default_factory=list)


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
    since = datetime.now(timezone.utc).date() - timedelta(days=days)
    stale_before = datetime.now(timezone.utc).date() - timedelta(days=stale_days)

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

    score, factors = scorecard_repo(
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
        notes=[factor.reason for factor in factors if factor.reason],
        risk_flags=risk_flags,
        factors=factors,
    )


def scorecard_repo(
    *,
    merged_prs: int,
    open_prs: int,
    stale_ratio: float,
    median_merge_days: float | None,
    median_maintainer_response_days: float | None,
    external_merged_ratio: float | None,
    skill_matches: list[str],
    stars: int,
) -> tuple[int, list[ScoreFactor]]:
    """Score a repo and lay the card face up: every factor with its number."""
    factors: list[ScoreFactor] = []

    merge_value = f"{merged_prs} merged"
    if merged_prs >= 30:
        factors.append(ScoreFactor("merge_activity", "Merge activity", merge_value, 15, "active merge history"))
    elif merged_prs >= 10:
        factors.append(ScoreFactor("merge_activity", "Merge activity", merge_value, 8, "some recent merges"))
    elif merged_prs == 0:
        factors.append(ScoreFactor("merge_activity", "Merge activity", merge_value, -18, "no recent merged PRs"))
    else:
        factors.append(ScoreFactor("merge_activity", "Merge activity", merge_value, 0))

    merge_days_value = _fmt_days(median_merge_days)
    if median_merge_days is not None:
        if median_merge_days <= 7:
            factors.append(ScoreFactor("merge_speed", "Median merge time", merge_days_value, 14, "fast median merge time"))
        elif median_merge_days <= 21:
            factors.append(ScoreFactor("merge_speed", "Median merge time", merge_days_value, 6, "reasonable median merge time"))
        elif median_merge_days > 45:
            factors.append(ScoreFactor("merge_speed", "Median merge time", merge_days_value, -12, "slow median merge time"))
        else:
            factors.append(ScoreFactor("merge_speed", "Median merge time", merge_days_value, 0))
    else:
        factors.append(ScoreFactor("merge_speed", "Median merge time", merge_days_value, 0))

    stale_value = f"{stale_ratio:.0%} of {open_prs} open"
    if stale_ratio >= 0.5 and open_prs:
        factors.append(ScoreFactor("stale_backlog", "Stale PR backlog", stale_value, -24, "many stale open PRs"))
    elif stale_ratio >= 0.25:
        factors.append(ScoreFactor("stale_backlog", "Stale PR backlog", stale_value, -12, "noticeable stale PR backlog"))
    elif open_prs:
        factors.append(ScoreFactor("stale_backlog", "Stale PR backlog", stale_value, 6, "stale PR ratio looks manageable"))
    else:
        factors.append(ScoreFactor("stale_backlog", "Stale PR backlog", stale_value, 0))

    response_value = _fmt_days(median_maintainer_response_days)
    if median_maintainer_response_days is not None:
        if median_maintainer_response_days <= 3:
            factors.append(ScoreFactor("maintainer_response", "Maintainer response", response_value, 10, "maintainers respond quickly"))
        elif median_maintainer_response_days <= 10:
            factors.append(ScoreFactor("maintainer_response", "Maintainer response", response_value, 4, "maintainer response time is acceptable"))
        elif median_maintainer_response_days > 21:
            factors.append(ScoreFactor("maintainer_response", "Maintainer response", response_value, -10, "maintainer responses look slow"))
        else:
            factors.append(ScoreFactor("maintainer_response", "Maintainer response", response_value, 0))
    else:
        factors.append(ScoreFactor("maintainer_response", "Maintainer response", response_value, 0))

    external_value = _fmt_percent(external_merged_ratio)
    if external_merged_ratio is not None:
        if external_merged_ratio >= 0.5:
            factors.append(ScoreFactor("external_share", "External merged share", external_value, 10, "outside contributors are getting merged"))
        elif external_merged_ratio < 0.2:
            factors.append(ScoreFactor("external_share", "External merged share", external_value, -8, "recent merged PRs are mostly internal"))
        else:
            factors.append(ScoreFactor("external_share", "External merged share", external_value, 0))
    else:
        factors.append(ScoreFactor("external_share", "External merged share", external_value, 0))

    queue_value = f"{open_prs} open vs {merged_prs} merged"
    if open_prs >= 100 and merged_prs < 10:
        factors.append(ScoreFactor("queue_pressure", "Open queue pressure", queue_value, -10, "open PR queue is much larger than recent merge volume"))
    elif open_prs >= 50 and merged_prs < 5:
        factors.append(ScoreFactor("queue_pressure", "Open queue pressure", queue_value, -8, "crowded open PR queue"))
    else:
        factors.append(ScoreFactor("queue_pressure", "Open queue pressure", queue_value, 0))

    if skill_matches:
        factors.append(
            ScoreFactor(
                "skill_fit",
                "Skill fit",
                ", ".join(skill_matches[:4]),
                min(10, len(skill_matches) * 3),
                f"matches skills: {', '.join(skill_matches[:4])}",
            )
        )
    else:
        factors.append(ScoreFactor("skill_fit", "Skill fit", "none", 0))

    stars_value = f"{stars:,}"
    if stars >= 10_000:
        factors.append(ScoreFactor("stars", "Stars", stars_value, 5))
    elif stars >= 1_000:
        factors.append(ScoreFactor("stars", "Stars", stars_value, 3))
    else:
        factors.append(ScoreFactor("stars", "Stars", stars_value, 0))

    score = 50 + sum(factor.delta for factor in factors)
    return max(0, min(100, score)), factors


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
    """Backward-compatible (score, notes) form of scorecard_repo()."""
    score, factors = scorecard_repo(
        merged_prs=merged_prs,
        open_prs=open_prs,
        stale_ratio=stale_ratio,
        median_merge_days=median_merge_days,
        median_maintainer_response_days=median_maintainer_response_days,
        external_merged_ratio=external_merged_ratio,
        skill_matches=skill_matches,
        stars=stars,
    )
    return score, [factor.reason for factor in factors if factor.reason]


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
        if report.factors:
            lines.extend(
                [
                    "",
                    "| Factor | Value | Points | Why |",
                    "| --- | ---: | ---: | --- |",
                ]
            )
            for factor in report.factors:
                points = f"+{factor.delta}" if factor.delta > 0 else str(factor.delta)
                lines.append(f"| {factor.label} | {factor.value} | {points} | {factor.reason or '·'} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_html(reports: list[RepoRadarReport]) -> str:
    """Render radar reports as a self-contained, email-friendly HTML report.

    Inline styles only, no external assets: the score table and per-repo
    signal lists render the same in Gmail/Outlook as in a browser.
    """
    from html import escape

    def esc(value) -> str:
        return escape(str(value), quote=True)

    rows = "".join(
        "<tr>"
        f'<td style="padding:6px 10px;border-bottom:1px solid #e1e4e8">{esc(r.repo)}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #e1e4e8;text-align:right">'
        f"<b>{esc(r.score)}</b></td>"
        f'<td style="padding:6px 10px;border-bottom:1px solid #e1e4e8">{esc(r.recommendation)}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #e1e4e8;text-align:right">{esc(r.merged_prs)}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #e1e4e8;text-align:right">{esc(r.open_prs)}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #e1e4e8;text-align:right">{esc(r.stale_prs)}</td>'
        "</tr>"
        for r in reports
    )
    head_cell = (
        'style="padding:6px 10px;border-bottom:2px solid #24292e;'
        'text-align:left;font-size:12px;color:#6a737d"'
    )
    details: list[str] = []
    for r in reports:
        facts = [
            f"Stars: {esc(r.stars)}",
            f"Primary language: {esc(r.primary_language)}",
            f"External merged ratio: {esc(_fmt_percent(r.external_merged_ratio))}",
        ]
        if r.skill_matches:
            facts.append(f"Skill matches: {esc(', '.join(r.skill_matches))}")
        if r.notes:
            facts.append(f"Signals: {esc(', '.join(r.notes))}")
        if r.risk_flags:
            facts.append(
                f'<span style="color:#b31d28">Risk flags: {esc(", ".join(r.risk_flags))}</span>'
            )
        details.append(
            f'<div style="border:1px solid #e1e4e8;border-radius:6px;padding:10px 14px;margin:10px 0">'
            f'<div style="font-size:14px"><b>{esc(r.repo)}</b> '
            f'<span style="color:#6a737d;font-size:12px">· {esc(r.score)} · {esc(r.recommendation)}</span></div>'
            f'<div style="color:#444d56;font-size:13px;margin-top:6px">{"<br>".join(facts)}</div>'
            f"</div>"
        )
    return (
        "<!DOCTYPE html>\n"
        '<html><body style="margin:0;padding:16px;background:#ffffff;font-family:'
        "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif\">"
        '<div style="max-width:720px;margin:0 auto">'
        '<h2 style="margin:0 0 8px 0;font-size:18px;color:#24292e">GitSense Radar Report</h2>'
        '<table style="border-collapse:collapse;width:100%;font-size:13px">'
        f"<thead><tr><th {head_cell}>Repo</th><th {head_cell}>Score</th><th {head_cell}>Action</th>"
        f"<th {head_cell}>Merged</th><th {head_cell}>Open</th><th {head_cell}>Stale</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        + "".join(details)
        + "</div></body></html>\n"
    )


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
        except httpx.HTTPError:
            comments = []
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
