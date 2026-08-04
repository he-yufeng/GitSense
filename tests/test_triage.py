from gitsense.triage import build_row, next_action, sort_rows


def _action(**overrides) -> str:
    signals = {
        "review_decision": None,
        "is_draft": False,
        "mergeable_state": "clean",
        "ci_failing": False,
        "updated_days": 2.0,
        "stale_days": 14,
    }
    signals.update(overrides)
    return next_action(**signals)


def test_next_action_priority_order():
    # draft beats everything: nobody will look until it's ready
    assert _action(is_draft=True, review_decision="CHANGES_REQUESTED") == "mark ready for review"
    # requested changes beat red CI and conflicts
    assert _action(review_decision="CHANGES_REQUESTED", ci_failing=True) == "address the review"
    # red CI beats conflicts
    assert _action(ci_failing=True, mergeable_state="DIRTY") == "fix CI"
    assert _action(mergeable_state="CONFLICTING") == "rebase to clear conflicts"


def test_next_action_approved_and_stale():
    assert _action(review_decision="APPROVED") == "approved & green — nudge for merge"
    assert _action(updated_days=20.0) == "no review in 20d — ping"
    assert _action(updated_days=3.0) == "waiting on reviewer"


def _search_item(**overrides):
    item = {
        "number": 42,
        "title": "fix the thing",
        "html_url": "https://github.com/o/r/pull/42",
        "repository_url": "https://api.github.com/repos/o/r",
        "draft": False,
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }
    item.update(overrides)
    return item


def _pr_payload(**overrides):
    pr = {
        "draft": False,
        "additions": 25,
        "changed_files": 2,
        "mergeable_state": "clean",
        "created_at": "2026-07-01T00:00:00Z",
    }
    pr.update(overrides)
    return pr


def test_build_row_shallow_has_no_score():
    row = build_row(_search_item(), stale_days=14)
    assert row.repo == "o/r"
    assert row.number == 42
    assert row.score is None
    assert row.action == "waiting on reviewer"


def test_build_row_enriched_scores_and_acts():
    row = build_row(
        _search_item(),
        pr=_pr_payload(),
        review_decision="APPROVED",
        ci_failing=False,
        touches_tests=True,
        stale_days=14,
    )
    assert row.score is not None and row.score >= 70
    assert row.action == "approved & green — nudge for merge"
    assert row.notes


def test_build_row_enriched_changes_requested():
    row = build_row(
        _search_item(),
        pr=_pr_payload(),
        review_decision="CHANGES_REQUESTED",
        ci_failing=True,
        touches_tests=False,
        stale_days=14,
    )
    assert row.action == "address the review"


def test_sort_rows_worst_first_unscored_last():
    good = build_row(_search_item(number=1), pr=_pr_payload(), review_decision="APPROVED",
                     touches_tests=True)
    bad = build_row(_search_item(number=2), pr=_pr_payload(), review_decision="CHANGES_REQUESTED",
                    ci_failing=True)
    shallow = build_row(_search_item(number=3))
    rows = sort_rows([good, shallow, bad])
    assert [r.number for r in rows] == [2, 1, 3]
    assert rows[0].score is not None and rows[0].score < rows[1].score
