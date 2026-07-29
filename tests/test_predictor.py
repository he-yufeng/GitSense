import pytest

from gitsense.predictor import (
    analyze_pr,
    derive_review_decision,
    files_touch_tests,
    parse_pr_ref,
    prediction_label,
    score_pr,
)


def test_parse_pr_ref_accepts_url_and_short_form():
    assert parse_pr_ref("https://github.com/vllm-project/vllm/pull/123") == (
        "vllm-project",
        "vllm",
        123,
    )
    assert parse_pr_ref("vllm-project/vllm#456") == ("vllm-project", "vllm", 456)


def test_parse_pr_ref_rejects_garbage():
    with pytest.raises(ValueError):
        parse_pr_ref("not-a-pr-reference")


def test_derive_review_decision_uses_latest_per_reviewer():
    # alice approved then later requested changes -> changes win for her;
    # bob's lone approval would pass, but a CHANGES_REQUESTED anywhere wins.
    reviews = [
        {"user": {"login": "alice"}, "state": "APPROVED"},
        {"user": {"login": "alice"}, "state": "CHANGES_REQUESTED"},
        {"user": {"login": "bob"}, "state": "APPROVED"},
        {"user": {"login": "carol"}, "state": "COMMENTED"},  # ignored
    ]
    assert derive_review_decision(reviews) == "CHANGES_REQUESTED"


def test_derive_review_decision_approved_and_none():
    assert derive_review_decision([{"user": {"login": "a"}, "state": "APPROVED"}]) == "APPROVED"
    assert derive_review_decision([{"user": {"login": "a"}, "state": "COMMENTED"}]) is None
    assert derive_review_decision([]) is None


def test_files_touch_tests():
    assert files_touch_tests([{"filename": "src/app.py"}, {"filename": "tests/test_app.py"}])
    assert files_touch_tests([{"filename": "app/foo.spec.ts"}])
    assert not files_touch_tests([{"filename": "src/app.py"}, {"filename": "README.md"}])


def _score(**overrides) -> int:
    signals = {
        "review_decision": None,
        "is_draft": False,
        "mergeable_state": "CLEAN",
        "ci_failing": False,
        "changed_files": 2,
        "additions": 40,
        "touches_tests": True,
        "age_days": 3,
    }
    signals.update(overrides)
    score, _ = score_pr(**signals)
    return score


def test_approved_small_tested_pr_scores_high():
    score, notes = score_pr(
        review_decision="APPROVED",
        is_draft=False,
        mergeable_state="CLEAN",
        ci_failing=False,
        changed_files=2,
        additions=30,
        touches_tests=True,
        age_days=2,
    )
    assert score >= 70
    assert prediction_label(score) == "Likely to merge"
    assert "already approved by a reviewer" in notes


def test_changes_requested_draft_with_conflicts_scores_low():
    score, notes = score_pr(
        review_decision="CHANGES_REQUESTED",
        is_draft=True,
        mergeable_state="DIRTY",
        ci_failing=True,
        changed_files=40,
        additions=2000,
        touches_tests=False,
        age_days=120,
    )
    assert score <= 25
    assert "changes requested — address the review first" in notes
    assert "has merge conflicts — rebase onto the base branch" in notes


def test_each_negative_signal_lowers_the_score():
    base = _score()
    assert _score(review_decision="CHANGES_REQUESTED") < base
    assert _score(is_draft=True) < base
    assert _score(mergeable_state="DIRTY") < base
    assert _score(ci_failing=True) < base
    assert _score(changed_files=50, additions=3000) < base
    assert _score(age_days=200) < base


def test_score_is_clamped_to_0_100():
    low, _ = score_pr(
        review_decision="CHANGES_REQUESTED",
        is_draft=True,
        mergeable_state="DIRTY",
        ci_failing=True,
        changed_files=80,
        additions=9000,
        touches_tests=False,
        age_days=400,
    )
    assert 0 <= low <= 100


def test_prediction_label_thresholds():
    assert prediction_label(85) == "Likely to merge"
    assert prediction_label(55) == "Could go either way"
    assert prediction_label(30) == "Long shot"
    assert prediction_label(10) == "Unlikely as-is"


def test_analyze_pr_extracts_signals_from_payload():
    pr = {
        "draft": False,
        "additions": 25,
        "changed_files": 2,
        "mergeable_state": "clean",
        "created_at": "2026-06-18T00:00:00Z",
    }
    result = analyze_pr(pr, review_decision="APPROVED", ci_failing=False, touches_tests=True)
    assert result.score >= 70
    assert result.label == "Likely to merge"
    assert result.notes
