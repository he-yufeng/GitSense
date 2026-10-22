"""CI-health and release-cadence scorecard factors."""

from gitsense.radar import ScoreFactor, scorecard_repo


def _factors(**over) -> dict[str, ScoreFactor]:
    base = dict(
        merged_prs=20,
        open_prs=10,
        stale_ratio=0.1,
        median_merge_days=5.0,
        median_maintainer_response_days=2.0,
        external_merged_ratio=0.5,
        skill_matches=[],
        stars=5000,
    )
    base.update(over)
    _score, factors = scorecard_repo(**base)
    return {f.key: f for f in factors}


def test_green_ci_adds_points():
    f = _factors(ci_success_rate=0.95, ci_runs_seen=10)["ci_health"]
    assert f.delta == 8
    assert "reliably green" in f.reason


def test_mostly_red_ci_costs_points():
    f = _factors(ci_success_rate=0.3, ci_runs_seen=10)["ci_health"]
    assert f.delta == -10
    assert "not yours" in f.reason


def test_middling_ci_is_neutral():
    f = _factors(ci_success_rate=0.7, ci_runs_seen=10)["ci_health"]
    assert f.delta == 0


def test_no_ci_runs_visible_is_honest_zero():
    f = _factors(ci_success_rate=None, ci_runs_seen=0)["ci_health"]
    assert f.delta == 0
    assert "no completed CI runs" in f.value


def test_regular_releases_add_points():
    f = _factors(releases_last_year=5, latest_release_days=30)["release_cadence"]
    assert f.delta == 6
    assert "regularly" in f.reason


def test_quiet_releases_cost_points():
    f = _factors(releases_last_year=0, latest_release_days=500)["release_cadence"]
    assert f.delta == -6
    assert "quiet" in f.reason


def test_no_releases_at_all_is_not_punished():
    # rolling-release repos are healthy; absence is reported, not scored
    f = _factors(releases_last_year=None, latest_release_days=None)["release_cadence"]
    assert f.delta == 0
    assert "no releases recorded" in f.value


def test_occasional_releases_are_neutral():
    f = _factors(releases_last_year=2, latest_release_days=100)["release_cadence"]
    assert f.delta == 0


def test_factors_compose_into_score():
    healthy = _factors(ci_success_rate=1.0, ci_runs_seen=10, releases_last_year=6)
    sick = _factors(ci_success_rate=0.2, ci_runs_seen=10, releases_last_year=0, latest_release_days=600)
    healthy_score = 50 + sum(f.delta for f in healthy.values())
    sick_score = 50 + sum(f.delta for f in sick.values())
    assert healthy_score - sick_score == 8 - (-10) + 6 - (-6)
