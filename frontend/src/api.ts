import {
  Assignment,
  AssignmentPayload,
  Config,
  Config as ConfigResponse,
  DataScientist,
  DataScientistPayload,
  ImportResult,
  Project,
  ProjectPayload,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch (err) {
      // ignore parse failure
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    // No content
    return undefined as unknown as T;
  }
  const contentType = response.headers.get("Content-Type") || "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.text()) as unknown as T;
}

export const api = {
  getConfig: (): Promise<ConfigResponse> => request("/config"),
  updateConfig: (payload: Partial<Config>): Promise<Config> =>
    request("/config", { method: "PUT", body: JSON.stringify(payload) }),

  listDataScientists: (): Promise<DataScientist[]> => request("/data-scientists"),
  createDataScientist: (payload: DataScientistPayload): Promise<DataScientist> =>
    request("/data-scientists", { method: "POST", body: JSON.stringify(payload) }),
  updateDataScientist: (id: number, payload: DataScientistPayload): Promise<DataScientist> =>
    request(`/data-scientists/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteDataScientist: (id: number): Promise<void> =>
    request(`/data-scientists/${id}`, { method: "DELETE" }),

  listProjects: (): Promise<Project[]> => request("/projects"),
  createProject: (payload: ProjectPayload): Promise<Project> =>
    request("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (id: number, payload: ProjectPayload): Promise<Project> =>
    request(`/projects/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteProject: (id: number): Promise<void> => request(`/projects/${id}`, { method: "DELETE" }),

  listAssignments: (): Promise<Assignment[]> => request("/assignments"),
  replaceAssignments: (payload: AssignmentPayload[]): Promise<Assignment[]> =>
    request("/assignments", {
      method: "PUT",
      body: JSON.stringify({ assignments: payload }),
    }),

  exportSchedule: async (): Promise<Blob> => {
    const response = await fetch(`${API_BASE}/export/csv`);
    const blob = await response.blob();
    return blob;
  },

  importSchedule: async (file: File): Promise<ImportResult> => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_BASE}/import/schedule`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const message = await response.text();
      throw new Error(message || "Failed to import");
    }
    return (await response.json()) as ImportResult;
  },
};

