import json

from gitsense.radar import (
    RepoRadarReport,
    analyze_repo,
    load_target_repos,
    parse_repo_name,
    recommendation_for_score,
    render_json,
    render_markdown,
    risk_flags_for_repo,
    score_repo,
)


def test_parse_repo_name_accepts_url():
    assert parse_repo_name("https://github.com/vllm-project/vllm") == ("vllm-project", "vllm")


def test_load_target_repos_ignores_comments(tmp_path):
    path = tmp_path / "targets.txt"
    path.write_text(
        """
        # target repos
        vllm-project/vllm
        pytorch/pytorch, optional note
        """,
        encoding="utf-8",
    )

    assert load_target_repos(path) == ["vllm-project/vllm", "pytorch/pytorch"]


def test_score_repo_rewards_fast_external_merges():
    score, notes = score_repo(
        merged_prs=35,
        open_prs=20,
        stale_ratio=0.05,
        median_merge_days=4,
        median_maintainer_response_days=2,
        external_merged_ratio=0.7,
        skill_matches=["python", "llm"],
        stars=12_000,
    )

    assert score >= 90
    assert "outside contributors are getting merged" in notes
    assert recommendation_for_score(score) == "Go"


def test_score_repo_penalizes_stale_internal_backlog():
    score, notes = score_repo(
        merged_prs=0,
        open_prs=100,
        stale_ratio=0.8,
        median_merge_days=None,
        median_maintainer_response_days=None,
        external_merged_ratio=0.1,
        skill_matches=[],
        stars=400,
    )

    assert score < 45
    assert "many stale open PRs" in notes
    assert recommendation_for_score(score) == "Avoid for now"


def test_risk_flags_call_out_crowded_internal_repos():
    flags = risk_flags_for_repo(
        merged_prs=3,
        open_prs=140,
        stale_ratio=0.4,
        median_merge_days=50,
        median_maintainer_response_days=25,
        external_merged_ratio=0.1,
    )

    assert "crowded stale PR queue" in flags
    assert "slow merge time" in flags
    assert "mostly internal recent merges" in flags


def test_analyze_repo_uses_public_pr_signals(monkeypatch):
    def fake_repo_info(owner, repo):
        return {
            "full_name": f"{owner}/{repo}",
            "description": "LLM inference in Python",
            "stargazers_count": 2000,
            "language": "Python",
            "topics": ["llm"],
        }

    def fake_languages(owner, repo):
        return {"Python": 1000}

    def fake_count(query):
        if "is:merged" in query:
            return 12
        if "created:<" in query:
            return 2
        return 8

    def fake_search(query, sort="created", order="desc", per_page=30):
        return [
            {
                "html_url": "https://github.com/o/r/pull/1",
                "created_at": "2026-05-01T00:00:00Z",
                "closed_at": "2026-05-05T00:00:00Z",
                "author_association": "CONTRIBUTOR",
            },
            {
                "html_url": "https://github.com/o/r/pull/2",
                "created_at": "2026-05-02T00:00:00Z",
                "closed_at": "2026-05-10T00:00:00Z",
                "author_association": "MEMBER",
            },
        ]

    def fake_comments(owner, repo, number):
        return [
            {
                "created_at": "2026-05-03T00:00:00Z",
                "author_association": "MEMBER",
            }
        ]

    monkeypatch.setattr("gitsense.radar.get_repo_info", fake_repo_info)
    monkeypatch.setattr("gitsense.radar.get_repo_languages", fake_languages)
    monkeypatch.setattr("gitsense.radar.search_issue_count", fake_count)
    monkeypatch.setattr("gitsense.radar.search_issues", fake_search)
    monkeypatch.setattr("gitsense.radar.get_issue_comments", fake_comments)

    report = analyze_repo("o/r", skills=["python", "cuda"], days=90)

    assert report.merged_prs == 12
    assert report.stale_prs == 2
    assert report.open_to_merged_ratio == 8 / 12
    assert report.skill_matches == ["python"]
    assert report.median_merge_days == 6
    assert report.median_maintainer_response_days == 1.5


def test_render_markdown_includes_key_fields():
    report = analyze_repo.__annotations__  # keep import exercised without constructing by accident
    assert "return" in report

    markdown = render_markdown(
        [
            RepoRadarReport(
                repo="o/r",
                score=81,
                recommendation="Go",
                stars=100,
                primary_language="Python",
                merged_prs=10,
                open_prs=4,
                stale_prs=1,
                stale_ratio=0.25,
                median_merge_days=2,
                median_maintainer_response_days=1,
                external_merged_ratio=0.5,
                open_to_merged_ratio=0.4,
                risk_flags=["manual review needed"],
            )
        ]
    )

    assert "# GitSense Radar Report" in markdown
    assert "| o/r | 81 | Go | 10 | 4 | 1 | 0.4x |" in markdown
    assert "Risk flags: manual review needed" in markdown


def test_render_json_includes_machine_readable_fields():
    payload = render_json(
        [
            RepoRadarReport(
                repo="o/r",
                score=81,
                recommendation="Go",
                stars=100,
                primary_language="Python",
                merged_prs=10,
                open_prs=4,
                stale_prs=1,
                stale_ratio=0.25,
                median_merge_days=2,
                median_maintainer_response_days=1,
                external_merged_ratio=0.5,
                open_to_merged_ratio=0.4,
                risk_flags=["manual review needed"],
            )
        ]
    )

    assert '"repo": "o/r"' in payload
    assert '"open_to_merged_ratio": 0.4' in payload


def test_radar_cli_sorts_and_writes_report(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from gitsense.cli import main

    calls = []

    def fake_analyze_repo(repo, *, days, stale_days, skills, sample_size):
        calls.append(
            {
                "repo": repo,
                "days": days,
                "stale_days": stale_days,
                "skills": skills,
                "sample_size": sample_size,
            }
        )
        return RepoRadarReport(
            repo=repo,
            score=90 if repo == "fast/repo" else 51,
            recommendation="Go" if repo == "fast/repo" else "Comment first",
            stars=1000,
            primary_language="Python",
            merged_prs=20,
            open_prs=5,
            stale_prs=1,
            stale_ratio=0.2,
            median_merge_days=5,
            median_maintainer_response_days=2,
            external_merged_ratio=0.6,
        )

    monkeypatch.setattr("gitsense.radar.analyze_repo", fake_analyze_repo)

    out = tmp_path / "radar.md"
    result = CliRunner().invoke(
        main,
        [
            "radar",
            "slow/repo",
            "fast/repo",
            "--skills",
            "python,llm",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0
    assert [call["repo"] for call in calls] == ["slow/repo", "fast/repo"]
    assert calls[0]["stale_days"] == 14
    assert calls[0]["skills"] == ["python", "llm"]
    assert out.read_text(encoding="utf-8").index("fast/repo") < out.read_text(
        encoding="utf-8"
    ).index("slow/repo")


def test_radar_cli_writes_json_report(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from gitsense.cli import main

    def fake_analyze_repo(repo, *, days, stale_days, skills, sample_size):
        return RepoRadarReport(
            repo=repo,
            score=77,
            recommendation="Go",
            stars=1000,
            primary_language="Python",
            merged_prs=20,
            open_prs=5,
            stale_prs=1,
            stale_ratio=0.2,
            median_merge_days=5,
            median_maintainer_response_days=2,
            external_merged_ratio=0.6,
        )

    monkeypatch.setattr("gitsense.radar.analyze_repo", fake_analyze_repo)

    out = tmp_path / "radar.json"
    result = CliRunner().invoke(
        main,
        ["radar", "one/repo", "--format", "json", "--out", str(out)],
    )

    assert result.exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload[0]["repo"] == "one/repo"
