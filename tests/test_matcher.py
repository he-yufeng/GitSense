"""Tests for the deterministic, key-less matcher behind find --no-llm."""

from datetime import datetime, timedelta, timezone

from gitsense.matcher import rank_locally, score_match


def _candidate(**over):
    base = {
        "repo": "o/r",
        "title": "untitled issue",
        "url": "https://github.com/o/r/issues/1",
        "labels": [],
        "comments": 0,
        "created_at": "2026-05-01",
        "updated_at": "2026-05-12",
        "body": "nothing relevant here",
        "claim": None,
    }
    base.update(over)
    return base


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _old() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=200)).isoformat()


def test_title_hit_beats_body_hit():
    body_only, _ = score_match(_candidate(body="a python repro"), ["python"])
    in_title, reasons = score_match(_candidate(title="python crash on exit"), ["python"])
    assert in_title > body_only
    assert "title mentions python" in reasons


def test_word_boundaries_keep_go_out_of_django():
    score, reasons = score_match(_candidate(title="django admin glitch"), ["go"])
    assert all("go" not in r.split("mentions ")[-1] for r in reasons if "mentions" in r)
    assert score == 3  # base only: no skill evidence


def test_symbol_skills_like_cpp_match():
    score, reasons = score_match(_candidate(title="C++17 build breaks on arm64"), ["c++"])
    assert score > 3
    assert "title mentions c++" in reasons


def test_skill_evidence_caps_at_eight_without_bonuses():
    skills = ["python", "cuda", "llm", "rust", "wasm"]
    score, _ = score_match(
        _candidate(title="python cuda llm rust wasm", body="python cuda llm rust wasm"), skills
    )
    assert score == 8


def test_newcomer_label_adds_two():
    plain, _ = score_match(_candidate(title="python bug"), ["python"])
    labeled, reasons = score_match(
        _candidate(title="python bug", labels=["good first issue"]), ["python"]
    )
    assert labeled == plain + 2
    assert any("good first issue" in r for r in reasons)


def test_freshness_bonus_and_stale_silence():
    fresh, reasons = score_match(_candidate(title="python bug", updated_at=_today()), ["python"])
    stale, stale_reasons = score_match(
        _candidate(title="python bug", updated_at=_old()), ["python"]
    )
    assert fresh == stale + 1
    assert any("active in the last two weeks" in r for r in reasons)
    assert not any("active" in r for r in stale_reasons)


def test_noisy_thread_pulls_down():
    quiet, _ = score_match(_candidate(title="python bug", comments=2), ["python"])
    loud, reasons = score_match(_candidate(title="python bug", comments=42), ["python"])
    assert loud == quiet - 1
    assert any("42 comments" in r for r in reasons)


def test_claim_penalty_and_reason():
    claim = {"user": "octocat", "date": "2026-10-01", "phrase": "i'll take this"}
    free, _ = score_match(_candidate(title="python bug"), ["python"])
    taken, reasons = score_match(_candidate(title="python bug", claim=claim), ["python"])
    assert taken == free - 2
    assert any("@octocat" in r for r in reasons)


def test_no_evidence_reason_is_honest():
    _, reasons = score_match(_candidate(), ["python"])
    assert reasons == ["matched the search query; no direct skill mention in title, labels or body"]


def test_score_stays_within_one_to_ten():
    low, _ = score_match(
        _candidate(comments=99, claim={"user": "x", "date": "", "phrase": "mine"}), ["python"]
    )
    high, _ = score_match(
        _candidate(
            title="python cuda llm rust wasm",
            body="python cuda llm rust wasm",
            labels=["good first issue"],
            updated_at=_today(),
        ),
        ["python", "cuda", "llm", "rust", "wasm"],
    )
    assert low == 1
    assert high == 10


def test_rank_locally_sorts_and_caps():
    pool = [
        _candidate(title="nothing here", url="u1"),
        _candidate(title="python crash", url="u2"),
        _candidate(title="python cuda crash", labels=["good first issue"], url="u3"),
    ]
    ranked = rank_locally(pool, ["python", "cuda"], limit=2)
    assert [r["url"] for r in ranked] == ["u3", "u2"]
    assert ranked[0]["reason"]
    assert ranked[0]["approach"] == ""
    assert all(isinstance(r["match_score"], int) for r in ranked)


def test_rank_locally_pool_is_the_ceiling():
    assert len(rank_locally([_candidate()], ["python"], limit=15)) == 1


def test_llm_credentials_available(monkeypatch):
    from gitsense.finder import llm_credentials_available

    for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert not llm_credentials_available(None)
    assert llm_credentials_available("sk-explicit")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    assert llm_credentials_available(None)
