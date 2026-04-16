---
name: staffing-analytics-charts
description: >-
  Plans staffing analyses and builds Python chart tools via create_dynamic_tool.
  Use when the user asks for plots, trends, heatmaps, gaps, utilization, or
  week-over-week staffing visuals; or when store_artifact / run_dynamic_tool
  appear in the workflow.
---

# Staffing analytics and charts

## When this applies

Use this playbook for **quantitative or visual** answers (charts, tables derived in code, custom metrics), not for simple one-line roster edits.

## Plan first (short)

Before tools: state in 3–6 bullets — goal, **metric definition**, **data grain** (person / project / team / week), which **context sections** or **MCP tools** supply that grain, and what you will **not** infer from coarser data.

## Data grain

- Entity-level questions → roster, projects, assignments in context plus scheduling tools (`get_availability`, `check_conflicts`, assignment-related tools as exposed).
- Team-level utilization over time → aggregate helpers only if the question is explicitly team-wide.
- Do not treat team-level series as per-project demand or gap without project-level inputs.

## Dynamic Python tools

1. Prefer **small JSON** into `store_artifact` when the payload is large; pass `artifact_id` into `run_dynamic_tool` when useful.
2. `create_dynamic_tool`: code must define `run(**kwargs)`; plots return `{"type": "png_base64", "data": "<base64>"}`.
3. After create or requirement change: **one** `check_dynamic_tool_status(name, max_wait_seconds=120)` **or** call `run_dynamic_tool` (venv wait is built in). Avoid tight polling.
4. On failure: `update_dynamic_tool`, then re-run.

## Output

After a successful plot, summarize what the chart shows and any caveats (definitions, missing data). Keep prose proportional to task complexity.
