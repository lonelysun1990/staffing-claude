"""CLI to run YAML eval cases against run_agent_stream."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import app.orm_models  # noqa: F401 — register models on Base.metadata

from app.auth import UserORM, hash_password
from app.database import Base, SessionLocal, engine
from app.seed_db import seed

from .expectations import (
    assistant_text_from_events,
    build_synthetic_events,
    check_expectations,
    load_case,
    session_id_from_events,
    tool_names_from_events,
)
from .fixture_loader import load_eval_fixture
from .sse_parse import parse_sse_stream
from .stats import mean, pass_at_least_once, pass_rate


def ensure_eval_user(db: Session) -> UserORM:
    username = os.environ.get("EVAL_USERNAME", "eval_runner")
    row = db.query(UserORM).filter(UserORM.username == username).first()
    if row:
        return row
    password = os.environ.get("EVAL_USER_PASSWORD", "eval-change-me")
    row = UserORM(
        username=username,
        hashed_password=hash_password(password),
        role="manager",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


async def run_single_turn(
    db: Session,
    user_id: int,
    session_id: Optional[int],
    user_message: str,
) -> Dict[str, Any]:
    from app.agent.loop import run_agent_stream
    from app.agent.models import AgentRequest, ChatMessage

    req = AgentRequest(
        messages=[ChatMessage(role="user", content=user_message)],
        session_id=session_id,
    )
    stream = run_agent_stream(req, db, user_id=user_id)
    events = await parse_sse_stream(stream)
    return {
        "events": events,
        "tool_names": tool_names_from_events(events),
        "assistant_text": assistant_text_from_events(events),
        "session_id": session_id_from_events(events),
    }


def _normalize_turns(case: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "turns" in case:
        return case["turns"]
    return [{"user_message": case["user_message"], "expect": case.get("expect") or {}}]


async def run_case_async(case: Dict[str, Any], db: Session, user_id: int) -> Dict[str, Any]:
    turns_out: List[Dict[str, Any]] = []
    session_id: Optional[int] = None
    merged_tools: List[str] = []
    merged_text_parts: List[str] = []

    for turn in _normalize_turns(case):
        msg = turn["user_message"]
        out = await run_single_turn(db, user_id, session_id, msg)
        if out["session_id"] is not None:
            session_id = out["session_id"]
        merged_tools.extend(out["tool_names"])
        merged_text_parts.append(out["assistant_text"])
        exp_turn = turn.get("expect") or {}
        passed_t, checks_t, score_t = check_expectations(out["events"], exp_turn)
        turns_out.append(
            {
                "user_message": msg,
                "passed": passed_t,
                "score": score_t,
                "checks": checks_t,
                "tool_names": out["tool_names"],
                "session_id": out["session_id"],
            }
        )

    root_expect = (case.get("expect") or {}) if "turns" in case else {}
    thread_passed = True
    thread_checks: List[Dict[str, Any]] = []
    thread_score = 1.0
    if root_expect:
        merged_text = "\n".join(merged_text_parts)
        syn = build_synthetic_events(merged_tools, merged_text)
        thread_passed, thread_checks, thread_score = check_expectations(syn, root_expect)

    all_passed = all(t["passed"] for t in turns_out) and thread_passed

    return {
        "turns": turns_out,
        "thread_expect": {
            "passed": thread_passed,
            "score": thread_score,
            "checks": thread_checks,
        }
        if root_expect
        else None,
        "passed": all_passed,
        "merged_tool_names": merged_tools,
    }


async def run_eval_batch(
    case_files: List[Path],
    cases_dir: Path,
    runs_override: Optional[int],
) -> Dict[str, Any]:
    """Run all cases under one event loop (avoids asyncio.run per case + SDK cancel issues)."""
    report: Dict[str, Any] = {"cases": []}

    for cf in case_files:
        case = load_case(cf)
        runs = runs_override if runs_override is not None else int(case.get("runs") or 1)
        fixture = case.get("fixture")
        case_result: Dict[str, Any] = {
            "id": case["id"],
            "file": str(cf),
            "runs": [],
        }

        for run_idx in range(runs):
            db = SessionLocal()
            try:
                if fixture:
                    fp = (cases_dir.parent / fixture).resolve() if not Path(str(fixture)).is_absolute() else Path(fixture)
                    if not fp.is_file():
                        raise FileNotFoundError(f"Fixture not found: {fp}")
                    load_eval_fixture(db, fp)
                else:
                    default_fp = cases_dir.parent / "fixtures" / "mini_store.json"
                    if default_fp.is_file():
                        load_eval_fixture(db, default_fp)
                    else:
                        seed()

                user = ensure_eval_user(db)
                out = await run_case_async(case, db, user.id)

                turns = out["turns"]
                tr_expect = out.get("thread_expect")
                scores = [t["score"] for t in turns]
                if tr_expect:
                    scores.append(tr_expect["score"])
                mean_score = mean(scores) if scores else 1.0

                case_result["runs"].append(
                    {
                        "run": run_idx,
                        "passed": out["passed"],
                        "score": mean_score,
                        "turns": turns,
                        "thread_expect": tr_expect,
                        "merged_tool_names": out["merged_tool_names"],
                    }
                )
            finally:
                db.close()

        run_passes = [r["passed"] for r in case_result["runs"]]
        case_result["pass_rate"] = pass_rate(run_passes)
        case_result["mean_score"] = mean([r["score"] for r in case_result["runs"]])
        case_result["pass_at_least_once"] = pass_at_least_once(run_passes)
        report["cases"].append(case_result)

    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run staffing agent eval cases")
    parser.add_argument("--case", type=Path, help="Path to a single YAML case")
    parser.add_argument("--all", action="store_true", help="Run all cases in evals/cases/*.yaml")
    parser.add_argument("--runs", type=int, default=None, help="Override per-case runs")
    args = parser.parse_args(argv)

    cases_dir = Path(__file__).resolve().parent / "cases"
    case_files: List[Path] = []
    if args.all:
        case_files = sorted(cases_dir.glob("*.yaml"))
        if not case_files:
            print("No cases found in", cases_dir, file=sys.stderr)
            return 1
    elif args.case:
        case_files = [args.case]
    else:
        parser.error("Provide --case PATH or --all")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is required for live agent eval.", file=sys.stderr)
        return 1

    Base.metadata.create_all(bind=engine)

    # Single asyncio.run for the whole batch — multiple asyncio.run() calls break Claude Agent SDK / anyio.
    report = asyncio.run(run_eval_batch(case_files, cases_dir, args.runs))

    print(json.dumps(report, indent=2))
    overall = all(all(r["passed"] for r in c["runs"]) for c in report["cases"])
    return 0 if overall else 1
