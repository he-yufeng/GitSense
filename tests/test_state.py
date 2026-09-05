"""Tests for the per-user state directory and legacy CWD migration."""

import os

from gitsense.state import resolve_state_file, state_dir


def test_state_dir_defaults_to_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert state_dir(None) == str(tmp_path / ".gitsense")


def test_state_dir_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    override = tmp_path / "custom"
    assert state_dir(str(override)) == str(override)
    assert resolve_state_file(str(override), "watch.json") == str(override / "watch.json")


def test_default_location_when_no_legacy_file(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    path = resolve_state_file(None, "watch.json")
    assert path == os.path.join(str(home), ".gitsense", "watch.json")
    assert not os.path.exists(path)  # resolution alone creates nothing


def test_legacy_cwd_file_is_copied_once(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "work"
    legacy_dir = work / ".gitsense"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "watch.json"
    legacy_file.write_text('{"k": {"seen": ["u1"]}}', encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(work)

    path = resolve_state_file(None, "watch.json")
    assert path == os.path.join(str(home), ".gitsense", "watch.json")
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == '{"k": {"seen": ["u1"]}}'
    # copy, not move: the legacy file stays put
    assert legacy_file.exists()


def test_existing_new_file_is_not_overwritten_by_legacy(monkeypatch, tmp_path):
    home = tmp_path / "home"
    new_dir = home / ".gitsense"
    new_dir.mkdir(parents=True)
    new_file = new_dir / "triage-last.json"
    new_file.write_text('[{"n": 1}]', encoding="utf-8")

    work = tmp_path / "work"
    legacy_dir = work / ".gitsense"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "triage-last.json").write_text('[{"n": 2}]', encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(work)

    path = resolve_state_file(None, "triage-last.json")
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == '[{"n": 1}]'
