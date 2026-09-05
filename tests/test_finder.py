"""Tests for the search query builder."""

import httpx
import pytest

from gitsense.finder import build_search_queries, fetch_candidates


def test_basic_query():
    queries = build_search_queries(["python"], min_stars=100, labels=[])
    assert len(queries) >= 1
    assert "python" in queries[0]
    assert "is:issue" in queries[0]
    assert "is:open" in queries[0]
    assert "archived:false" in queries[0]
    assert "no:assignee" in queries[0]
    assert "stars:>=100" in queries[0]
    assert "updated:>=" in queries[0]


def test_multiple_skills():
    queries = build_search_queries(["python", "cuda", "llm"], min_stars=0, labels=[])
    assert len(queries) >= 3
    # Each skill gets its own query + one "good first issue" combo
    assert any("cuda" in q for q in queries)
    assert any("good first issue" in q for q in queries)


def test_with_labels():
    queries = build_search_queries(["rust"], min_stars=50, labels=["bug"])
    assert any('label:"bug"' in q for q in queries)


def test_zero_stars():
    queries = build_search_queries(["go"], min_stars=0, labels=[])
    assert not any("stars:" in q for q in queries)


def test_include_assigned_drops_no_assignee_filter():
    queries = build_search_queries(["python"], min_stars=0, labels=[], include_assigned=True)
    assert not any("no:assignee" in q for q in queries)


def test_empty_skills_rejected():
    with pytest.raises(ValueError, match="skills must not be empty"):
        build_search_queries([], min_stars=0, labels=[])


def test_nonpositive_updated_days_rejected():
    with pytest.raises(ValueError, match="got 0"):
        build_search_queries(["python"], min_stars=0, labels=[], updated_days=0)


def test_fetch_candidates_filters_comment_heavy_issues(monkeypatch):
    def fake_search_issues(query, per_page):
        return [
            {
                "title": "quiet bug",
                "html_url": "https://github.com/o/r/issues/1",
                "repository_url": "https://api.github.com/repos/o/r",
                "labels": [{"name": "bug"}],
                "comments": 2,
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-12T00:00:00Z",
                "body": "clear repro",
            },
            {
                "title": "long debate",
                "html_url": "https://github.com/o/r/issues/2",
                "repository_url": "https://api.github.com/repos/o/r",
                "labels": [{"name": "discussion"}],
                "comments": 42,
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-12T00:00:00Z",
                "body": "unclear",
            },
        ]

    monkeypatch.setattr("gitsense.finder.search_issues", fake_search_issues)

    candidates = fetch_candidates(["python"], min_stars=0, max_comments=10)

    assert [candidate["title"] for candidate in candidates] == ["quiet bug"]
    assert candidates[0]["updated_at"] == "2026-05-12"


def test_linked_pr_issues_filtered_by_default():
    queries = build_search_queries(["python"], min_stars=100, labels=[])
    assert all("-linked:pr" in q for q in queries)


def test_linked_pr_issues_included_on_opt_in():
    queries = build_search_queries(["python"], min_stars=100, labels=[], include_linked=True)
    assert all("-linked:pr" not in q for q in queries)


def test_openai_key_stays_on_openai_host(monkeypatch):
    from gitsense import finder

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            raise httpx.ConnectError("stop after client construction")

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            captured["base_url"] = base_url
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(finder, "OpenAI", FakeOpenAI)
    out = finder.rank_with_llm(
        [{"repo": "o/r", "title": "t", "labels": [], "body": "b", "comments": 0, "updated_at": ""}],
        ["python"],
    )
    assert captured["base_url"] is None  # OpenAI SDK default host, not OpenRouter
    assert out[0]["reason"] == "LLM ranking unavailable (provider error)"


def test_openrouter_key_routes_to_openrouter(monkeypatch):
    from gitsense import finder

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            raise httpx.ConnectError("stop after client construction")

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            captured["base_url"] = base_url
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(finder, "OpenAI", FakeOpenAI)
    finder.rank_with_llm(
        [{"repo": "o/r", "title": "t", "labels": [], "body": "b", "comments": 0, "updated_at": ""}],
        ["python"],
    )
    assert captured["base_url"] == "https://openrouter.ai/api/v1"


def _candidates(n):
    return [
        {
            "repo": f"o/r{i}",
            "title": f"issue {i}",
            "labels": [],
            "body": "b",
            "comments": 0,
            "updated_at": "",
            "url": f"https://github.com/o/r{i}/issues/1",
        }
        for i in range(n)
    ]


def _no_llm_env(monkeypatch):
    for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_BASE_URL"):
        monkeypatch.delenv(var, raising=False)


def test_rank_without_key_returns_up_to_limit(monkeypatch):
    from gitsense import finder

    _no_llm_env(monkeypatch)
    out = finder.rank_with_llm(_candidates(12), ["python"], limit=5)
    assert len(out) == 5


def test_rank_without_key_does_not_clamp_below_pool(monkeypatch):
    from gitsense import finder

    _no_llm_env(monkeypatch)
    out = finder.rank_with_llm(_candidates(3), ["python"], limit=15)
    assert len(out) == 3  # pool is the ceiling, not the requested limit


def test_llm_prompt_asks_for_the_requested_limit(monkeypatch):
    from gitsense import finder

    _no_llm_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["prompt"] = kwargs["messages"][0]["content"]
            raise httpx.ConnectError("stop after prompt capture")

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(finder, "OpenAI", FakeOpenAI)
    finder.rank_with_llm(_candidates(30), ["python"], limit=15)
    assert "Only include the top 15." in captured["prompt"]


def test_provider_error_fallback_respects_limit(monkeypatch):
    from gitsense import finder

    _no_llm_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class FakeCompletions:
        def create(self, **kwargs):
            raise httpx.ConnectError("down")

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(finder, "OpenAI", FakeOpenAI)
    out = finder.rank_with_llm(_candidates(20), ["python"], limit=12)
    assert len(out) == 12
    assert out[0]["reason"] == "LLM ranking unavailable (provider error)"


def _status_error(status, headers=None):
    req = httpx.Request("GET", "https://api.github.com/search/issues")
    resp = httpx.Response(status, headers=headers or {}, request=req)
    return httpx.HTTPStatusError(f"HTTP {status}", request=req, response=resp)


def test_fetch_candidates_raises_search_error_when_all_queries_fail(monkeypatch):
    from gitsense import finder

    def boom(query, per_page):
        raise _status_error(
            403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1893456000"}
        )

    monkeypatch.setattr("gitsense.finder.search_issues", boom)
    with pytest.raises(finder.SearchError, match="rate limit"):
        fetch_candidates(["python"], min_stars=0)


def test_fetch_candidates_tolerates_partial_query_failure(monkeypatch):
    def flaky_search(query, per_page):
        if "good first issue" in query:
            raise _status_error(502)
        return [
            {
                "title": "quiet bug",
                "html_url": "https://github.com/o/r/issues/1",
                "repository_url": "https://api.github.com/repos/o/r",
                "labels": [{"name": "bug"}],
                "comments": 2,
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-12T00:00:00Z",
                "body": "clear repro",
            }
        ]

    monkeypatch.setattr("gitsense.finder.search_issues", flaky_search)
    candidates = fetch_candidates(["python"], min_stars=0)
    assert [c["title"] for c in candidates] == ["quiet bug"]


def test_render_markdown_report():
    from gitsense.finder import render_markdown

    results = [
        {
            "repo": "o/r",
            "title": "fix the leak",
            "url": "https://github.com/o/r/issues/1",
            "labels": ["bug"],
            "match_score": 9,
            "reason": "perfect match",
            "approach": "start in worker.py",
            "claim": None,
        }
    ]
    text = render_markdown(results, ["python", "cuda"])
    assert text.startswith("# GitSense results for: python, cuda")
    assert "## 1. [9/10] o/r" in text
    assert "[fix the leak](https://github.com/o/r/issues/1)" in text
    assert "How to start: start in worker.py" in text
    assert text.endswith("\n")
