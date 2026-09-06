"""CLI for GitSense."""

from __future__ import annotations

import json
from dataclasses import asdict

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from gitsense import __version__

console = Console()


@click.group()
@click.version_option(__version__, prog_name="gitsense")
def main():
    """GitSense — find contribution targets and check repo fit."""


@main.command()
@click.option("--skills", "-s", default="", help="Your skills, comma-separated (e.g. python,cuda,llm)")
@click.option("--profile", "profile_user", default="", help="Infer skills from a GitHub username's public repos")
@click.option("--stars", default=100, help="Minimum repo stars (default: 100)")
@click.option("--labels", "-l", default="", help="Filter by labels, comma-separated (e.g. bug,good first issue)")
@click.option("--model", "-m", default="gpt-4o-mini", help="LLM model for ranking")
@click.option("--api-key", "-k", envvar="OPENAI_API_KEY", help="LLM API key")
@click.option("--no-llm", is_flag=True, help="Skip LLM ranking, just show raw results")
@click.option("--limit", "-n", default=8, help="Number of results to show")
@click.option(
    "--updated-days",
    default=180,
    show_default=True,
    help="Only show issues updated within this many days",
)
@click.option("--max-comments", type=int, help="Skip noisy issues with more than this many comments")
@click.option("--include-assigned", is_flag=True, help="Include issues that already have assignees")
@click.option("--include-linked", is_flag=True, help="Include issues that already have linked PRs")
@click.option(
    "--check-claims",
    is_flag=True,
    help="Also scan comments for people claiming the issue (one API call per issue)",
)
@click.option(
    "--watch",
    is_flag=True,
    help="Digest mode: show only issues not seen by an earlier --watch run with the same filters",
)
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
@click.option("--out", type=click.Path(dir_okay=False), help="Write a report file")
@click.option(
    "--state-dir",
    default=None,
    help="Directory for --watch state (default: ~/.gitsense)",
)
def find(skills: str, profile_user: str, stars: int, labels: str, model: str, api_key: str | None,
         no_llm: bool, limit: int, updated_days: int, max_comments: int | None,
         include_assigned: bool, include_linked: bool, check_claims: bool, watch: bool,
         fmt: str, out: str | None, state_dir: str | None):
    """Find open issues that match your skills.

    \b
    Examples:
        gitsense find --skills python,llm,cuda
        gitsense find --profile torvalds
        gitsense find --skills rust,wasm --stars 500
        gitsense find --skills python --labels bug --no-llm
        gitsense find --skills python,llm --updated-days 30 --max-comments 10
        gitsense find --skills python,llm --format json --out results.json
    """
    from gitsense.finder import SearchError, fetch_candidates, rank_with_llm

    skill_list = [s.strip() for s in skills.split(",") if s.strip()]
    if profile_user:
        from gitsense.profile import infer_skills

        with console.status(f"[bold blue]Inferring skills from @{profile_user}'s repos..."):
            profile = infer_skills(profile_user)
        if not profile["top"]:
            raise click.UsageError(
                f"could not infer any skills from @{profile_user}: "
                "no non-fork public repos with a primary language"
            )
        inferred = [lang for lang in profile["top"] if lang not in skill_list]
        skill_list.extend(inferred)
        console.print(
            f"[dim]Inferred from {profile['repo_count']} repos: "
            f"{', '.join(profile['top'][:6])}[/dim]"
        )
    if not skill_list:
        raise click.UsageError("pass --skills, or --profile to infer them from a GitHub account")

    label_list = [lab.strip() for lab in labels.split(",") if lab.strip()] if labels else []
    if updated_days <= 0:
        raise click.UsageError("--updated-days must be greater than zero")
    if max_comments is not None and max_comments < 0:
        raise click.UsageError("--max-comments cannot be negative")

    with console.status("[bold blue]Searching GitHub for matching issues..."):
        try:
            candidates = fetch_candidates(
                skill_list,
                min_stars=stars,
                labels=label_list,
                updated_days=updated_days,
                max_comments=max_comments,
                include_assigned=include_assigned,
                include_linked=include_linked,
                check_claims=check_claims,
            )
        except SearchError as exc:
            raise click.ClickException(str(exc)) from exc

    if not candidates:
        console.print("[dim]No matching issues found. Try broader skills or lower --stars.[/dim]")
        return

    console.print(f"[green]Found {len(candidates)} candidates.[/green]")
    if len(candidates) < limit:
        console.print(
            f"[dim]Only {len(candidates)} candidates matched these filters, "
            f"fewer than the requested --limit {limit}.[/dim]"
        )

    if no_llm:
        ranked = candidates[:limit]
        for c in ranked:
            c["match_score"] = "-"
            c["reason"] = ""
            c["approach"] = ""
    else:
        with console.status(f"[bold blue]Ranking with {model}..."):
            ranked = rank_with_llm(
                candidates, skill_list, model=model, api_key=api_key, limit=limit
            )

    if watch:
        from gitsense.watch import default_watch_path, diff_watch, load_watch, query_key, save_watch

        key = query_key(
            skill_list, stars, label_list, updated_days, include_assigned, include_linked, max_comments
        )
        path = default_watch_path(state_dir)
        state = load_watch(path)
        new_results, first_seen = diff_watch(state, key, ranked)
        save_watch(state, path)
        if first_seen is None:
            console.print(
                f"[dim]First watch for this filter set: {len(ranked)} results recorded as the baseline.[/dim]"
            )
        else:
            seen_count = len(ranked) - len(new_results)
            console.print(
                f"[dim]Watch digest since {first_seen}: {len(new_results)} new, {seen_count} already seen.[/dim]"
            )
            ranked = new_results
            if not ranked:
                return

    if fmt == "json" and not out:
        console.print_json(json.dumps(ranked))
    else:
        _print_results(ranked, skill_list)

    if out:
        from pathlib import Path

        from gitsense.finder import render_markdown

        if fmt == "json":
            text = json.dumps(ranked, indent=2, ensure_ascii=False) + "\n"
        else:
            text = render_markdown(ranked, skill_list)
        Path(out).write_text(text, encoding="utf-8")
        console.print(f"\n[green]Wrote report:[/green] {out}")


def _print_results(results: list[dict], skills: list[str]) -> None:
    console.print()
    console.print(Panel(
        f"[bold]Skills:[/bold] {', '.join(skills)}\n"
        f"[bold]Results:[/bold] {len(results)} issues ranked by match",
        title="[bold cyan]GitSense Results[/bold cyan]",
        border_style="cyan",
    ))

    for i, r in enumerate(results, 1):
        score = r.get("match_score", "-")
        score_color = "green" if isinstance(score, int) and score >= 7 else (
            "yellow" if isinstance(score, int) and score >= 4 else "red"
        )

        console.print(f"\n  [{score_color}][bold]{i}. [{score}/10][/bold][/{score_color}] "
                       f"[bold]{r['repo']}[/bold]")
        console.print(f"     {r['title']}")
        console.print(f"     [dim]{r['url']}[/dim]")
        if r.get("labels"):
            console.print(f"     Labels: {', '.join(r['labels'][:4])}")
        claim = r.get("claim")
        if claim:
            console.print(
                f"     [yellow]⚠ possibly claimed by @{claim['user']} on {claim['date']}[/yellow]"
            )
        if r.get("reason"):
            console.print(f"     [italic]{r['reason']}[/italic]")
        if r.get("approach"):
            console.print(f"     [bold]How to start:[/bold] {r['approach']}")


@main.command()
@click.argument("repo")
@click.option("--skills", "-s", default="", help="Your skills for matching")
@click.option(
    "--updated-days",
    default=180,
    show_default=True,
    help="Only show issues updated within this many days",
)
@click.option("--max-comments", type=int, help="Skip noisy issues with more than this many comments")
def scan(repo: str, skills: str, updated_days: int, max_comments: int | None):
    """Scan a specific repo for contribution opportunities.

    \b
    Example:
        gitsense scan vllm-project/vllm --skills python,cuda
    """
    from gitsense.github_client import describe_http_error, search_issues

    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []

    with console.status(f"[bold blue]Scanning {repo}..."):
        if updated_days <= 0:
            raise click.UsageError("--updated-days must be greater than zero")
        if max_comments is not None and max_comments < 0:
            raise click.UsageError("--max-comments cannot be negative")
        from datetime import datetime, timedelta, timezone

        since = datetime.now(timezone.utc).date() - timedelta(days=updated_days)
        q = f"repo:{repo} is:issue is:open no:assignee updated:>={since.isoformat()}"
        if skill_list:
            q += f" {' OR '.join(skill_list[:3])}"
        try:
            issues = search_issues(q, per_page=15)
        except httpx.HTTPError as exc:
            raise click.ClickException(describe_http_error(exc, what=f"Scanning {repo}")) from exc
        if max_comments is not None:
            issues = [issue for issue in issues if issue.get("comments", 0) <= max_comments]

    if not issues:
        console.print(f"[dim]No open unassigned issues found in {repo}.[/dim]")
        return

    t = Table(title=f"Open issues in {repo}", show_lines=False)
    t.add_column("#", style="dim", width=6)
    t.add_column("Title", max_width=60)
    t.add_column("Labels", style="cyan", max_width=25)
    t.add_column("Updated", style="dim", width=10)
    t.add_column("Comments", justify="right", width=8)

    for issue in issues:
        labels = ", ".join(lab["name"] for lab in issue.get("labels", [])[:3])
        t.add_row(
            str(issue["number"]),
            issue["title"][:58],
            labels[:23],
            issue.get("updated_at", "")[:10],
            str(issue.get("comments", 0)),
        )
    console.print(t)


@main.command()
@click.argument("repos", nargs=-1)
@click.option("--targets", type=click.Path(exists=True, dir_okay=False), help="File with one owner/repo per line")
@click.option("--days", default=90, show_default=True, help="Recent PR window to inspect")
@click.option("--stale-days", default=14, show_default=True, help="Open PR age counted as stale")
@click.option("--skills", "-s", default="", help="Your skills, comma-separated, for fit signals")
@click.option("--sample", default=20, show_default=True, help="Merged PR sample size per repo")
@click.option("--format", "fmt", type=click.Choice(["md", "json"]), default="md")
@click.option("--out", type=click.Path(dir_okay=False), help="Write a report file")
@click.option("--explain", is_flag=True, help="Show why each repo got its score, one signal per line")
def radar(
    repos: tuple[str, ...],
    targets: str | None,
    days: int,
    stale_days: int,
    skills: str,
    sample: int,
    fmt: str,
    out: str | None,
    explain: bool,
):
    """Score repos before you spend a weekend on a PR.

    \b
    Examples:
        gitsense radar vllm-project/vllm --skills python,cuda,llm
        gitsense radar --targets targets.txt --days 90 --out radar.md
    """
    from pathlib import Path

    from gitsense.radar import analyze_repo, load_target_repos, render_markdown

    if days <= 0:
        raise click.UsageError("--days must be greater than zero")
    if stale_days <= 0:
        raise click.UsageError("--stale-days must be greater than zero")
    if sample <= 0:
        raise click.UsageError("--sample must be greater than zero")

    target_repos = list(repos)
    if targets:
        target_repos.extend(load_target_repos(targets))
    if not target_repos:
        raise click.UsageError("pass at least one repo or --targets file")

    skill_list = [skill.strip() for skill in skills.split(",") if skill.strip()]
    reports = []
    for repo in dict.fromkeys(target_repos):
        with console.status(f"[bold blue]Checking {repo}..."):
            reports.append(
                analyze_repo(
                    repo,
                    days=days,
                    stale_days=stale_days,
                    skills=skill_list,
                    sample_size=sample,
                )
            )

    reports.sort(key=lambda report: report.score, reverse=True)
    if fmt == "json" and not out:
        console.print_json(json.dumps([asdict(report) for report in reports]))
    else:
        _print_radar_results(reports, explain=explain)

    if out:
        from gitsense.radar import render_json

        text = render_json(reports) if fmt == "json" else render_markdown(reports)
        Path(out).write_text(text, encoding="utf-8")
        console.print(f"\n[green]Wrote report:[/green] {out}")


def _print_radar_results(reports, explain: bool = False) -> None:
    t = Table(title="GitSense Radar", show_lines=False)
    t.add_column("Repo", style="bold", max_width=34)
    t.add_column("Score", justify="right", width=5)
    t.add_column("Action", width=14)
    t.add_column("Merged", justify="right", width=7)
    t.add_column("Open", justify="right", width=5)
    t.add_column("Stale", justify="right", width=5)
    t.add_column("Merge", justify="right", width=7)
    t.add_column("Reply", justify="right", width=7)
    t.add_column("Flags", max_width=28)

    for report in reports:
        color = "green" if report.score >= 75 else "yellow" if report.score >= 45 else "red"
        t.add_row(
            report.repo,
            f"[{color}]{report.score}[/{color}]",
            report.recommendation,
            str(report.merged_prs),
            str(report.open_prs),
            str(report.stale_prs),
            _fmt_days(report.median_merge_days),
            _fmt_days(report.median_maintainer_response_days),
            ", ".join(report.risk_flags[:2]),
        )

    console.print(t)
    if explain:
        for report in reports:
            console.print(f"\n[bold]{report.repo}[/bold] [dim]score {report.score}[/dim]")
            for note in report.notes:
                console.print(f"  [dim]•[/dim] {note}")
            if report.risk_flags:
                console.print(f"  [yellow]flags:[/yellow] {', '.join(report.risk_flags)}")
    console.print("\n[dim]Signals use public GitHub PR history. Treat this as a triage pass, not a guarantee.[/dim]")


def _fmt_days(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value < 1:
        return "<1d"
    return f"{value:.1f}d"


@main.command()
@click.argument("pr_ref")
def predict(pr_ref: str):
    """Estimate how likely an open PR is to get merged, with the reasons why.

    \b
    Examples:
        gitsense predict https://github.com/vllm-project/vllm/pull/12345
        gitsense predict vllm-project/vllm#12345
    """
    from gitsense import github_client
    from gitsense.predictor import (
        analyze_pr,
        derive_review_decision,
        files_touch_tests,
        parse_pr_ref,
    )

    try:
        owner, repo, number = parse_pr_ref(pr_ref)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    with console.status(f"[bold blue]Fetching {owner}/{repo}#{number}..."):
        try:
            pr = github_client.get_pull_request(owner, repo, number)
            reviews = github_client.get_pull_request_reviews(owner, repo, number)
            files = github_client.get_pull_request_files(owner, repo, number)
            head_sha = (pr.get("head") or {}).get("sha") or ""
            ci_state = (
                github_client.get_commit_status_state(owner, repo, head_sha) if head_sha else ""
            )
        except httpx.HTTPError as exc:
            raise click.ClickException(
                github_client.describe_http_error(exc, what=f"Fetching {owner}/{repo}#{number}")
            ) from exc

    prediction = analyze_pr(
        pr,
        review_decision=derive_review_decision(reviews),
        ci_failing=(ci_state == "failure"),
        touches_tests=files_touch_tests(files),
    )

    color = "green" if prediction.score >= 70 else "yellow" if prediction.score >= 45 else "red"
    body = f"[bold {color}]{prediction.score}/100 — {prediction.label}[/bold {color}]\n\n"
    body += "\n".join(f"  • {note}" for note in prediction.notes)
    console.print(
        Panel(body, title=f"PR merge prediction: {owner}/{repo}#{number}", border_style=color)
    )
    console.print(
        "\n[dim]Heuristic from public PR signals. Treat it as triage, not a guarantee.[/dim]"
    )


@main.command()
@click.argument("username")
@click.option("--limit", "-n", default=30, show_default=True, help="Max open PRs to triage")
@click.option("--stale-days", default=14, show_default=True, help="Days without review before pinging")
@click.option("--shallow", is_flag=True, help="Skip per-PR API calls (fast, no scores)")
@click.option("--since-last", is_flag=True, help="Show only what changed since the last triage snapshot")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.option(
    "--state-dir",
    default=None,
    help="Directory for --since-last snapshots (default: ~/.gitsense)",
)
def triage(username: str, limit: int, stale_days: int, shallow: bool, since_last: bool, fmt: str,
           state_dir: str | None):
    """Triage every open PR you've authored, worst-first.

    \b
    Examples:
        gitsense triage octocat
        gitsense triage octocat --stale-days 7 --format json
        gitsense triage octocat --shallow          # one search call only
        gitsense triage octocat --since-last       # delta vs your last run
    """
    from gitsense.github_client import describe_http_error
    from gitsense.triage import (
        build_row,
        default_snapshot_path,
        diff_snapshots,
        enrich_rows,
        fetch_authored_prs,
        load_snapshot,
        save_snapshot,
        sort_rows,
    )

    if limit <= 0:
        raise click.UsageError("--limit must be greater than zero")
    if stale_days <= 0:
        raise click.UsageError("--stale-days must be greater than zero")

    with console.status(f"[bold blue]Finding @{username}'s open PRs..."):
        try:
            items = fetch_authored_prs(username, limit)[:limit]
        except httpx.HTTPError as exc:
            raise click.ClickException(
                describe_http_error(exc, what=f"Finding @{username}'s PRs")
            ) from exc

    if not items:
        console.print(f"[dim]No open PRs found for @{username}.[/dim]")
        return

    if shallow:
        rows = [build_row(item, stale_days=stale_days) for item in items]
    else:
        with console.status(f"[bold blue]Checking {len(items)} open PRs..."):
            try:
                rows = enrich_rows(items, stale_days=stale_days)
            except httpx.HTTPError as exc:
                raise click.ClickException(
                    describe_http_error(exc, what="Enriching PRs")
                ) from exc
    rows = sort_rows(rows)

    if since_last:
        snap = default_snapshot_path(state_dir)
        delta = diff_snapshots(load_snapshot(snap), rows)
        save_snapshot(rows, snap)
        if fmt == "json":
            console.print_json(json.dumps(delta))
            return
        unchanged = len(rows) - len(delta["new"]) - len(delta["changed"])
        console.print(f"[bold]Triage delta:[/bold] {len(delta['new'])} new, "
                      f"{len(delta['changed'])} changed, {len(delta['gone'])} gone, {unchanged} unchanged")
        for entry in delta["new"]:
            console.print(f"  [green]NEW[/green]     {entry['repo']}#{entry['number']} — {entry['action']}")
        for entry in delta["changed"]:
            console.print(
                f"  [yellow]CHANGED[/yellow] {entry['repo']}#{entry['number']} — "
                f"{entry['was']} → {entry['now']}"
            )
        for entry in delta["gone"]:
            console.print(f"  [dim]GONE     {entry['repo']}#{entry['number']} — was: {entry['was']}[/dim]")
        return

    if fmt == "json":
        console.print_json(json.dumps([asdict(r) for r in rows]))
        return

    t = Table(title=f"Open PR triage: @{username}", show_lines=False)
    t.add_column("PR", style="bold", max_width=30)
    t.add_column("Score", justify="right", width=5)
    t.add_column("Action", width=30)
    t.add_column("Age", justify="right", width=6)
    t.add_column("Idle", justify="right", width=6)
    t.add_column("Title", max_width=44)

    for r in rows:
        score_color = "green" if (r.score or 0) >= 70 else "yellow" if (r.score or 0) >= 45 else "red"
        score_text = f"[{score_color}]{r.score}[/{score_color}]" if r.score is not None else "[dim]-[/dim]"
        action = r.action
        if action in ("fix CI", "address the review", "rebase to clear conflicts"):
            action = f"[red]{action}[/red]"
        elif action.startswith("no review"):
            action = f"[yellow]{action}[/yellow]"
        t.add_row(
            f"{r.repo}#{r.number}",
            score_text,
            action,
            f"{int(r.age_days)}d",
            f"{int(r.updated_days)}d",
            r.title[:42],
        )
    console.print(t)
    console.print(
        "\n[dim]Scores reuse the predict heuristic. "
        "Idle = days since last activity on the PR.[/dim]"
    )


@main.command()
@click.argument("username")
def profile(username: str):
    """Infer a skill profile from a GitHub user's public repos.

    \b
    Example:
        gitsense profile torvalds
    """
    from gitsense.profile import infer_skills

    with console.status(f"[bold blue]Reading @{username}'s public repos..."):
        result = infer_skills(username)

    if not result["top"]:
        console.print(
            f"[yellow]No skills inferred for @{username}: "
            "no non-fork public repos with a primary language.[/yellow]"
        )
        return

    lines = [f"  {lang:<16} {weight:.2f}" for lang, weight in result["languages"]]
    body = (
        f"[bold]Inferred from {result['repo_count']} repos[/bold]"
        + (f" (skipped {result['skipped_forks']} forks)" if result["skipped_forks"] else "")
        + "\n\n" + "\n".join(lines)
        + "\n\n[dim]Weights = 1 + log10(stars+1), capped at 1000 stars. "
        "Forks and repos without a primary language are skipped.[/dim]"
    )
    console.print(Panel(body, title=f"[bold cyan]Skill profile: @{username}[/bold cyan]",
                        border_style="cyan"))
    console.print(f"\n[dim]Use it directly: gitsense find --profile {username}[/dim]")
