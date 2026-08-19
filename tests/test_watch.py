"""Tests for the find --watch state and delta logic."""

from gitsense.watch import (
    diff_watch,
    load_watch,
    query_key,
    save_watch,
    watch_path,
)


def _results(*urls: str) -> list[dict]:
    return [{"url": u, "title": f"issue at {u}"} for u in urls]


def test_first_watch_records_baseline(tmp_path):
    state = {}
    key = query_key(["python"], 100, [], 180, False, False, None)
    new, first_seen = diff_watch(state, key, _results("u1", "u2"))
    assert first_seen is None
    assert {r["url"] for r in new} == {"u1", "u2"}
    # Second run with the same results yields nothing new.
    new2, first_seen2 = diff_watch(state, key, _results("u1", "u2"))
    assert first_seen2 is not None
    assert new2 == []


def test_watch_reports_only_new_urls(tmp_path):
    state = {}
    key = query_key(["python"], 100, [], 180, False, False, None)
    diff_watch(state, key, _results("u1"))
    new, _ = diff_watch(state, key, _results("u1", "u2", "u3"))
    assert [r["url"] for r in new] == ["u2", "u3"]


def test_watch_state_roundtrips_through_disk(tmp_path):
    path = watch_path(str(tmp_path))
    key = query_key(["python"], 100, [], 180, False, False, None)
    state = {}
    diff_watch(state, key, _results("u1"))
    save_watch(state, path)
    loaded = load_watch(path)
    new, first_seen = diff_watch(loaded, key, _results("u1", "u2"))
    assert [r["url"] for r in new] == ["u2"]
    assert first_seen is not None


def test_watch_filters_keep_separate_histories():
    state = {}
    key_py = query_key(["python"], 100, [], 180, False, False, None)
    key_cuda = query_key(["cuda"], 100, [], 180, False, False, None)
    diff_watch(state, key_py, _results("u1"))
    # The same URL under a different filter signature is still new there.
    new, _ = diff_watch(state, key_cuda, _results("u1"))
    assert [r["url"] for r in new] == ["u1"]


def test_watch_seen_set_survives_result_churn():
    state = {}
    key = query_key(["python"], 100, [], 180, False, False, None)
    diff_watch(state, key, _results("u1", "u2"))
    # u1 drops out of the result set entirely, then comes back: still seen.
    diff_watch(state, key, _results("u2"))
    new, _ = diff_watch(state, key, _results("u1"))
    assert new == []


def test_query_key_normalizes_order_and_case():
    a = query_key(["Python", " cuda "], 100, ["Bug"], 180, False, False, None)
    b = query_key(["cuda", "python"], 100, ["bug"], 180, False, False, None)
    assert a != b  # the stray space stays significant, case folds
    c = query_key(["python", "cuda"], 100, ["bug"], 180, False, False, None)
    assert c != a  # sanity: the spaced " cuda " differs from "cuda"
    d = query_key(["python", "cuda"], 100, ["bug"], 180, False, False, None)
    assert c == d  # same inputs, same key


def test_load_watch_tolerates_corrupt_file(tmp_path):
    path = watch_path(str(tmp_path))
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert load_watch(path) == {}
    assert load_watch(str(tmp_path / "nope" / "watch.json")) == {}
