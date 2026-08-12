"""
Unit tests for Day 8 — Call Analytics Dashboard database and logic.
"""

import pytest

from db import (
    finalize_call,
    get_analytics_summary,
    get_recent_calls,
    init_db,
    mark_call_outcome,
    record_call_start,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Use isolated SQLite database for test session."""
    db_file = str(tmp_path / "test_analytics.db")
    monkeypatch.setenv("BOLBUDDY_DB_PATH", db_file)
    init_db(db_path=db_file)
    return db_file


def test_record_call_start():
    """Verify call session start is recorded properly."""
    res = record_call_start(call_id="call_test_01", user_id="user_101", channel="browser")
    assert res["success"] is True
    assert res["call_id"] == "call_test_01"
    assert res["outcome"] == "in_progress"
    assert res["channel"] == "browser"


def test_successful_call_flow():
    """Verify a call that completes an exercise is recorded as successful."""
    call_id = "call_test_success_1"
    record_call_start(call_id=call_id, user_id="user_success", channel="browser")

    # Learner completes a speaking exercise
    mark_res = mark_call_outcome(
        call_id=call_id,
        outcome="success",
        completed_activities_inc=1,
    )
    assert mark_res["success"] is True
    assert mark_res["outcome"] == "success"
    assert mark_res["completed_activities"] == 1

    # End session
    fin_res = finalize_call(call_id=call_id)
    assert fin_res["success"] is True
    assert fin_res["outcome"] == "success"
    assert fin_res["failure_reason"] is None


def test_failed_call_flow():
    """Verify a call where learner leaves before completing activity is recorded as failed."""
    call_id = "call_test_failed_1"
    record_call_start(call_id=call_id, user_id="user_failed", channel="sip")

    # Session ends early without completing exercise
    fin_res = finalize_call(
        call_id=call_id,
        default_outcome="failed",
        default_reason="user_hangup",
    )
    assert fin_res["success"] is True
    assert fin_res["outcome"] == "failed"
    assert fin_res["failure_reason"] == "user_hangup"


def test_analytics_summary_calculation():
    """Verify totals, success rate, and completed activities calculated correctly."""
    # 2 Successful calls, 1 Failed call
    c1 = "call_sum_1"
    record_call_start(c1, "u1", "browser")
    mark_call_outcome(c1, "success", completed_activities_inc=2)
    finalize_call(c1)

    c2 = "call_sum_2"
    record_call_start(c2, "u2", "browser")
    mark_call_outcome(c2, "success", completed_activities_inc=1)
    finalize_call(c2)

    c3 = "call_sum_3"
    record_call_start(c3, "u3", "sip")
    finalize_call(c3, default_outcome="failed", default_reason="incomplete_exercise")

    summary = get_analytics_summary()
    assert summary["success"] is True
    assert summary["total_calls"] == 3
    assert summary["successful_calls"] == 2
    assert summary["failed_calls"] == 1
    assert summary["completed_activities"] == 3
    assert summary["success_rate"] == 66.7
    assert summary["failure_reasons"] == {"incomplete_exercise": 1}


def test_get_recent_calls():
    """Verify recent calls list formatting and lack of transcript data."""
    c_id = "call_recent_01"
    record_call_start(c_id, "user_rec", "browser")
    mark_call_outcome(c_id, "success", completed_activities_inc=1)
    finalize_call(c_id)

    recent = get_recent_calls(limit=5)
    assert len(recent) == 1
    rec = recent[0]
    assert "duration_formatted" in rec


def test_early_hangup_vs_completed_evaluation_flow():
    """
    Explicit test for Day 8 logic:
    Call starts -> in_progress -> Learner hangs up early -> FAILED
    vs.
    Call starts -> in_progress -> Exercise actually evaluated/completed -> SUCCESS
    """
    # Case 1: Learner hangs up immediately without doing any activity
    c1 = "call_early_hangup"
    record_call_start(c1, "u1", "browser")
    res1 = finalize_call(c1, default_outcome="failed", default_reason="user_hangup")
    assert res1["outcome"] == "failed"
    assert res1["failure_reason"] == "user_hangup"

    # Case 2: Learner leaves mid-exercise without successful evaluation
    c2 = "call_mid_exercise"
    record_call_start(c2, "u2", "browser")
    res2 = finalize_call(c2, default_outcome="failed", default_reason="incomplete_exercise")
    assert res2["outcome"] == "failed"
    assert res2["failure_reason"] == "incomplete_exercise"

    # Case 3: Learner actually completes exercise evaluation successfully
    c3 = "call_completed_exercise"
    record_call_start(c3, "u3", "browser")
    mark_call_outcome(c3, outcome="success", completed_activities_inc=1)
    res3 = finalize_call(c3)
    assert res3["outcome"] == "success"
    assert res3["failure_reason"] is None

