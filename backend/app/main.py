from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from . import storage
from .auth import (
    Token,
    UserCreate,
    UserORM,
    UserOut,
    create_access_token,
    get_current_user,
    get_user_or_none,
    hash_password,
    require_auth,
    require_manager,
    verify_password,
)
from .database import Base, engine, get_db
from .models import (
    Assignment,
    AssignmentCreate,
    AssignmentsPayload,
    AuditLogItem,
    BulkAssignPayload,
    ConfigModel,
    ConfigUpdate,
    ConflictItem,
    DataScientist,
    DataScientistCreate,
    ImportResult,
    Project,
    ProjectCreate,
)
from .agent import AgentRequest, AgentResponse, run_agent

# Create all tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Staffing Scheduler", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"


# Auth ----------------------------------------------------------------------- #

@app.post("/auth/register", response_model=UserOut, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> UserOut:
    existing = db.query(UserORM).filter(UserORM.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")
    user = UserORM(username=payload.username, hashed_password=hash_password(payload.password), role=payload.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut(id=user.id, username=user.username, role=user.role)


@app.post("/auth/token", response_model=Token)
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)) -> Token:
    user = db.query(UserORM).filter(UserORM.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user.username, "role": user.role})
    return Token(access_token=token, token_type="bearer")


@app.get("/auth/me", response_model=UserOut)
def me(current_user: UserORM = Depends(require_auth)) -> UserOut:
    return UserOut(id=current_user.id, username=current_user.username, role=current_user.role)


# Config -------------------------------------------------------------------- #

@app.get("/config", response_model=ConfigModel)
def get_config(db: Session = Depends(get_db)) -> ConfigModel:
    return storage.get_config(db)


@app.put("/config", response_model=ConfigModel)
def update_config(payload: ConfigUpdate, db: Session = Depends(get_db)) -> ConfigModel:
    return storage.update_config(db, payload)


# Data scientists ------------------------------------------------------------ #

@app.get("/data-scientists", response_model=List[DataScientist])
def list_data_scientists(db: Session = Depends(get_db)) -> List[DataScientist]:
    return storage.list_data_scientists(db)


@app.post("/data-scientists", response_model=DataScientist, status_code=201)
def create_data_scientist(payload: DataScientistCreate, db: Session = Depends(get_db), _: UserORM = Depends(require_manager)) -> DataScientist:
    return storage.create_data_scientist(db, payload)


@app.put("/data-scientists/{ds_id}", response_model=DataScientist)
def update_data_scientist(ds_id: int, payload: DataScientistCreate, db: Session = Depends(get_db), _: UserORM = Depends(require_manager)) -> DataScientist:
    try:
        return storage.update_data_scientist(db, ds_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/data-scientists/{ds_id}", status_code=204, response_model=None)
def delete_data_scientist(ds_id: int, db: Session = Depends(get_db), _: UserORM = Depends(require_manager)) -> None:
    try:
        storage.delete_data_scientist(db, ds_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# Projects ------------------------------------------------------------------ #

@app.get("/projects", response_model=List[Project])
def list_projects(db: Session = Depends(get_db)) -> List[Project]:
    return storage.list_projects(db)


@app.post("/projects", response_model=Project, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), _: UserORM = Depends(require_manager)) -> Project:
    return storage.create_project(db, payload)


@app.put("/projects/{project_id}", response_model=Project)
def update_project(project_id: int, payload: ProjectCreate, db: Session = Depends(get_db), _: UserORM = Depends(require_manager)) -> Project:
    try:
        return storage.update_project(db, project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/projects/{project_id}", status_code=204, response_model=None)
def delete_project(project_id: int, db: Session = Depends(get_db), _: UserORM = Depends(require_manager)) -> None:
    try:
        storage.delete_project(db, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# Assignments --------------------------------------------------------------- #

@app.get("/assignments", response_model=List[Assignment])
def list_assignments(db: Session = Depends(get_db)) -> List[Assignment]:
    return storage.list_assignments(db)


@app.post("/assignments", response_model=Assignment, status_code=201)
def create_assignment(payload: AssignmentCreate, db: Session = Depends(get_db), current_user: Optional[UserORM] = Depends(get_user_or_none)) -> Assignment:
    try:
        changed_by = current_user.username if current_user else "anonymous"
        return storage.add_assignment(db, payload, changed_by=changed_by)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/assignments/{assignment_id}", status_code=204, response_model=None)
def delete_assignment(assignment_id: int, db: Session = Depends(get_db), current_user: Optional[UserORM] = Depends(get_user_or_none)) -> None:
    try:
        changed_by = current_user.username if current_user else "anonymous"
        storage.delete_assignment(db, assignment_id, changed_by=changed_by)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.put("/assignments", response_model=List[Assignment])
def replace_assignments(payload: AssignmentsPayload, db: Session = Depends(get_db), _: UserORM = Depends(require_manager)) -> List[Assignment]:
    try:
        return storage.replace_assignments(db, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/assignments/bulk", response_model=List[Assignment], status_code=201)
def bulk_assign(payload: BulkAssignPayload, db: Session = Depends(get_db), _: UserORM = Depends(require_manager)) -> List[Assignment]:
    """Assign a DS to a project for every week in a date range."""
    try:
        from datetime import timedelta
        results = []
        current = payload.start_date
        while current <= payload.end_date:
            a = storage.add_assignment(db, AssignmentCreate(
                data_scientist_id=payload.data_scientist_id,
                project_id=payload.project_id,
                week_start=current,
                allocation=payload.allocation,
            ))
            results.append(a)
            current += timedelta(weeks=1)
        return results
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# Capacity conflicts --------------------------------------------------------- #

@app.get("/conflicts", response_model=List[ConflictItem])
def get_conflicts(db: Session = Depends(get_db)) -> List[ConflictItem]:
    return storage.get_conflicts(db)


# Skills -------------------------------------------------------------------- #

@app.get("/skills", response_model=List[str])
def list_skills(db: Session = Depends(get_db)) -> List[str]:
    return storage.list_skills(db)


@app.get("/projects/{project_id}/suggest-ds", response_model=List[DataScientist])
def suggest_ds(project_id: int, db: Session = Depends(get_db)) -> List[DataScientist]:
    try:
        return storage.get_skill_suggestions(db, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# Audit log ----------------------------------------------------------------- #

@app.get("/audit-logs", response_model=List[AuditLogItem])
def list_audit_logs(limit: int = 100, db: Session = Depends(get_db)) -> List[AuditLogItem]:
    return storage.list_audit_logs(db, limit=limit)


# Import/export ------------------------------------------------------------- #

@app.get("/export/csv")
def export_schedule(db: Session = Depends(get_db)) -> StreamingResponse:
    csv_content = storage.export_assignments(db)
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="schedule.csv"'},
    )


@app.post("/agent/chat", response_model=AgentResponse)
def agent_chat(request: AgentRequest, db: Session = Depends(get_db)) -> AgentResponse:
    return run_agent(request, db)


@app.post("/import/schedule", response_model=ImportResult)
async def import_schedule(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportResult:
    try:
        suffix = Path(file.filename or "schedule.xlsx").suffix.lower()
        if suffix not in (".csv", ".xlsx", ".xls"):
            raise ValueError(f"Unsupported file type: {suffix}")
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            contents = await file.read()
            tmp.write(contents)
            tmp_path = Path(tmp.name)
        result = storage.import_from_file(db, tmp_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if "tmp_path" in locals() and tmp_path.exists():
            tmp_path.unlink()
    return result
