from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse

from .models import (
    Assignment,
    AssignmentsPayload,
    ConfigModel,
    ConfigUpdate,
    DataScientist,
    DataScientistCreate,
    ImportResult,
    Project,
    ProjectCreate,
)
from .storage import get_store

app = FastAPI(title="Staffing Scheduler", version="0.1.0")
store = get_store()

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


@app.get("/config", response_model=ConfigModel)
def get_config() -> ConfigModel:
    return store.get_config()


@app.put("/config", response_model=ConfigModel)
def update_config(payload: ConfigUpdate) -> ConfigModel:
    return store.update_config(payload)


# Data scientists ------------------------------------------------------------ #
@app.get("/data-scientists", response_model=list[DataScientist])
def list_data_scientists() -> list[DataScientist]:
    return store.list_data_scientists()


@app.post("/data-scientists", response_model=DataScientist, status_code=201)
def create_data_scientist(payload: DataScientistCreate) -> DataScientist:
    return store.create_data_scientist(payload)


@app.put("/data-scientists/{ds_id}", response_model=DataScientist)
def update_data_scientist(ds_id: int, payload: DataScientistCreate) -> DataScientist:
    try:
        return store.update_data_scientist(ds_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/data-scientists/{ds_id}", status_code=204)
def delete_data_scientist(ds_id: int) -> None:
    try:
        store.delete_data_scientist(ds_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# Projects ------------------------------------------------------------------ #
@app.get("/projects", response_model=list[Project])
def list_projects() -> list[Project]:
    return store.list_projects()


@app.post("/projects", response_model=Project, status_code=201)
def create_project(payload: ProjectCreate) -> Project:
    return store.create_project(payload)


@app.put("/projects/{project_id}", response_model=Project)
def update_project(project_id: int, payload: ProjectCreate) -> Project:
    try:
        return store.update_project(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int) -> None:
    try:
        store.delete_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# Assignments --------------------------------------------------------------- #
@app.get("/assignments", response_model=list[Assignment])
def list_assignments() -> list[Assignment]:
    return store.list_assignments()


@app.put("/assignments", response_model=list[Assignment])
def replace_assignments(payload: AssignmentsPayload) -> list[Assignment]:
    try:
        return store.replace_assignments(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# Import/export ------------------------------------------------------------- #
@app.get("/export/csv")
def export_schedule() -> StreamingResponse:
    csv_content = store.export_assignments()
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="schedule.csv"'},
    )


@app.post("/import/excel", response_model=ImportResult)
async def import_schedule(file: UploadFile = File(...)) -> ImportResult:
    try:
        suffix = Path(file.filename or "schedule.xlsx").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            contents = await file.read()
            temp.write(contents)
            temp_path = Path(temp.name)
        result = store.import_from_excel(temp_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if "temp_path" in locals() and temp_path.exists():
            temp_path.unlink()
    return result
