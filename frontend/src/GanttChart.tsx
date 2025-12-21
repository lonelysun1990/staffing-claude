import { useMemo } from "react";
import { Assignment, DataScientist, Project } from "./types";

// Color palette for bars - vibrant, distinct colors
const COLORS = [
  "#6366f1", // indigo
  "#ec4899", // pink
  "#14b8a6", // teal
  "#f59e0b", // amber
  "#8b5cf6", // violet
  "#06b6d4", // cyan
  "#f97316", // orange
  "#84cc16", // lime
  "#ef4444", // red
  "#3b82f6", // blue
  "#a855f7", // purple
  "#10b981", // emerald
  "#eab308", // yellow
  "#0ea5e9", // sky
  "#d946ef", // fuchsia
  "#22c55e", // green
];

/**
 * Generate an acronym from a project name.
 * - Takes first letter of each word
 * - Keeps numbers
 * - Limits to 4 characters for readability
 */
function generateAcronym(name: string): string {
  const words = name.split(/[\s\-_+]+/).filter(Boolean);
  
  if (words.length === 1) {
    // Single word: take first 3-4 chars
    return name.slice(0, 4).toUpperCase();
  }
  
  // Multiple words: take first letter of each word, keep numbers
  const acronym = words
    .map((word) => {
      // If word is a number or short code, keep it
      if (/^\d+$/.test(word) || word.length <= 3) {
        return word.toUpperCase();
      }
      return word[0].toUpperCase();
    })
    .join("");
  
  // Limit length
  return acronym.slice(0, 5);
}

interface GanttChartProps {
  weeks: string[];
  assignments: Assignment[];
  dataScientists: DataScientist[];
  projects: Project[];
  mode: "by-person" | "by-project";
}

interface GanttBar {
  id: string;
  label: string;
  acronym: string;
  allocation: number;
  color: string;
  weekIndex: number;
}

interface GanttRow {
  id: number;
  name: string;
  bars: Map<number, GanttBar[]>; // weekIndex -> bars for that week
}

export function GanttChart({
  weeks,
  assignments,
  dataScientists,
  projects,
  mode,
}: GanttChartProps) {
  const dsLookup = useMemo(
    () => Object.fromEntries(dataScientists.map((ds) => [ds.id, ds])),
    [dataScientists]
  );

  const projectLookup = useMemo(
    () => Object.fromEntries(projects.map((p) => [p.id, p])),
    [projects]
  );

  const weekIndexMap = useMemo(
    () => Object.fromEntries(weeks.map((w, i) => [w, i])),
    [weeks]
  );

  // Generate color maps and acronyms
  const projectData = useMemo(
    () =>
      Object.fromEntries(
        projects.map((p, i) => [
          p.id,
          {
            color: COLORS[i % COLORS.length],
            acronym: generateAcronym(p.name),
            name: p.name,
          },
        ])
      ),
    [projects]
  );

  const dsColors = useMemo(
    () => Object.fromEntries(dataScientists.map((ds, i) => [ds.id, COLORS[i % COLORS.length]])),
    [dataScientists]
  );

  const rows = useMemo((): GanttRow[] => {
    if (mode === "by-person") {
      // Group assignments by data scientist
      return dataScientists.map((ds) => {
        const dsAssignments = assignments.filter((a) => a.data_scientist_id === ds.id);
        const bars = new Map<number, GanttBar[]>();

        dsAssignments.forEach((a) => {
          const weekIndex = weekIndexMap[a.week_start];
          if (weekIndex === undefined) return;

          const project = projectLookup[a.project_id];
          const pData = projectData[a.project_id];
          const bar: GanttBar = {
            id: `${a.id}`,
            label: project?.name ?? `Project ${a.project_id}`,
            acronym: pData?.acronym ?? "?",
            allocation: a.allocation,
            color: pData?.color ?? COLORS[0],
            weekIndex,
          };

          if (!bars.has(weekIndex)) {
            bars.set(weekIndex, []);
          }
          bars.get(weekIndex)!.push(bar);
        });

        return { id: ds.id, name: ds.name, bars };
      });
    } else {
      // Group assignments by project
      return projects.map((project) => {
        const projectAssignments = assignments.filter((a) => a.project_id === project.id);
        const bars = new Map<number, GanttBar[]>();

        projectAssignments.forEach((a) => {
          const weekIndex = weekIndexMap[a.week_start];
          if (weekIndex === undefined) return;

          const ds = dsLookup[a.data_scientist_id];
          const bar: GanttBar = {
            id: `${a.id}`,
            label: ds ? `${ds.name} (${(a.allocation * 100).toFixed(0)}%)` : `DS ${a.data_scientist_id}`,
            acronym: ds?.name.split(" ").map(n => n[0]).join("") ?? "?",
            allocation: a.allocation,
            color: dsColors[a.data_scientist_id] ?? COLORS[0],
            weekIndex,
          };

          if (!bars.has(weekIndex)) {
            bars.set(weekIndex, []);
          }
          bars.get(weekIndex)!.push(bar);
        });

        return { id: project.id, name: project.name, bars };
      });
    }
  }, [
    mode,
    dataScientists,
    projects,
    assignments,
    weekIndexMap,
    projectLookup,
    dsLookup,
    projectData,
    dsColors,
  ]);

  // Format week label (show month/day)
  const formatWeek = (week: string) => {
    const date = new Date(week + "T00:00:00");
    return `${date.getMonth() + 1}/${date.getDate()}`;
  };

  // Show only a subset of weeks for better readability
  const visibleWeeks = weeks.slice(0, Math.min(weeks.length, 16));

  if (rows.length === 0) {
    return (
      <div className="gantt-empty">
        No {mode === "by-person" ? "data scientists" : "projects"} to display.
      </div>
    );
  }

  return (
    <div className="gantt-container">
      <div className="gantt-chart">
        {/* Header row with week labels */}
        <div className="gantt-header">
          <div className="gantt-label-cell">
            {mode === "by-person" ? "Data Scientist" : "Project"}
          </div>
          {visibleWeeks.map((week, i) => (
            <div key={week} className="gantt-week-header">
              <span className="gantt-week-label">{formatWeek(week)}</span>
              {i === 0 && <span className="gantt-week-year">{week.slice(0, 4)}</span>}
            </div>
          ))}
        </div>

        {/* Data rows */}
        {rows.map((row) => (
          <div key={row.id} className="gantt-row">
            <div className="gantt-label-cell" title={row.name}>
              {row.name}
            </div>
            {visibleWeeks.map((week, weekIndex) => {
              const cellBars = row.bars.get(weekIndex) ?? [];
              return (
                <div key={week} className="gantt-cell">
                  {cellBars.length > 0 && (
                    <div className="gantt-bars">
                      {cellBars.map((bar) => (
                        <div
                          key={bar.id}
                          className="gantt-bar"
                          style={{
                            backgroundColor: bar.color,
                            height: mode === "by-person" 
                              ? `${Math.max(bar.allocation * 100, 20)}%`
                              : `${Math.max(100 / cellBars.length, 20)}%`,
                          }}
                          title={`${bar.label}: ${(bar.allocation * 100).toFixed(0)}%`}
                        >
                          <span className="gantt-bar-text">
                            {mode === "by-person" 
                              ? `${bar.acronym} ${(bar.allocation * 100).toFixed(0)}%`
                              : bar.label.split(" (")[0]}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {/* Legend */}
      <div className="gantt-legend">
        <span className="gantt-legend-title">
          {mode === "by-person" ? "Project Acronyms:" : "Legend:"}
        </span>
        {mode === "by-person"
          ? projects.slice(0, 10).map((p) => {
              const pData = projectData[p.id];
              return (
                <div key={p.id} className="gantt-legend-item">
                  <span
                    className="gantt-legend-color"
                    style={{ backgroundColor: pData?.color }}
                  />
                  <span className="gantt-legend-label">
                    <strong>{pData?.acronym}</strong> = {p.name}
                  </span>
                </div>
              );
            })
          : dataScientists.slice(0, 8).map((ds) => (
              <div key={ds.id} className="gantt-legend-item">
                <span
                  className="gantt-legend-color"
                  style={{ backgroundColor: dsColors[ds.id] }}
                />
                <span className="gantt-legend-label">{ds.name}</span>
              </div>
            ))}
        {(mode === "by-person" ? projects.length > 10 : dataScientists.length > 8) && (
          <span className="gantt-legend-more">
            +{(mode === "by-person" ? projects.length - 10 : dataScientists.length - 8)} more
          </span>
        )}
      </div>
    </div>
  );
}

