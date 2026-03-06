"""Tests for the search query builder."""

from gitsense.finder import build_search_queries


def test_basic_query():
    queries = build_search_queries(["python"], min_stars=100, labels=[])
    assert len(queries) >= 1
    assert "python" in queries[0]
    assert "is:issue" in queries[0]
    assert "is:open" in queries[0]
    assert "stars:>=100" in queries[0]


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
