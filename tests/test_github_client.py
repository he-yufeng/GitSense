"""Tests for GitHub token resolution."""

import subprocess

import pytest

from gitsense import github_client


@pytest.fixture(autouse=True)
def clean_token_state(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    github_client._get_token.cache_clear()
    yield
    github_client._get_token.cache_clear()


def _completed(returncode=0, stdout=""):
    return subprocess.CompletedProcess(args=["gh", "auth", "token"], returncode=returncode, stdout=stdout)


def test_env_token_used_without_calling_gh(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")

    def fail_run(*args, **kwargs):
        raise AssertionError("gh should not run when GITHUB_TOKEN is set")

    monkeypatch.setattr(subprocess, "run", fail_run)
    assert github_client._get_headers()["Authorization"] == "Bearer env-token"


def test_gh_token_used_when_env_missing(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(stdout="cli-token\n"))
    headers = github_client._get_headers()
    assert headers["Authorization"] == "Bearer cli-token"
    assert "gh CLI" in capsys.readouterr().err


def test_env_wins_over_gh(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "env-token")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(stdout="cli-token"))
    assert github_client._get_headers()["Authorization"] == "Bearer env-token"


def test_gh_missing_falls_back_to_anonymous(monkeypatch):
    def raise_fnf(*args, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(subprocess, "run", raise_fnf)
    assert "Authorization" not in github_client._get_headers()


def test_gh_nonzero_exit_falls_back(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(returncode=1, stdout="junk"))
    assert "Authorization" not in github_client._get_headers()


def test_gh_timeout_falls_back(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["gh", "auth", "token"], timeout=5)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert "Authorization" not in github_client._get_headers()


def test_gh_empty_output_falls_back(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(stdout="  \n"))
    assert "Authorization" not in github_client._get_headers()


def test_gh_called_with_short_timeout(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["argv"] = args[0]
        captured.update(kwargs)
        return _completed(stdout="cli-token")

    monkeypatch.setattr(subprocess, "run", fake_run)
    github_client._get_headers()
    assert captured["argv"] == ["gh", "auth", "token"]
    assert captured["timeout"] == 5


# ---------------------------------------------------------------------------
# get_commit_status_state: legacy status + Actions check runs folded together
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _ci_router(status_payload, check_run_pages):
    """Route by URL suffix: /status vs /check-runs (paged)."""
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if url.endswith("/status"):
            return _Resp(status_payload)
        page = (kwargs.get("params") or {}).get("page", 1)
        return _Resp({"check_runs": check_run_pages.get(page, [])})

    return fake_get, calls


def test_ci_state_legacy_failure_short_circuits(monkeypatch):
    fake_get, calls = _ci_router({"state": "failure"}, {})
    monkeypatch.setattr(github_client.httpx, "get", fake_get)

    assert github_client.get_commit_status_state("o", "r", "abc") == "failure"
    assert calls == ["https://api.github.com/repos/o/r/commits/abc/status"]


def test_ci_state_actions_failure_detected(monkeypatch):
    # Actions-only repo: legacy endpoint knows nothing, a check run is red
    fake_get, _ = _ci_router(
        {"state": "pending"},
        {1: [{"conclusion": "success"}, {"conclusion": "failure"}]},
    )
    monkeypatch.setattr(github_client.httpx, "get", fake_get)

    assert github_client.get_commit_status_state("o", "r", "abc") == "failure"


def test_ci_state_actions_green_keeps_legacy_state(monkeypatch):
    fake_get, _ = _ci_router(
        {"state": "success"},
        {1: [{"conclusion": "success"}, {"conclusion": "skipped"}]},
    )
    monkeypatch.setattr(github_client.httpx, "get", fake_get)

    assert github_client.get_commit_status_state("o", "r", "abc") == "success"


def test_ci_state_empty_everywhere_stays_empty(monkeypatch):
    fake_get, _ = _ci_router({"state": ""}, {1: []})
    monkeypatch.setattr(github_client.httpx, "get", fake_get)

    assert github_client.get_commit_status_state("o", "r", "abc") == ""


def test_ci_state_pages_check_runs(monkeypatch):
    page1 = [{"conclusion": "success"}] * 100
    page2 = [{"conclusion": "timed_out"}]
    fake_get, _ = _ci_router({"state": "pending"}, {1: page1, 2: page2})
    monkeypatch.setattr(github_client.httpx, "get", fake_get)

    assert github_client.get_commit_status_state("o", "r", "abc") == "failure"
