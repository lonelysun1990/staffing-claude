import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { ChatPanel } from "./ChatPanel";
import { GanttChart } from "./GanttChart";
import {
  Assignment,
  AssignmentPayload,
  Config,
  DataScientist,
  DataScientistPayload,
  ImportResult,
  Project,
  ProjectPayload,
} from "./types";
import "./App.css";

type TabKey = "schedule" | "dataScientists" | "projects" | "settings" | "importExport";

const TAB_LABELS: Record<TabKey, string> = {
  schedule: "Schedule",
  dataScientists: "Data Scientists",
  projects: "Projects",
  settings: "Settings",
  importExport: "Import / Export",
};

const startOfWeek = (input: Date) => {
  const copy = new Date(input);
  const day = copy.getDay();
  const diff = copy.getDate() - day + (day === 0 ? -6 : 1);
  copy.setDate(diff);
  copy.setHours(0, 0, 0, 0);
  return copy;
};

const toISODate = (date: Date) => date.toISOString().split("T")[0];

function App() {
  const [tab, setTab] = useState<TabKey>("schedule");
  const [config, setConfig] = useState<Config>({ granularity_weeks: 1, horizon_weeks: 26 });
  const [dataScientists, setDataScientists] = useState<DataScientist[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const [dsForm, setDsForm] = useState<DataScientistPayload>({
    name: "",
    level: "Junior DS",
    max_concurrent_projects: 1,
    efficiency: 1,
    notes: "",
  });
  const [editingDsId, setEditingDsId] = useState<number | null>(null);

  const [projectForm, setProjectForm] = useState({
    name: "",
    start_date: toISODate(startOfWeek(new Date())),
    duration_weeks: 12,
    weeklyFte: 1,
  });
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null);

  const [newAssignment, setNewAssignment] = useState<AssignmentPayload>({
    data_scientist_id: 0,
    project_id: 0,
    week_start: toISODate(startOfWeek(new Date())),
    allocation: 0.25,
  });

  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  const weeks = useMemo(() => {
    const slots: string[] = [];
    const start = startOfWeek(new Date());
    for (let i = 0; i < config.horizon_weeks; i += config.granularity_weeks) {
      const week = new Date(start);
      week.setDate(start.getDate() + i * 7);
      slots.push(toISODate(week));
    }
    return slots;
  }, [config]);

  const loadData = async () => {
    try {
      setLoading(true);
      const [configResponse, dsList, projectList, assignmentList] = await Promise.all([
        api.getConfig(),
        api.listDataScientists(),
        api.listProjects(),
        api.listAssignments(),
      ]);
      setConfig(configResponse);
      setDataScientists(dsList);
      setProjects(projectList);
      setAssignments(assignmentList);
      setNewAssignment((prev) => ({
        ...prev,
        data_scientist_id: dsList[0]?.id ?? 0,
        project_id: projectList[0]?.id ?? 0,
        week_start: weeks[0] ?? prev.week_start,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSaveDataScientist = async () => {
    try {
      if (!dsForm.name.trim()) {
        throw new Error("Name is required");
      }
      if (editingDsId) {
        const updated = await api.updateDataScientist(editingDsId, dsForm);
        setDataScientists((prev) => prev.map((ds) => (ds.id === updated.id ? updated : ds)));
        setStatus(`Updated ${updated.name}`);
      } else {
        const created = await api.createDataScientist(dsForm);
        setDataScientists((prev) => [...prev, created]);
        setStatus(`Added ${created.name}`);
      }
      setDsForm({
        name: "",
        level: "Junior DS",
        max_concurrent_projects: 1,
        efficiency: 1,
        notes: "",
      });
      setEditingDsId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save data scientist");
    }
  };

  const handleDeleteDataScientist = async (id: number) => {
    try {
      await api.deleteDataScientist(id);
      setDataScientists((prev) => prev.filter((ds) => ds.id !== id));
      setAssignments((prev) => prev.filter((a) => a.data_scientist_id !== id));
      setStatus("Removed data scientist");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete");
    }
  };

  const buildProjectPayload = (): ProjectPayload => {
    const start = new Date(projectForm.start_date);
    const end = new Date(start);
    end.setDate(start.getDate() + (projectForm.duration_weeks - 1) * 7);
    const fte_requirements = Array.from({ length: projectForm.duration_weeks }).map((_, idx) => {
      const week = new Date(start);
      week.setDate(start.getDate() + idx * 7);
      return { week_start: toISODate(week), fte: Number(projectForm.weeklyFte) };
    });
    return {
      name: projectForm.name,
      start_date: toISODate(start),
      end_date: toISODate(end),
      fte_requirements,
    };
  };

  const handleSaveProject = async () => {
    try {
      if (!projectForm.name.trim()) {
        throw new Error("Project name is required");
      }
      const payload = buildProjectPayload();
      if (editingProjectId) {
        const updated = await api.updateProject(editingProjectId, payload);
        setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
        setStatus(`Updated project ${updated.name}`);
      } else {
        const created = await api.createProject(payload);
        setProjects((prev) => [...prev, created]);
        setStatus(`Added project ${created.name}`);
      }
      setProjectForm({
        name: "",
        start_date: toISODate(startOfWeek(new Date())),
        duration_weeks: 12,
        weeklyFte: 1,
      });
      setEditingProjectId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save project");
    }
  };

  const handleDeleteProject = async (id: number) => {
    try {
      await api.deleteProject(id);
      setProjects((prev) => prev.filter((p) => p.id !== id));
      setAssignments((prev) => prev.filter((a) => a.project_id !== id));
      setStatus("Removed project");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete project");
    }
  };

  const handleAddAssignment = () => {
    if (!newAssignment.data_scientist_id || !newAssignment.project_id) {
      setError("Select a data scientist and project first");
      return;
    }
    const newRow: Assignment = {
      id: Date.now(),
      ...newAssignment,
    };
    setAssignments((prev) => [...prev, newRow]);
    setStatus("Draft assignment added");
  };

  const handleSaveAssignments = async () => {
    try {
      const payload: AssignmentPayload[] = assignments.map(
        ({ data_scientist_id, project_id, week_start, allocation }) => ({
          data_scientist_id,
          project_id,
          week_start,
          allocation,
        })
      );
      const saved = await api.replaceAssignments(payload);
      setAssignments(saved);
      setStatus("Assignments saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save assignments");
    }
  };

  const handleImport = async (file?: File | null) => {
    if (!file) return;
    try {
      const result = await api.importSchedule(file);
      setImportResult(result);
      await loadData();
      setStatus("Imported schedule from Excel");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to import file");
    }
  };

  const handleExport = async () => {
    try {
      const blob = await api.exportSchedule();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "schedule.csv";
      link.click();
      URL.revokeObjectURL(url);
      setStatus("Exported schedule");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to export schedule");
    }
  };

  const handleConfigUpdate = async (updates: Partial<Config>) => {
    try {
      const updated = await api.updateConfig(updates);
      setConfig(updated);
      setStatus("Updated scheduling defaults");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update config");
    }
  };

  const projectLookup = useMemo(
    () => Object.fromEntries(projects.map((project) => [project.id, project])),
    [projects]
  );
  const dsLookup = useMemo(
    () => Object.fromEntries(dataScientists.map((ds) => [ds.id, ds])),
    [dataScientists]
  );

  const weeklySummary = useMemo(() => {
    const summary: Record<string, number> = {};
    assignments.forEach((assignment) => {
      summary[assignment.week_start] = (summary[assignment.week_start] || 0) + assignment.allocation;
    });
    return summary;
  }, [assignments]);

  const resetMessages = () => {
    setError(null);
    setStatus(null);
  };

  return (
    <div className="app">
      <header className="app__header">
        <div>
          <p className="eyebrow">Staffing Scheduler</p>
          <h1>Plan and balance your data science team</h1>
          <p className="subtitle">
            Configure staffing capacity, track FTE demand per project, and allocate people week by
            week.
          </p>
        </div>
        <div className="tag">Default: {config.granularity_weeks} week slots • {config.horizon_weeks} week horizon</div>
      </header>

      <nav className="tabs">
        {Object.entries(TAB_LABELS).map(([key, label]) => (
          <button
            key={key}
            className={`tab ${tab === key ? "active" : ""}`}
            onClick={() => {
              resetMessages();
              setTab(key as TabKey);
            }}
          >
            {label}
          </button>
        ))}
      </nav>

      {(loading || error || status) && (
        <div className="alerts">
          {loading && <div className="alert info">Loading scheduler data...</div>}
          {status && <div className="alert success">{status}</div>}
          {error && <div className="alert danger">{error}</div>}
        </div>
      )}

      <main className="panels">
        {tab === "schedule" && (
          <section className="panel">
            <header className="panel__header">
              <div>
                <p className="eyebrow">Weekly assignments</p>
                <h2>Balance workload across projects</h2>
              </div>
              <button className="primary" onClick={handleSaveAssignments}>
                Save assignments
              </button>
            </header>
            <div className="grid stats">
              <div className="stat">
                <p className="eyebrow">People</p>
                <strong>{dataScientists.length}</strong>
                <span>Data scientists available</span>
              </div>
              <div className="stat">
                <p className="eyebrow">Projects</p>
                <strong>{projects.length}</strong>
                <span>Active initiatives</span>
              </div>
              <div className="stat">
                <p className="eyebrow">This week</p>
                <strong>{(weeklySummary[weeks[0]] ?? 0).toFixed(2)}</strong>
                <span>FTE allocated</span>
              </div>
            </div>

            <div className="card">
              <div className="card__header">
                <div>
                  <p className="eyebrow">Add assignment</p>
                  <h3>Create a weekly allocation</h3>
                </div>
                <button className="secondary" onClick={handleAddAssignment}>
                  Add to draft
                </button>
              </div>
              <div className="form-grid">
                <label>
                  Data scientist
                  <select
                    value={newAssignment.data_scientist_id}
                    onChange={(e) =>
                      setNewAssignment((prev) => ({
                        ...prev,
                        data_scientist_id: Number(e.target.value),
                      }))
                    }
                  >
                    {dataScientists.map((ds) => (
                      <option key={ds.id} value={ds.id}>
                        {ds.name} ({ds.level})
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Project
                  <select
                    value={newAssignment.project_id}
                    onChange={(e) =>
                      setNewAssignment((prev) => ({
                        ...prev,
                        project_id: Number(e.target.value),
                      }))
                    }
                  >
                    {projects.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Week start
                  <select
                    value={newAssignment.week_start}
                    onChange={(e) =>
                      setNewAssignment((prev) => ({ ...prev, week_start: e.target.value }))
                    }
                  >
                    {weeks.map((week) => (
                      <option key={week} value={week}>
                        {week}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Allocation (% of week)
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={newAssignment.allocation}
                    onChange={(e) =>
                      setNewAssignment((prev) => ({
                        ...prev,
                        allocation: Number(e.target.value),
                      }))
                    }
                  />
                </label>
              </div>
            </div>

            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Week</th>
                    <th>Data scientist</th>
                    <th>Project</th>
                    <th>Allocation</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {assignments.map((assignment) => (
                    <tr key={assignment.id}>
                      <td>{assignment.week_start}</td>
                      <td>{dsLookup[assignment.data_scientist_id]?.name || assignment.data_scientist_id}</td>
                      <td>{projectLookup[assignment.project_id]?.name || assignment.project_id}</td>
                      <td>
                        <input
                          type="number"
                          min={0}
                          max={1}
                          step={0.05}
                          value={assignment.allocation}
                          onChange={(e) => {
                            const value = Number(e.target.value);
                            setAssignments((prev) =>
                              prev.map((row) =>
                                row.id === assignment.id ? { ...row, allocation: value } : row
                              )
                            );
                          }}
                        />
                      </td>
                      <td>
                        <button
                          className="ghost"
                          onClick={() =>
                            setAssignments((prev) => prev.filter((row) => row.id !== assignment.id))
                          }
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                  {assignments.length === 0 && (
                    <tr>
                      <td colSpan={5} className="muted">
                        No assignments yet. Add one above.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {tab === "dataScientists" && (
          <section className="panel">
            <header className="panel__header">
              <div>
                <p className="eyebrow">Team roster</p>
                <h2>Manage data scientists</h2>
              </div>
              <button className="primary" onClick={handleSaveDataScientist}>
                {editingDsId ? "Update person" : "Add person"}
              </button>
            </header>

            <div className="card">
              <div className="card__header">
                <div>
                  <p className="eyebrow">Schedule overview</p>
                  <h3>Weekly assignments by person</h3>
                </div>
              </div>
              <GanttChart
                weeks={weeks}
                assignments={assignments}
                dataScientists={dataScientists}
                projects={projects}
                mode="by-person"
              />
            </div>

            <div className="form-grid">
              <label>
                Name
                <input
                  type="text"
                  value={dsForm.name}
                  onChange={(e) => setDsForm((prev) => ({ ...prev, name: e.target.value }))}
                />
              </label>
              <label>
                Level
                <input
                  type="text"
                  value={dsForm.level}
                  onChange={(e) => setDsForm((prev) => ({ ...prev, level: e.target.value }))}
                />
              </label>
              <label>
                Max concurrent projects
                <input
                  type="number"
                  min={1}
                  value={dsForm.max_concurrent_projects}
                  onChange={(e) =>
                    setDsForm((prev) => ({
                      ...prev,
                      max_concurrent_projects: Number(e.target.value),
                    }))
                  }
                />
              </label>
              <label>
                Efficiency (FTE)
                <input
                  type="number"
                  step={0.05}
                  min={0.1}
                  value={dsForm.efficiency}
                  onChange={(e) =>
                    setDsForm((prev) => ({ ...prev, efficiency: Number(e.target.value) }))
                  }
                />
              </label>
              <label className="full">
                Notes
                <input
                  type="text"
                  value={dsForm.notes ?? ""}
                  onChange={(e) => setDsForm((prev) => ({ ...prev, notes: e.target.value }))}
                />
              </label>
            </div>

            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Level</th>
                    <th>Concurrency</th>
                    <th>Efficiency</th>
                    <th>Notes</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {dataScientists.map((ds) => (
                    <tr key={ds.id}>
                      <td>{ds.name}</td>
                      <td>{ds.level}</td>
                      <td>{ds.max_concurrent_projects}</td>
                      <td>{ds.efficiency.toFixed(2)}</td>
                      <td className="muted">{ds.notes}</td>
                      <td className="actions">
                        <button
                          className="ghost"
                          onClick={() => {
                            setEditingDsId(ds.id);
                            setDsForm({
                              name: ds.name,
                              level: ds.level,
                              max_concurrent_projects: ds.max_concurrent_projects,
                              efficiency: ds.efficiency,
                              notes: ds.notes ?? "",
                            });
                          }}
                        >
                          Edit
                        </button>
                        <button className="ghost danger" onClick={() => handleDeleteDataScientist(ds.id)}>
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {tab === "projects" && (
          <section className="panel">
            <header className="panel__header">
              <div>
                <p className="eyebrow">Project catalog</p>
                <h2>Capture FTE needs</h2>
              </div>
              <button className="primary" onClick={handleSaveProject}>
                {editingProjectId ? "Update project" : "Add project"}
              </button>
            </header>

            <div className="card">
              <div className="card__header">
                <div>
                  <p className="eyebrow">Team allocation</p>
                  <h3>Who's working on each project</h3>
                </div>
              </div>
              <GanttChart
                weeks={weeks}
                assignments={assignments}
                dataScientists={dataScientists}
                projects={projects}
                mode="by-project"
              />
            </div>

            <div className="form-grid">
              <label>
                Name
                <input
                  type="text"
                  value={projectForm.name}
                  onChange={(e) => setProjectForm((prev) => ({ ...prev, name: e.target.value }))}
                />
              </label>
              <label>
                Start date
                <input
                  type="date"
                  value={projectForm.start_date}
                  onChange={(e) => setProjectForm((prev) => ({ ...prev, start_date: e.target.value }))}
                />
              </label>
              <label>
                Duration (weeks)
                <input
                  type="number"
                  min={1}
                  value={projectForm.duration_weeks}
                  onChange={(e) =>
                    setProjectForm((prev) => ({ ...prev, duration_weeks: Number(e.target.value) }))
                  }
                />
              </label>
              <label>
                Weekly FTE need
                <input
                  type="number"
                  min={0}
                  step={0.1}
                  value={projectForm.weeklyFte}
                  onChange={(e) => setProjectForm((prev) => ({ ...prev, weeklyFte: Number(e.target.value) }))}
                />
              </label>
            </div>

            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Project</th>
                    <th>Timeline</th>
                    <th>Weekly FTE</th>
                    <th>Duration</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map((project) => {
                    const duration =
                      (new Date(project.end_date).getTime() - new Date(project.start_date).getTime()) /
                        (1000 * 60 * 60 * 24 * 7) +
                      1;
                    const weeklyFte = project.fte_requirements[0]?.fte ?? 0;
                    return (
                      <tr key={project.id}>
                        <td>{project.name}</td>
                        <td>
                          {project.start_date} → {project.end_date}
                        </td>
                        <td>{weeklyFte}</td>
                        <td>{duration.toFixed(0)} weeks</td>
                        <td className="actions">
                          <button
                            className="ghost"
                            onClick={() => {
                              setEditingProjectId(project.id);
                              setProjectForm({
                                name: project.name,
                                start_date: project.start_date,
                                duration_weeks: Number(duration),
                                weeklyFte: weeklyFte,
                              });
                            }}
                          >
                            Edit
                          </button>
                          <button className="ghost danger" onClick={() => handleDeleteProject(project.id)}>
                            Delete
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {tab === "settings" && (
          <section className="panel">
            <header className="panel__header">
              <div>
                <p className="eyebrow">Scheduling defaults</p>
                <h2>Configure horizon and granularity</h2>
              </div>
            </header>
            <div className="form-grid">
              <label>
                Granularity (weeks per slot)
                <input
                  type="number"
                  min={1}
                  value={config.granularity_weeks}
                  onChange={(e) =>
                    handleConfigUpdate({ granularity_weeks: Number(e.target.value) || 1 })
                  }
                />
              </label>
              <label>
                Planning horizon (weeks)
                <input
                  type="number"
                  min={1}
                  value={config.horizon_weeks}
                  onChange={(e) =>
                    handleConfigUpdate({ horizon_weeks: Number(e.target.value) || 1 })
                  }
                />
              </label>
            </div>
          </section>
        )}

        {tab === "importExport" && (
          <section className="panel">
            <header className="panel__header">
              <div>
                <p className="eyebrow">Data exchange</p>
                <h2>Import or export schedules</h2>
              </div>
              <div className="actions">
                <button className="secondary" onClick={handleExport}>
                  Export CSV
                </button>
                <label className="file-button">
                  Import CSV/Excel
                  <input
                    type="file"
                    accept=".csv,.xlsx,.xls"
                    onChange={(e) => handleImport(e.target.files?.[0])}
                  />
                </label>
              </div>
            </header>
            <div className="card">
              <h3>Template</h3>
              <p className="muted">
                Include columns <code>week_start</code>, <code>data_scientist</code>,{" "}
                <code>project</code>, and <code>allocation</code>. Optional columns such as{" "}
                <code>level</code>, <code>max_concurrent_projects</code>, <code>efficiency</code>,
                <code>project_start</code>, <code>project_end</code>, and <code>fte</code> will be used when
                present.
              </p>
              {importResult && (
                <div className="import-result">
                  <div>
                    <p className="eyebrow">Import summary</p>
                    <ul>
                      <li>Assignments created: {importResult.created_assignments}</li>
                      <li>New data scientists: {importResult.created_data_scientists}</li>
                      <li>New projects: {importResult.created_projects}</li>
                      <li>Replaced assignments: {importResult.replaced_existing_assignments}</li>
                    </ul>
                  </div>
                </div>
              )}
            </div>
          </section>
        )}
      </main>

      <button className="chat-toggle" onClick={() => setChatOpen(true)} title="Open staffing assistant">
        💬
      </button>
      <ChatPanel
        isOpen={chatOpen}
        onClose={() => setChatOpen(false)}
        onDataChanged={loadData}
      />
    </div>
  );
}

export default App;

