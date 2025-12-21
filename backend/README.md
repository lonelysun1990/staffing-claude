# Staffing scheduler backend

This FastAPI service powers the staffing scheduler. It stores a JSON-backed schedule with configurable granularity/horizon defaults (1 week, 6 months).

## Running locally

```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Useful endpoints

- `GET /health` – quick readiness check  
- `GET /config` / `PUT /config` – update scheduling defaults  
- `GET|POST|PUT|DELETE /data-scientists` – CRUD data scientist roster  
- `GET|POST|PUT|DELETE /projects` – CRUD project catalog  
- `GET|PUT /assignments` – read or replace weekly allocations  
- `POST /import/excel` – upload an Excel file with `week_start`, `data_scientist`, `project`, `allocation` columns  
- `GET /export/csv` – download the current assignment grid as CSV

