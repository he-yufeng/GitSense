"""Tests for claim detection on issue comments."""

from datetime import datetime, timedelta, timezone

from gitsense.finder import detect_claims, fetch_candidates


def _comment(body, user="someone", created=None):
    return {
        "body": body,
        "user": {"login": user},
        "created_at": created or datetime.now(timezone.utc).date().isoformat(),
    }


def test_detects_english_claim():
    claim = detect_claims([_comment("I'd like to work on this if that's ok")])
    assert claim is not None
    assert claim["user"] == "someone"


def test_detects_chinese_claim():
    claim = detect_claims([_comment("这个我来认领，周末提 PR")])
    assert claim is not None


def test_ordinary_comment_is_not_a_claim():
    assert detect_claims([_comment("can you share the full traceback?")]) is None
    assert detect_claims([]) is None


def test_stale_claim_is_ignored():
    old = (datetime.now(timezone.utc).date() - timedelta(days=120)).isoformat()
    assert detect_claims([_comment("I'll take this", created=old)]) is None
    # 120 days back still counts within a 180-day window
    claim = detect_claims([_comment("I'll take this", created=old)], days=180)
    assert claim is not None


def test_fetch_candidates_annotates_claims(monkeypatch):
    issue = {
        "html_url": "https://github.com/octo-org/demo/issues/42",
        "repository_url": "https://api.github.com/repos/octo-org/demo",
        "title": "fix the thing",
        "labels": [],
        "comments": 3,
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-20T00:00:00Z",
        "body": "body",
    }
    monkeypatch.setattr("gitsense.finder.search_issues", lambda q, per_page=20: [issue])
    monkeypatch.setattr(
        "gitsense.finder.get_issue_comments",
        lambda owner, repo, number: [_comment("I can take this one", user="octocat")],
    )

    candidates = fetch_candidates(["python"], min_stars=0, check_claims=True)

    assert candidates[0]["claim"]["user"] == "octocat"


def test_fetch_candidates_skips_claim_lookup_without_comments(monkeypatch):
    issue = {
        "html_url": "https://github.com/octo-org/demo/issues/43",
        "repository_url": "https://api.github.com/repos/octo-org/demo",
        "title": "quiet issue",
        "labels": [],
        "comments": 0,
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-20T00:00:00Z",
        "body": "body",
    }
    monkeypatch.setattr("gitsense.finder.search_issues", lambda q, per_page=20: [issue])

    def _boom(owner, repo, number):
        raise AssertionError("should not fetch comments for a comment-less issue")

    monkeypatch.setattr("gitsense.finder.get_issue_comments", _boom)

    candidates = fetch_candidates(["python"], min_stars=0, check_claims=True)
    assert candidates[0]["claim"] is None
