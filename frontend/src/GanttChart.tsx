import { useMemo } from "react";
import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { Assignment, DataScientist, Project } from "./types";

const COLORS = [
  "#6366f1", "#ec4899", "#14b8a6", "#f59e0b", "#8b5cf6",
  "#06b6d4", "#f97316", "#84cc16", "#ef4444", "#3b82f6",
  "#a855f7", "#10b981", "#eab308", "#0ea5e9", "#d946ef", "#22c55e",
];

function generateAcronym(name: string): string {
  const words = name.split(/[\s\-_+]+/).filter(Boolean);
  if (words.length === 1) return name.slice(0, 4).toUpperCase();
  return words
    .map((word) => (/^\d+$/.test(word) || word.length <= 3 ? word.toUpperCase() : word[0].toUpperCase()))
    .join("")
    .slice(0, 5);
}

interface GanttBar {
  id: string;
  assignmentId: number;
  label: string;
  acronym: string;
  allocation: number;
  color: string;
}

interface GanttRow {
  id: number;
  name: string;
  bars: Map<number, GanttBar[]>;
}

interface GanttChartProps {
  weeks: string[];
  assignments: Assignment[];
  dataScientists: DataScientist[];
  projects: Project[];
  mode: "by-person" | "by-project";
  onMoveAssignment?: (assignmentId: number, newWeekStart: string) => void;
}

// Draggable bar
function DraggableBar({ bar, mode }: { bar: GanttBar; mode: "by-person" | "by-project" }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `bar-${bar.assignmentId}`,
    data: { assignmentId: bar.assignmentId },
  });
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className="gantt-bar"
      style={{
        backgroundColor: bar.color,
        opacity: isDragging ? 0.4 : 1,
        cursor: "grab",
      }}
      title={`${bar.label}: ${(bar.allocation * 100).toFixed(0)}% — drag to move`}
    >
      <span className="gantt-bar-text">
        {mode === "by-person"
          ? `${bar.acronym} ${(bar.allocation * 100).toFixed(0)}%`
          : bar.label.split(" (")[0]}
      </span>
    </div>
  );
}

// Droppable cell
function DroppableCell({
  id,
  children,
}: {
  id: string;
  children: React.ReactNode;
}) {
  const { isOver, setNodeRef } = useDroppable({ id });
  return (
    <div
      ref={setNodeRef}
      className={`gantt-cell${isOver ? " gantt-cell--over" : ""}`}
    >
      {children}
    </div>
  );
}

export function GanttChart({
  weeks,
  assignments,
  dataScientists,
  projects,
  mode,
  onMoveAssignment,
}: GanttChartProps) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

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
  const projectData = useMemo(
    () =>
      Object.fromEntries(
        projects.map((p, i) => [p.id, { color: COLORS[i % COLORS.length], acronym: generateAcronym(p.name), name: p.name }])
      ),
    [projects]
  );
  const dsColors = useMemo(
    () => Object.fromEntries(dataScientists.map((ds, i) => [ds.id, COLORS[i % COLORS.length]])),
    [dataScientists]
  );

  const visibleWeeks = weeks.slice(0, Math.min(weeks.length, 16));

  const rows = useMemo((): GanttRow[] => {
    if (mode === "by-person") {
      return dataScientists.map((ds) => {
        const bars = new Map<number, GanttBar[]>();
        assignments
          .filter((a) => a.data_scientist_id === ds.id)
          .forEach((a) => {
            const weekIndex = weekIndexMap[a.week_start];
            if (weekIndex === undefined) return;
            const pData = projectData[a.project_id];
            const bar: GanttBar = {
              id: `${a.id}`,
              assignmentId: a.id,
              label: projectLookup[a.project_id]?.name ?? `Project ${a.project_id}`,
              acronym: pData?.acronym ?? "?",
              allocation: a.allocation,
              color: pData?.color ?? COLORS[0],
            };
            if (!bars.has(weekIndex)) bars.set(weekIndex, []);
            bars.get(weekIndex)!.push(bar);
          });
        return { id: ds.id, name: ds.name, bars };
      });
    } else {
      return projects.map((project) => {
        const bars = new Map<number, GanttBar[]>();
        assignments
          .filter((a) => a.project_id === project.id)
          .forEach((a) => {
            const weekIndex = weekIndexMap[a.week_start];
            if (weekIndex === undefined) return;
            const ds = dsLookup[a.data_scientist_id];
            const bar: GanttBar = {
              id: `${a.id}`,
              assignmentId: a.id,
              label: ds ? `${ds.name} (${(a.allocation * 100).toFixed(0)}%)` : `DS ${a.data_scientist_id}`,
              acronym: ds?.name.split(" ").map((n) => n[0]).join("") ?? "?",
              allocation: a.allocation,
              color: dsColors[a.data_scientist_id] ?? COLORS[0],
            };
            if (!bars.has(weekIndex)) bars.set(weekIndex, []);
            bars.get(weekIndex)!.push(bar);
          });
        return { id: project.id, name: project.name, bars };
      });
    }
  }, [mode, dataScientists, projects, assignments, weekIndexMap, projectLookup, dsLookup, projectData, dsColors]);

  const formatWeek = (week: string) => {
    const d = new Date(week + "T00:00:00");
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };

  // Find a bar across all rows by assignmentId
  const findBar = (assignmentId: number): GanttBar | undefined => {
    for (const row of rows) {
      for (const bars of row.bars.values()) {
        const found = bars.find((b) => b.assignmentId === assignmentId);
        if (found) return found;
      }
    }
    return undefined;
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || !onMoveAssignment) return;

    // active.id = "bar-{assignmentId}", over.id = "cell-{rowId}-{weekIndex}"
    const assignmentId = Number(String(active.id).replace("bar-", ""));
    const weekIndex = Number(String(over.id).split("-").pop());
    const newWeekStart = visibleWeeks[weekIndex];
    if (newWeekStart) {
      onMoveAssignment(assignmentId, newWeekStart);
    }
  };

  if (rows.length === 0) {
    return (
      <div className="gantt-empty">
        No {mode === "by-person" ? "data scientists" : "projects"} to display.
      </div>
    );
  }

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <div className="gantt-container">
        <div className="gantt-chart">
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

          {rows.map((row) => (
            <div key={row.id} className="gantt-row">
              <div className="gantt-label-cell" title={row.name}>{row.name}</div>
              {visibleWeeks.map((week, weekIndex) => {
                const cellBars = row.bars.get(weekIndex) ?? [];
                return (
                  <DroppableCell key={week} id={`cell-${row.id}-${weekIndex}`}>
                    {cellBars.length > 0 && (
                      <div className="gantt-bars">
                        {cellBars.map((bar) => (
                          <DraggableBar key={bar.id} bar={bar} mode={mode} />
                        ))}
                      </div>
                    )}
                  </DroppableCell>
                );
              })}
            </div>
          ))}
        </div>

        <div className="gantt-legend">
          <span className="gantt-legend-title">
            {mode === "by-person" ? "Project Acronyms:" : "Legend:"}
            {onMoveAssignment && <span className="gantt-legend-hint"> · drag bars to move</span>}
          </span>
          {mode === "by-person"
            ? projects.slice(0, 10).map((p) => {
                const pData = projectData[p.id];
                return (
                  <div key={p.id} className="gantt-legend-item">
                    <span className="gantt-legend-color" style={{ backgroundColor: pData?.color }} />
                    <span className="gantt-legend-label"><strong>{pData?.acronym}</strong> = {p.name}</span>
                  </div>
                );
              })
            : dataScientists.slice(0, 8).map((ds) => (
                <div key={ds.id} className="gantt-legend-item">
                  <span className="gantt-legend-color" style={{ backgroundColor: dsColors[ds.id] }} />
                  <span className="gantt-legend-label">{ds.name}</span>
                </div>
              ))}
          {(mode === "by-person" ? projects.length > 10 : dataScientists.length > 8) && (
            <span className="gantt-legend-more">
              +{mode === "by-person" ? projects.length - 10 : dataScientists.length - 8} more
            </span>
          )}
        </div>
      </div>

      {/* Drag overlay (ghost preview) */}
      <DragOverlay>
        {/* No content needed — the draggable bar itself fades */}
      </DragOverlay>
    </DndContext>
  );
}
