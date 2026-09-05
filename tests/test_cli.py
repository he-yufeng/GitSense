"""CLI-level tests: clean errors, exit codes, find export."""

import json

import httpx
from click.testing import CliRunner

from gitsense.cli import main


def _status_error(status, headers=None):
    req = httpx.Request("GET", "https://api.github.com/x")
    resp = httpx.Response(status, headers=headers or {}, request=req)
    return httpx.HTTPStatusError(f"HTTP {status}", request=req, response=resp)


def _issue(i, repo="o/r"):
    return {
        "title": f"issue {i}",
        "html_url": f"https://github.com/{repo}/issues/{i}",
        "repository_url": f"https://api.github.com/repos/{repo}",
        "labels": [{"name": "bug"}],
        "comments": 0,
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-12T00:00:00Z",
        "body": "repro",
    }


def _no_llm_env(monkeypatch):
    for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_BASE_URL"):
        monkeypatch.delenv(var, raising=False)


def test_find_rate_limit_prints_reset_and_exits_nonzero(monkeypatch):
    def boom(query, per_page):
        raise _status_error(
            403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1893456000"}
        )

    monkeypatch.setattr("gitsense.finder.search_issues", boom)
    result = CliRunner().invoke(main, ["find", "--skills", "python"])
    assert result.exit_code == 1
    assert "rate limit" in result.output
    assert "00:00 UTC" in result.output  # 1893456000 = 2030-01-01T00:00:00Z
    assert "Traceback" not in result.output


def test_find_other_http_error_is_one_clean_line(monkeypatch):
    def boom(query, per_page):
        raise _status_error(502)

    monkeypatch.setattr("gitsense.finder.search_issues", boom)
    result = CliRunner().invoke(main, ["find", "--skills", "python"])
    assert result.exit_code == 1
    assert "HTTP 502" in result.output
    assert "Traceback" not in result.output


def test_find_secondary_rate_limit_named_in_message(monkeypatch):
    def boom(query, per_page):
        req = httpx.Request("GET", "https://api.github.com/search/issues")
        resp = httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "21"},
            content=b'{"message": "You have exceeded a secondary rate limit."}',
            request=req,
        )
        raise httpx.HTTPStatusError("HTTP 403", request=req, response=resp)

    monkeypatch.setattr("gitsense.finder.search_issues", boom)
    result = CliRunner().invoke(main, ["find", "--skills", "python"])
    assert result.exit_code == 1
    assert "secondary rate limit" in result.output


def test_scan_bad_repo_is_a_clean_error(monkeypatch):
    def boom(query, sort="created", order="desc", per_page=30):
        raise _status_error(404)

    monkeypatch.setattr("gitsense.github_client.search_issues", boom)
    result = CliRunner().invoke(main, ["scan", "o/nope"])
    assert result.exit_code == 1
    assert "not found" in result.output
    assert "Traceback" not in result.output


def test_scan_rate_limit_shows_reset(monkeypatch):
    def boom(query, sort="created", order="desc", per_page=30):
        raise _status_error(
            403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1893456000"}
        )

    monkeypatch.setattr("gitsense.github_client.search_issues", boom)
    result = CliRunner().invoke(main, ["scan", "o/r"])
    assert result.exit_code == 1
    assert "rate limit" in result.output
    assert "00:00 UTC" in result.output


def test_predict_missing_pr_is_a_clean_error(monkeypatch):
    def boom(owner, repo, number):
        raise _status_error(404)

    monkeypatch.setattr("gitsense.github_client.get_pull_request", boom)
    result = CliRunner().invoke(main, ["predict", "o/r#123"])
    assert result.exit_code == 1
    assert "not found" in result.output
    assert "Traceback" not in result.output


def test_triage_search_failure_is_a_clean_error(monkeypatch):
    def boom(query, sort="created", order="desc", per_page=30):
        raise _status_error(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1893456000"})

    monkeypatch.setattr("gitsense.github_client.search_issues", boom)
    result = CliRunner().invoke(main, ["triage", "octocat"])
    assert result.exit_code == 1
    assert "rate limit" in result.output
    assert "00:00 UTC" in result.output
    assert "Traceback" not in result.output


def test_triage_enrichment_failure_is_a_clean_error(monkeypatch):
    monkeypatch.setattr(
        "gitsense.github_client.search_issues",
        lambda query, sort="created", order="desc", per_page=30: [
            {
                "number": 1,
                "title": "t",
                "html_url": "https://github.com/o/r/pull/1",
                "repository_url": "https://api.github.com/repos/o/r",
                "draft": False,
                "created_at": "2026-07-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        ],
    )

    def boom(query, variables=None):
        raise _status_error(502)

    monkeypatch.setattr("gitsense.github_client.graphql", boom)

    def rest_boom(owner, repo, number):
        raise _status_error(502)

    monkeypatch.setattr("gitsense.github_client.get_pull_request", rest_boom)
    result = CliRunner().invoke(main, ["triage", "octocat"])
    assert result.exit_code == 1
    assert "HTTP 502" in result.output
    assert "Traceback" not in result.output


def test_find_limit_passed_through(monkeypatch):
    _no_llm_env(monkeypatch)
    monkeypatch.setattr(
        "gitsense.finder.search_issues",
        lambda query, per_page: [_issue(i) for i in range(20)],
    )
    result = CliRunner().invoke(
        main, ["find", "--skills", "python", "--no-llm", "--limit", "15", "--format", "json"]
    )
    assert result.exit_code == 0
    payload = json.JSONDecoder().raw_decode(result.output[result.output.index("[") :])[0]
    assert len(payload) == 15


def test_find_says_once_when_pool_is_smaller_than_limit(monkeypatch):
    _no_llm_env(monkeypatch)
    monkeypatch.setattr(
        "gitsense.finder.search_issues",
        lambda query, per_page: [_issue(1), _issue(2)],
    )
    result = CliRunner().invoke(main, ["find", "--skills", "python", "--no-llm", "--limit", "10"])
    assert result.exit_code == 0
    assert result.output.count("Only 2 candidates matched") == 1


def test_find_json_export_to_file(monkeypatch, tmp_path):
    _no_llm_env(monkeypatch)
    monkeypatch.setattr(
        "gitsense.finder.search_issues",
        lambda query, per_page: [_issue(1), _issue(2)],
    )
    out = tmp_path / "results.json"
    result = CliRunner().invoke(
        main, ["find", "--skills", "python", "--no-llm", "--format", "json", "--out", str(out)]
    )
    assert result.exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [d["title"] for d in data] == ["issue 1", "issue 2"]
    assert data[0]["match_score"] == "-"


def test_find_markdown_export_to_file(monkeypatch, tmp_path):
    _no_llm_env(monkeypatch)
    monkeypatch.setattr(
        "gitsense.finder.search_issues",
        lambda query, per_page: [_issue(1)],
    )
    out = tmp_path / "results.md"
    result = CliRunner().invoke(
        main, ["find", "--skills", "python", "--no-llm", "--out", str(out)]
    )
    assert result.exit_code == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# GitSense results for: python")
    assert "[issue 1](https://github.com/o/r/issues/1)" in text
