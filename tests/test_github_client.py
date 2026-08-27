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
