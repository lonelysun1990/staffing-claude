export interface Config {
  granularity_weeks: number;
  horizon_weeks: number;
}

export interface DataScientist {
  id: number;
  name: string;
  level: string;
  max_concurrent_projects: number;
  efficiency: number;
  notes?: string | null;
}

export interface DataScientistPayload {
  name: string;
  level: string;
  max_concurrent_projects: number;
  efficiency: number;
  notes?: string | null;
}

export interface ProjectWeek {
  week_start: string;
  fte: number;
}

export interface Project {
  id: number;
  name: string;
  start_date: string;
  end_date: string;
  fte_requirements: ProjectWeek[];
}

export interface ProjectPayload {
  name: string;
  start_date: string;
  end_date: string;
  fte_requirements: ProjectWeek[];
}

export interface Assignment {
  id: number;
  data_scientist_id: number;
  project_id: number;
  week_start: string;
  allocation: number;
}

export interface AssignmentPayload {
  data_scientist_id: number;
  project_id: number;
  week_start: string;
  allocation: number;
}

export interface ImportResult {
  created_data_scientists: number;
  created_projects: number;
  created_assignments: number;
  replaced_existing_assignments: number;
}

