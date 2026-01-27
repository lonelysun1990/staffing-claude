# Staffing scheduler

This repository delivers a lightweight staffing planner with:

- **React** front end (Vite + TypeScript) for editing data scientists, projects, and weekly assignments.
- **FastAPI** Python back end with JSON persistence and Excel/CSV import-export helpers.

## Getting started

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend expects `VITE_API_BASE_URL` (default `http://localhost:8000`) to reach the API.
This is only a draft.
