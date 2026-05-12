"""CLI for GitSense."""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from gitsense import __version__

console = Console()


@click.group()
@click.version_option(__version__, prog_name="gitsense")
def main():
    """GitSense — find your next open source contribution, powered by AI."""
    pass


@main.command()
@click.option("--skills", "-s", required=True, help="Your skills, comma-separated (e.g. python,cuda,llm)")
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
def find(skills: str, stars: int, labels: str, model: str, api_key: str | None,
         no_llm: bool, limit: int, updated_days: int, max_comments: int | None,
         include_assigned: bool):
    """Find open issues that match your skills.

    \b
    Examples:
        gitsense find --skills python,llm,cuda
        gitsense find --skills rust,wasm --stars 500
        gitsense find --skills python --labels bug --no-llm
        gitsense find --skills python,llm --updated-days 30 --max-comments 10
    """
    from gitsense.finder import fetch_candidates, rank_with_llm

    skill_list = [s.strip() for s in skills.split(",") if s.strip()]
    label_list = [lab.strip() for lab in labels.split(",") if lab.strip()] if labels else []
    if updated_days <= 0:
        raise click.UsageError("--updated-days must be greater than zero")
    if max_comments is not None and max_comments < 0:
        raise click.UsageError("--max-comments cannot be negative")

    with console.status("[bold blue]Searching GitHub for matching issues..."):
        candidates = fetch_candidates(
            skill_list,
            min_stars=stars,
            labels=label_list,
            updated_days=updated_days,
            max_comments=max_comments,
            include_assigned=include_assigned,
        )

    if not candidates:
        console.print("[dim]No matching issues found. Try broader skills or lower --stars.[/dim]")
        return

    console.print(f"[green]Found {len(candidates)} candidates.[/green]")

    if no_llm:
        ranked = candidates[:limit]
        for c in ranked:
            c["match_score"] = "-"
            c["reason"] = ""
            c["approach"] = ""
    else:
        with console.status(f"[bold blue]Ranking with {model}..."):
            ranked = rank_with_llm(
                candidates, skill_list, model=model, api_key=api_key
            )[:limit]

    _print_results(ranked, skill_list)


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
    from gitsense.github_client import search_issues

    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []

    with console.status(f"[bold blue]Scanning {repo}..."):
        if updated_days <= 0:
            raise click.UsageError("--updated-days must be greater than zero")
        if max_comments is not None and max_comments < 0:
            raise click.UsageError("--max-comments cannot be negative")
        from datetime import date, timedelta

        since = date.today() - timedelta(days=updated_days)
        q = f"repo:{repo} is:issue is:open no:assignee updated:>={since.isoformat()}"
        if skill_list:
            q += f" {' OR '.join(skill_list[:3])}"
        issues = search_issues(q, per_page=15)
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
