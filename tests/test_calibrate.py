"""Difficulty estimation and calibration against closed-issue history."""

from datetime import datetime, timedelta, timezone

from gitsense.calibrate import (
    bucket_name,
    build_report,
    effort_note,
    load_report,
    save_report,
)
from gitsense.matcher import estimate_difficulty


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).date().isoformat()


def _candidate(**over):
    base = {
        "repo": "o/r",
        "title": "untitled issue",
        "url": "https://github.com/o/r/issues/1",
        "labels": [],
        "comments": 0,
        "created_at": _iso(30),
        "updated_at": _iso(5),
        "body": "nothing relevant here",
        "claim": None,
    }
    base.update(over)
    return base


# --- estimate_difficulty ------------------------------------------------------


def test_baseline_issue_is_medium():
    score, _ = estimate_difficulty(_candidate(), skills=[])
    assert 4 <= score <= 6


def test_newcomer_label_pulls_down():
    score, reasons = estimate_difficulty(
        _candidate(labels=["good first issue"]), skills=[]
    )
    assert score <= 3
    assert any("newcomers" in r for r in reasons)


def test_skill_area_pulls_down():
    easy, _ = estimate_difficulty(_candidate(title="fix cuda graph capture"), skills=["cuda"])
    hard, _ = estimate_difficulty(_candidate(title="fix cuda graph capture"), skills=[])
    assert easy < hard


def test_noisy_and_stale_push_up():
    score, reasons = estimate_difficulty(
        _candidate(comments=87, created_at=_iso(500)), skills=[]
    )
    assert score >= 7
    assert any("thread" in r for r in reasons)
    assert any("year" in r for r in reasons)


def test_claim_adds_effort():
    claimed, _ = estimate_difficulty(_candidate(claim={"user": "x", "date": "d"}), skills=[])
    plain, _ = estimate_difficulty(_candidate(), skills=[])
    assert claimed == plain + 1


def test_score_is_clamped():
    score, _ = estimate_difficulty(
        _candidate(labels=["good first issue"], title="python sql redis"), skills=["python", "sql", "redis"]
    )
    assert 1 <= score <= 10


# --- buckets and report --------------------------------------------------------


def _closed_item(difficulty_hint: str, close_days: float):
    """Build a search-API-shaped closed issue landing in a chosen bucket."""
    created = datetime.now(timezone.utc) - timedelta(days=close_days + 30)
    closed = created + timedelta(days=close_days)
    item = {
        "title": "some issue",
        "labels": ["good first issue"] if difficulty_hint == "easy" else [],
        "comments": 0 if difficulty_hint == "easy" else 60,
        "created_at": created.isoformat(),
        "closed_at": closed.isoformat(),
        "body": "",
        "claim": None,
    }
    return item


def test_bucket_boundaries():
    assert bucket_name(1) == "easy"
    assert bucket_name(3) == "easy"
    assert bucket_name(4) == "medium"
    assert bucket_name(6) == "medium"
    assert bucket_name(7) == "hard"


def test_report_tracks_reality_when_harder_took_longer():
    items = [
        _closed_item("easy", 2.0),
        _closed_item("easy", 4.0),
        _closed_item("hard", 40.0),
        _closed_item("hard", 60.0),
    ]
    report = build_report("me", items, skills=[])
    easy = next(b for b in report.buckets if b.name == "easy")
    hard = next(b for b in report.buckets if b.name == "hard")
    assert easy.median_days == 3.0
    assert hard.median_days == 50.0
    assert "tracks" in report.verdict


def test_report_flags_inversion():
    items = [
        _closed_item("easy", 40.0),
        _closed_item("easy", 60.0),
        _closed_item("hard", 2.0),
        _closed_item("hard", 4.0),
    ]
    report = build_report("me", items, skills=[])
    assert "do not rise" in report.verdict


def test_report_is_honest_with_too_little_history():
    report = build_report("me", [_closed_item("easy", 2.0)], skills=[])
    assert "anecdote" in report.verdict


# --- persistence and annotation ----------------------------------------------


def test_save_and_load_roundtrip(tmp_path):
    items = [_closed_item("easy", 2.0), _closed_item("easy", 4.0), _closed_item("hard", 50.0)]
    report = build_report("me", items, skills=[])
    save_report(report, str(tmp_path))
    loaded = load_report(str(tmp_path))
    assert loaded is not None
    assert loaded.username == "me"
    assert loaded.total_closed == 3
    assert loaded.days_for(2) == 3.0
    assert loaded.days_for(8) == 50.0


def test_load_missing_report_returns_none(tmp_path):
    assert load_report(str(tmp_path)) is None


def test_effort_note_with_and_without_calibration(tmp_path):
    plain = effort_note(4, None)
    assert plain == "effort ~4/10"
    items = [_closed_item("easy", 2.0), _closed_item("easy", 4.0), _closed_item("hard", 9.0)]
    report = build_report("me", items, skills=[])
    note = effort_note(4, report)
    assert "effort ~4/10" in note
    # bucket for 4 is medium; only easy/hard have data, so no days suffix
    assert note == "effort ~4/10"
    note_hard = effort_note(8, report)
    assert "median of 9d" in note_hard
