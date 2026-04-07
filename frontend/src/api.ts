import {
  Assignment,
  AssignmentPayload,
  AuditLogItem,
  BulkAssignPayload,
  BulkRemovePayload,
  Config,
  ConflictItem,
  DataScientist,
  DataScientistPayload,
  ImportResult,
  Project,
  ProjectPayload,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem("auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...getAuthHeaders(), ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem("auth_token");
      window.dispatchEvent(new Event("auth:unauthorized"));
    }
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {}
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as unknown as T;
  const ct = response.headers.get("Content-Type") || "";
  if (ct.includes("application/json")) return (await response.json()) as T;
  return (await response.text()) as unknown as T;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AgentResponse {
  reply: string;
  data_changed: boolean;
}

export const api = {
  // Auth
  login: async (username: string, password: string): Promise<{ access_token: string; token_type: string }> => {
    const formData = new URLSearchParams();
    formData.append("username", username);
    formData.append("password", password);
    const response = await fetch(`${API_BASE}/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: formData.toString(),
    });
    if (!response.ok) throw new Error("Invalid credentials");
    return response.json();
  },
  register: (payload: { username: string; password: string; role: string }): Promise<{ id: number; username: string; role: string }> =>
    request("/auth/register", { method: "POST", body: JSON.stringify(payload) }),
  me: (token: string): Promise<{ id: number; username: string; role: string }> =>
    request("/auth/me", { headers: { Authorization: `Bearer ${token}` } }),

  // Config
  getConfig: (): Promise<Config> => request("/config"),
  updateConfig: (payload: Partial<Config>): Promise<Config> =>
    request("/config", { method: "PUT", body: JSON.stringify(payload) }),

  // Data scientists
  listDataScientists: (): Promise<DataScientist[]> => request("/data-scientists"),
  createDataScientist: (payload: DataScientistPayload): Promise<DataScientist> =>
    request("/data-scientists", { method: "POST", body: JSON.stringify(payload) }),
  updateDataScientist: (id: number, payload: DataScientistPayload): Promise<DataScientist> =>
    request(`/data-scientists/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteDataScientist: (id: number): Promise<void> =>
    request(`/data-scientists/${id}`, { method: "DELETE" }),

  // Projects
  listProjects: (): Promise<Project[]> => request("/projects"),
  createProject: (payload: ProjectPayload): Promise<Project> =>
    request("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (id: number, payload: ProjectPayload): Promise<Project> =>
    request(`/projects/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteProject: (id: number): Promise<void> => request(`/projects/${id}`, { method: "DELETE" }),
  suggestDs: (projectId: number): Promise<DataScientist[]> =>
    request(`/projects/${projectId}/suggest-ds`),

  // Assignments
  listAssignments: (): Promise<Assignment[]> => request("/assignments"),
  createAssignment: (payload: AssignmentPayload): Promise<Assignment> =>
    request("/assignments", { method: "POST", body: JSON.stringify(payload) }),
  deleteAssignment: (id: number): Promise<void> =>
    request(`/assignments/${id}`, { method: "DELETE" }),
  replaceAssignments: (payload: AssignmentPayload[]): Promise<Assignment[]> =>
    request("/assignments", { method: "PUT", body: JSON.stringify({ assignments: payload }) }),
  bulkAssign: (payload: BulkAssignPayload): Promise<Assignment[]> =>
    request("/assignments/bulk", { method: "POST", body: JSON.stringify(payload) }),
  bulkRemove: (payload: BulkRemovePayload): Promise<{ removed: number }> =>
    request("/assignments/bulk", { method: "DELETE", body: JSON.stringify(payload) }),

  // Conflicts
  getConflicts: (): Promise<ConflictItem[]> => request("/conflicts"),

  // Skills
  listSkills: (): Promise<string[]> => request("/skills"),

  // Audit log
  listAuditLogs: (limit = 100): Promise<AuditLogItem[]> =>
    request(`/audit-logs?limit=${limit}`),

  // Import/export
  exportSchedule: async (): Promise<Blob> => {
    const response = await fetch(`${API_BASE}/export/csv`, {
      headers: getAuthHeaders(),
    });
    return response.blob();
  },

  sendAgentMessage: (messages: ChatMessage[]): Promise<AgentResponse> =>
    request("/agent/chat", {
      method: "POST",
      body: JSON.stringify({ messages }),
    }),


  importSchedule: async (file: File): Promise<ImportResult> => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_BASE}/import/schedule`, {
      method: "POST",
      body: formData,
      headers: getAuthHeaders(),
    });
    if (!response.ok) throw new Error(await response.text() || "Failed to import");
    return response.json() as Promise<ImportResult>;
  },
};
