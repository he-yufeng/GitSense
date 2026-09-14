"""The --format html report must be self-contained and injection-safe."""

from __future__ import annotations

from gitsense.finder import render_html as render_find_html
from gitsense.radar import RepoRadarReport
from gitsense.radar import render_html as render_radar_html


def _find_result(**overrides) -> dict:
    base = {
        "repo": "owner/project",
        "title": "Fix the thing",
        "url": "https://github.com/owner/project/issues/1",
        "match_score": 8,
        "labels": ["bug", "good first issue"],
        "reason": "matches your skills",
        "approach": "start at the parser",
        "claim": {"user": "someone", "date": "2026-09-01"},
    }
    base.update(overrides)
    return base


def _radar_report(**overrides) -> RepoRadarReport:
    base = {
        "repo": "owner/project",
        "score": 82,
        "recommendation": "Contribute",
        "stars": 12000,
        "primary_language": "Python",
        "merged_prs": 5,
        "open_prs": 2,
        "stale_prs": 1,
        "stale_ratio": 0.2,
        "open_to_merged_ratio": 0.4,
        "median_merge_days": 7.0,
        "median_maintainer_response_days": 2.0,
        "external_merged_ratio": 0.6,
        "skill_matches": ["python"],
        "notes": ["active maintainers"],
        "risk_flags": [],
    }
    base.update(overrides)
    return RepoRadarReport(**base)


def test_find_html_is_self_contained_and_inline_styled():
    html = render_find_html([_find_result()], ["python", "llm"])
    assert html.startswith("<!DOCTYPE html>")
    assert 'style="' in html
    # no external assets: email clients block them anyway
    assert "<link" not in html and "<script" not in html and "http-equiv" not in html
    assert "https://github.com/owner/project/issues/1" in html
    assert "Fix the thing" in html


def test_find_html_escapes_injected_markup():
    html = render_find_html(
        [_find_result(title='<img src=x onerror="alert(1)">', repo="<b>x</b>")],
        ["python"],
    )
    assert "<img src=x onerror=" not in html
    assert "&lt;img src=x onerror=" in html
    assert "<b>x</b>" not in html


def test_radar_html_table_and_details():
    html = render_radar_html([_radar_report()])
    assert html.startswith("<!DOCTYPE html>")
    assert "<table" in html and "owner/project" in html
    assert "Contribute" in html
    assert "active maintainers" in html


def test_radar_html_escapes_injected_markup():
    html = render_radar_html([_radar_report(notes=['<script>alert(1)</script>'])])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
