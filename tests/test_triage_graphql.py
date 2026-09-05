"""Tests for the batched GraphQL triage enrichment (no network)."""

from datetime import datetime, timedelta, timezone

import httpx

from gitsense import triage
from gitsense.triage import _build_pr_batch_query, enrich_row, enrich_rows


def _search_item(number=42, repo="o/r", **overrides):
    item = {
        "number": number,
        "title": "fix the thing",
        "html_url": f"https://github.com/{repo}/pull/{number}",
        "repository_url": f"https://api.github.com/repos/{repo}",
        "draft": False,
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
    }
    item.update(overrides)
    return item


def _rest_pr(**overrides):
    pr = {
        "draft": False,
        "additions": 25,
        "changed_files": 2,
        "mergeable_state": "clean",
        "created_at": "2026-07-01T00:00:00Z",
        "head": {"sha": "abc123"},
    }
    pr.update(overrides)
    return pr


def _gql_node(**overrides):
    node = {
        "isDraft": False,
        "additions": 25,
        "changedFiles": 2,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "reviewDecision": "APPROVED",
        "createdAt": "2026-07-01T00:00:00Z",
        "files": {"nodes": [{"path": "src/main.py"}, {"path": "tests/test_main.py"}]},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
    }
    node.update(overrides)
    return node


def _payload(*nodes):
    return {"data": {f"pr{i}": {"pullRequest": node} for i, node in enumerate(nodes)}}


def _stub_rest(monkeypatch, *, reviews, files, ci_state, pr=None):
    monkeypatch.setattr(
        "gitsense.github_client.get_pull_request",
        lambda owner, repo, number: pr or _rest_pr(),
    )
    monkeypatch.setattr(
        "gitsense.github_client.get_pull_request_reviews",
        lambda owner, repo, number: reviews,
    )
    monkeypatch.setattr(
        "gitsense.github_client.get_pull_request_files",
        lambda owner, repo, number: files,
    )
    monkeypatch.setattr(
        "gitsense.github_client.get_commit_status_state",
        lambda owner, repo, ref: ci_state,
    )


def test_batch_query_builds_aliased_blocks():
    items = [_search_item(number=42, repo="o/r"), _search_item(number=7, repo="a/b")]
    query = _build_pr_batch_query(items)
    assert query.startswith("query {")
    assert 'pr0: repository(owner: "o", name: "r")' in query
    assert 'pr1: repository(owner: "a", name: "b")' in query
    assert "pullRequest(number: 42)" in query
    assert "pullRequest(number: 7)" in query
    for field in ("reviewDecision", "mergeable", "mergeStateStatus", "statusCheckRollup", "changedFiles"):
        assert field in query


def test_enrich_rows_matches_rest_path(monkeypatch):
    items = [_search_item(number=42)]
    reviews = [{"state": "APPROVED", "user": {"login": "rev1"}}]
    files = [{"filename": "src/main.py"}, {"filename": "tests/test_main.py"}]

    _stub_rest(monkeypatch, reviews=reviews, files=files, ci_state="success")
    rest_row = enrich_row(items[0], stale_days=14)

    monkeypatch.setattr(
        "gitsense.github_client.graphql",
        lambda query, variables=None: _payload(_gql_node()),
    )
    gql_row = enrich_rows(items, stale_days=14)[0]

    assert gql_row.action == rest_row.action == "approved & green — nudge for merge"
    assert gql_row.score == rest_row.score
    assert gql_row.notes == rest_row.notes


def test_enrich_rows_matches_rest_path_on_failing_pr(monkeypatch):
    items = [_search_item(number=9)]
    reviews = [{"state": "CHANGES_REQUESTED", "user": {"login": "rev1"}}]
    files = [{"filename": "src/main.py"}]
    node = _gql_node(
        reviewDecision="CHANGES_REQUESTED",
        files={"nodes": [{"path": "src/main.py"}]},
        commits={"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE"}}}]},
    )

    _stub_rest(monkeypatch, reviews=reviews, files=files, ci_state="failure")
    rest_row = enrich_row(items[0], stale_days=14)

    monkeypatch.setattr(
        "gitsense.github_client.graphql",
        lambda query, variables=None: _payload(node),
    )
    gql_row = enrich_rows(items, stale_days=14)[0]

    assert gql_row.action == rest_row.action == "address the review"
    assert gql_row.score == rest_row.score


def test_enrich_rows_conflicting_pr_maps_to_dirty_vocabulary(monkeypatch):
    node = _gql_node(mergeable="CONFLICTING", mergeStateStatus="DIRTY", reviewDecision=None)
    monkeypatch.setattr(
        "gitsense.github_client.graphql",
        lambda query, variables=None: _payload(node),
    )
    row = enrich_rows([_search_item()], stale_days=14)[0]
    assert row.action == "rebase to clear conflicts"


def test_enrich_rows_falls_back_to_rest_on_http_error(monkeypatch):
    def boom(query, variables=None):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr("gitsense.github_client.graphql", boom)
    reviews = [{"state": "APPROVED", "user": {"login": "rev1"}}]
    _stub_rest(monkeypatch, reviews=reviews, files=[], ci_state="success")

    rows = enrich_rows([_search_item(number=1), _search_item(number=2)], stale_days=14)
    assert len(rows) == 2
    assert all(r.action == "approved & green — nudge for merge" for r in rows)


def test_enrich_rows_falls_back_on_errors_payload(monkeypatch):
    monkeypatch.setattr(
        "gitsense.github_client.graphql",
        lambda query, variables=None: {"errors": [{"message": "boom"}]},
    )
    _stub_rest(monkeypatch, reviews=[], files=[], ci_state="")

    rows = enrich_rows([_search_item()], stale_days=14)
    assert len(rows) == 1
    assert rows[0].score is not None  # came from the REST enrichment


def test_enrich_rows_missing_node_keeps_shallow_row(monkeypatch):
    monkeypatch.setattr(
        "gitsense.github_client.graphql",
        lambda query, variables=None: {"data": {"pr0": {"pullRequest": None}}},
    )
    row = enrich_rows([_search_item()], stale_days=14)[0]
    assert row.score is None
    assert row.action == "waiting on reviewer"


def test_enrich_rows_chunks_large_batches(monkeypatch):
    calls = []

    def fake_graphql(query, variables=None):
        calls.append(query)
        n = query.count("pullRequest(number:")
        return _payload(*(_gql_node() for _ in range(n)))

    monkeypatch.setattr("gitsense.github_client.graphql", fake_graphql)
    monkeypatch.setattr(triage, "_GQL_CHUNK", 2)

    items = [_search_item(number=i) for i in range(5)]
    rows = enrich_rows(items, stale_days=14)
    assert len(rows) == 5
    assert len(calls) == 3  # 2 + 2 + 1
