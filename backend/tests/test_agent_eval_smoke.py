import os

import pytest

from evals.expectations import check_expectations, load_case


def test_example_case_loads():
    from pathlib import Path

    case_path = Path(__file__).resolve().parent.parent / "evals" / "cases" / "example_smoke.yaml"
    case = load_case(case_path)
    assert case["id"] == "example_smoke"
    assert "user_message" in case


def test_thread_case_loads():
    from pathlib import Path

    case_path = (
        Path(__file__).resolve().parent.parent
        / "evals"
        / "cases"
        / "th_remember_then_list_memories.yaml"
    )
    case = load_case(case_path)
    assert case["id"] == "th_remember_then_list_memories"
    assert len(case["turns"]) == 2


def test_check_expectations_tools():
    events = [
        {"type": "tool_call_start", "name": "mcp__staffing__list_projects", "trace_id": "x"},
    ]
    ok, checks, score = check_expectations(
        events,
        {"must_call_tools": ["mcp__staffing__"], "max_tool_calls": 5},
    )
    assert ok
    assert score == 1.0


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("RUN_AGENT_EVAL"),
    reason="Set RUN_AGENT_EVAL=1 to run live agent smoke (costs API usage)",
)
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY required for live agent eval",
)
def test_live_eval_runner_end_to_end():
    from evals.runner import main
    from pathlib import Path

    case_path = Path(__file__).resolve().parent.parent / "evals" / "cases" / "example_smoke.yaml"
    code = main(["--case", str(case_path), "--runs", "1"])
    assert code in (0, 1)
