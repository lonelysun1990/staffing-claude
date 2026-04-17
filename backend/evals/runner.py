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

from .expectations import check_expectations, load_case, tool_names_from_events
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


async def run_case_once(
    case: Dict[str, Any],
    db: Session,
    user_id: int,
) -> Dict[str, Any]:
    from app.agent.loop import run_agent_stream
    from app.agent.models import AgentRequest, ChatMessage

    req = AgentRequest(
        messages=[ChatMessage(role="user", content=case["user_message"])],
        session_id=None,
    )
    stream = run_agent_stream(req, db, user_id=user_id)
    events = await parse_sse_stream(stream)
    return {"events": events, "tool_names": tool_names_from_events(events)}


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
    report: Dict[str, Any] = {"cases": []}

    for cf in case_files:
        case = load_case(cf)
        runs = args.runs if args.runs is not None else int(case.get("runs") or 1)
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
                out = asyncio.run(run_case_once(case, db, user.id))

                expect = case.get("expect") or {}
                passed, checks, score = check_expectations(out["events"], expect)
                case_result["runs"].append(
                    {
                        "run": run_idx,
                        "passed": passed,
                        "score": score,
                        "checks": checks,
                        "tool_names": out["tool_names"],
                    }
                )
            finally:
                db.close()

        run_passes = [r["passed"] for r in case_result["runs"]]
        case_result["pass_rate"] = pass_rate(run_passes)
        case_result["mean_score"] = mean([r["score"] for r in case_result["runs"]])
        case_result["pass_at_least_once"] = pass_at_least_once(run_passes)
        report["cases"].append(case_result)

    print(json.dumps(report, indent=2))
    overall = all(
        all(r["passed"] for r in c["runs"])
        for c in report["cases"]
    )
    return 0 if overall else 1
