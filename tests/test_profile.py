"""Tests for the GitHub profile skill inference."""

from gitsense.profile import infer_skills


def _repo(language, stars=0, fork=False):
    return {"language": language, "stargazers_count": stars, "fork": fork}


def _patch(monkeypatch, repos):
    monkeypatch.setattr("gitsense.profile.fetch_user_repos", lambda username, per_page=100: repos)


def test_languages_ranked_by_weighted_usage(monkeypatch):
    _patch(monkeypatch, [
        _repo("Python", stars=200),
        _repo("Python", stars=10),
        _repo("Rust", stars=5),
        _repo("Shell", stars=0),
    ])
    result = infer_skills("someone")
    assert result["top"][0] == "Python"
    assert result["top"].index("Rust") < result["top"].index("Shell")
    assert result["repo_count"] == 4


def test_forks_are_skipped(monkeypatch):
    _patch(monkeypatch, [
        _repo("Go", stars=500, fork=True),
        _repo("Python", stars=1),
    ])
    result = infer_skills("someone")
    assert result["top"] == ["Python"]
    assert result["skipped_forks"] == 1
    assert result["repo_count"] == 1


def test_repos_without_language_are_ignored(monkeypatch):
    _patch(monkeypatch, [_repo(None, stars=50), _repo("TypeScript", stars=3)])
    result = infer_skills("someone")
    assert result["top"] == ["TypeScript"]
    assert result["repo_count"] == 1


def test_star_weight_is_capped(monkeypatch):
    _patch(monkeypatch, [
        _repo("Python", stars=1_000_000),
        _repo("Rust", stars=1000),
    ])
    result = infer_skills("someone")
    weights = dict(result["languages"])
    # the million-star repo must not outweigh the thousand-star one by more
    # than the cap allows: both land at the same ceiling weight
    assert weights["Python"] == weights["Rust"]


def test_empty_profile_when_nothing_usable(monkeypatch):
    _patch(monkeypatch, [_repo(None), _repo("Go", fork=True)])
    result = infer_skills("someone")
    assert result["top"] == []
    assert result["repo_count"] == 0
