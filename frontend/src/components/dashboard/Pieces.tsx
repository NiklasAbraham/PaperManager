import { useState } from "react";
import type { DashboardData, DashProject, MapCluster, MapProject } from "./api";
import { READ_COLORS, fmt, projectColor, readingSegments, rgba, topicColor, weekTooltip } from "./helpers";


const Eyebrow = ({ children }: { children: React.ReactNode }) => (
  <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-3">{children}</p>
);

/** "12 this week · 85 this month" and 12 mini bars, one per week (hover shows the week). */
export function AddedStat({ dash, dense = false }: { dash: DashboardData; dense?: boolean }) {
  const [hot, setHot] = useState<number | null>(null);
  const weeks = dash.added_weekly;
  const max = Math.max(1, ...weeks.map((w) => w.count));
  return (
    <div className="min-w-0">
      <Eyebrow>Added</Eyebrow>
      <div className={`flex ${dense ? "items-end gap-3 mt-1" : "flex-col mt-0.5"}`}>
        <div className="shrink-0">
          <p className="flex items-baseline gap-1.5">
            <span className="text-2xl font-semibold text-ink tabular-nums leading-none">{fmt(dash.added_7d)}</span>
            <span className="text-xs text-ink-2">this week</span>
          </p>
          <p className="text-xs text-ink-3 mt-0.5 whitespace-nowrap">
            {hot != null && weeks[hot]
              ? <span className="text-accent">{weekTooltip(weeks[hot])}</span>
              : <>{fmt(dash.added_30d)} this month</>}
          </p>
        </div>
        <div className={`flex items-end gap-[3px] ${dense ? "flex-1 h-9 min-w-[72px]" : "h-8 mt-2"}`} onMouseLeave={() => setHot(null)} role="img"
          aria-label={`Papers added per week, last ${weeks.length} weeks`}>
          {weeks.map((w, i) => (
            <div key={w.week_start} title={weekTooltip(w)} onMouseEnter={() => setHot(i)}
              className="flex-1 h-full flex items-end cursor-default">
              <div className="w-full rounded-[3px] transition-colors"
                style={{ height: `${Math.max(w.count ? 12 : 5, (w.count / max) * 100)}%`,
                         background: i === hot ? "#6d28d9" : i === weeks.length - 1 ? "#7c3aed" : w.count ? "#c4b5fd" : "#ede9fe" }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Slim stacked bar unread / reading / read; every segment sets the reading_status filter. */
export function ReadingStat({ reading, onPick }: { reading: DashboardData["reading"]; onPick: (status: string) => void }) {
  const segs = readingSegments(reading);
  const label: Record<string, string> = { unread: "unread", reading: "reading", read: "read" };
  return (
    <div className="min-w-0">
      <Eyebrow>Reading</Eyebrow>
      <div className="flex gap-0.5 h-2.5 mt-2" role="group" aria-label="Reading progress">
        {segs.filter((s) => s.count > 0).map((s) => (
          <button key={s.key} type="button" onClick={() => onPick(s.key)}
            title={`${fmt(s.count)} ${label[s.key]}`} aria-label={`${fmt(s.count)} ${label[s.key]}: show these papers`}
            className="h-full rounded-full hover:brightness-95 hover:scale-y-125 transition-all"
            style={{ flexGrow: s.share, flexBasis: 0, minWidth: 7, background: READ_COLORS[s.key] }} />
        ))}
      </div>
      <p className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-ink-2">
        {segs.map((s) => (
          <button key={s.key} type="button" onClick={() => onPick(s.key)} className="inline-flex items-center gap-1 hover:text-accent">
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: READ_COLORS[s.key] }} />
            <span className="tabular-nums font-medium">{fmt(s.count)}</span> {label[s.key]}
          </button>
        ))}
      </p>
    </div>
  );
}

export function TopicsStat({ topics, clusters, onPick, max = 6, dense = false }: {
  topics: DashboardData["top_topics"]; clusters: MapCluster[]; onPick: (name: string) => void; max?: number; dense?: boolean;
}) {
  return (
    <div className="min-w-0">
      <Eyebrow>Top topics</Eyebrow>
      <div className={`flex flex-wrap gap-1.5 mt-1.5 ${dense ? "max-h-[54px] overflow-hidden" : ""}`}>
        {topics.slice(0, max).map((t) => {
          const color = topicColor(t.name, clusters);
          return (
            <button key={t.name} type="button" onClick={() => onPick(t.name)} title={`${t.name} · ${fmt(t.count)} papers`}
              className="inline-flex items-center gap-1.5 h-6 pl-2 pr-2.5 rounded-full text-[11px] text-ink-2 border max-w-full hover:text-ink hover:brightness-95 transition-colors"
              style={{ background: color ? rgba(color, 0.11) : "#f3f4f6", borderColor: color ? rgba(color, 0.38) : "#e5e7eb" }}>
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: color ?? "#d1d5db" }} />
              <span className="truncate">{t.name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function ProjectsStat({ projects, mapProjects, onHover, onPick, max = 3, dense = false }: {
  projects: DashProject[]; mapProjects: MapProject[]; onHover: (id: string | null) => void; onPick: (id: string) => void;
  max?: number; dense?: boolean;
}) {
  return (
    <div className="min-w-0">
      <Eyebrow>Projects</Eyebrow>
      <ul className={`${dense ? "mt-1 space-y-0.5" : "mt-1.5 space-y-1"}`} onMouseLeave={() => onHover(null)}>
        {projects.slice(0, max).map((p, i) => {
          const color = projectColor(p, i, mapProjects);
          const readPct = p.count ? (p.read / p.count) * 100 : 0;
          const readingPct = p.count ? (p.reading / p.count) * 100 : 0;
          return (
            <li key={p.id}>
              <button type="button" onClick={() => onPick(p.id)}
                onMouseEnter={() => onHover(p.id)} onFocus={() => onHover(p.id)} onBlur={() => onHover(null)}
                title={`${p.name}: ${fmt(p.read)} of ${fmt(p.count)} read`}
                className="group w-full flex items-center gap-2 h-5 text-left rounded hover:bg-gray-50">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
                <span className="text-xs text-ink-2 group-hover:text-ink truncate flex-1 min-w-0">{p.name}</span>
                <span className="flex h-1.5 w-14 rounded-full bg-gray-100 overflow-hidden shrink-0">
                  <span style={{ width: `${readPct}%`, background: color }} />
                  <span style={{ width: `${readingPct}%`, background: rgba(color, 0.4) }} />
                </span>
                <span className="text-[11px] text-ink-3 tabular-nums w-8 text-right shrink-0">{fmt(p.count)}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Soft skeleton while the map loads; or the "building" message. */
export function MapPlaceholder({ building = false, className = "" }: { building?: boolean; className?: string }) {
  return (
    <div className={`overflow-hidden bg-gray-50 ${className || "relative"}`} aria-busy="true">
      {[["12%", "20%", 120, "#ddd6fe"], ["48%", "46%", 150, "#bfdbfe"], ["70%", "14%", 110, "#fde68a"], ["26%", "58%", 100, "#fbcfe8"], ["76%", "56%", 90, "#bbf7d0"]].map(([l, t, s, c], i) => (
        <span key={i} className="absolute rounded-full animate-pulse blur-2xl opacity-70"
          style={{ left: l as string, top: t as string, width: s as number, height: (s as number) * 0.7, background: c as string }} />
      ))}
      <p className="absolute inset-0 grid place-items-center text-xs text-ink-3">{building ? "Laying out your library…" : ""}</p>
    </div>
  );
}

