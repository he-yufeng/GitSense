"""Tests for the search query builder."""

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
