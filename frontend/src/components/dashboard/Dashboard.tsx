import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { DashVariant } from "./helpers";
import { fmt } from "./helpers";
import TopicMap from "./TopicMap";
import { AddedStat, MapPlaceholder, ProjectsStat, ReadingStat, TopicsStat } from "./Pieces";
import { useDashboardData } from "./useDashboardData";

interface Props {
  variant: Exclude<DashVariant, "off">;
  /** The "Library · N papers" heading; the band variant draws it on top of the map. */
  title: React.ReactNode;
  onFilter: (key: "reading_status" | "topic" | "project_id", value: string) => void;
}

const STRIP = "flex gap-3 overflow-x-auto snap-x snap-mandatory scroll-px-4 sm:scroll-px-6 lg:scroll-px-0 -mx-4 px-4 sm:-mx-6 sm:px-6 lg:mx-0 lg:px-0 lg:overflow-visible lg:grid lg:grid-cols-4 pb-1 lg:pb-0 [scrollbar-width:none]";
const COLLAPSED_KEY = "pm_dash_map_collapsed";
const heading = (t: React.ReactNode) => <h1 className="text-sm font-semibold text-ink">{t}</h1>;

export default function Dashboard({ variant, title, onFilter }: Props) {
  const navigate = useNavigate();
  const { dash, map, mapStatus, dashLoading } = useDashboardData(true);
  const [hoverProject, setHoverProject] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(COLLAPSED_KEY) === "1"; } catch { return false; }
  });
  const toggle = () => setCollapsed((c) => {
    try { localStorage.setItem(COLLAPSED_KEY, c ? "0" : "1"); } catch { /* private mode */ }
    return !c;
  });

  const clusters = map?.clusters ?? [];
  const mapProjects = map?.projects ?? [];
  const showStats = !!dash;
  const showMap = mapStatus !== "none";
  if (!showStats && !showMap && !dashLoading) return heading(title);

  const open = (id: string) => navigate(`/paper/${id}`);
  const mapEl = (interactive = true, className = "absolute inset-0", inset?: { top: number; bottom: number }, pad?: number, fit?: boolean) =>
    map && mapStatus === "ready" ? (
      <TopicMap data={map} activeProjectId={hoverProject} interactive={interactive} onOpenPaper={open} className={className}
        insetTop={inset?.top} insetBottom={inset?.bottom} pad={pad} fit={fit} />
    ) : (
      <MapPlaceholder building={mapStatus === "building"} className={className} />
    );

  const added = dash && <AddedStat dash={dash} dense />;
  const reading = dash && <ReadingStat reading={dash.reading} onPick={(s) => onFilter("reading_status", s)} />;
  const topics = (max: number, dense: boolean) => dash && dash.top_topics.length > 0 && (
    <TopicsStat topics={dash.top_topics} clusters={clusters} onPick={(n) => onFilter("topic", n)} max={max} dense={dense} />
  );
  const projects = (max: number, dense: boolean) => dash && dash.projects.length > 0 && (
    <ProjectsStat projects={dash.projects} mapProjects={mapProjects} onHover={setHoverProject}
      onPick={(id) => onFilter("project_id", id)} max={max} dense={dense} />
  );
  const skeletonTile = <div className="h-[92px] rounded-xl bg-gray-100/70 animate-pulse" />;

  if (variant === "a") {
    return (
      <div className="space-y-3">
        {heading(title)}
        <section aria-label="Dashboard" className="bg-raised border border-line rounded-xl overflow-hidden grid lg:grid-cols-[300px_minmax(0,1fr)] lg:h-[400px]">
          {(showStats || dashLoading) && (
            <div className="flex gap-6 overflow-x-auto snap-x snap-mandatory scroll-px-4 px-4 lg:scroll-px-0 py-3 border-b border-line-s [scrollbar-width:none] lg:flex-col lg:gap-3.5 lg:overflow-hidden lg:p-4 lg:border-b-0 lg:border-r">
              {dash ? (
                <>
                  <div className="snap-start shrink-0 w-[220px] lg:w-auto">{added}</div>
                  <div className="snap-start shrink-0 w-[220px] lg:w-auto">{reading}</div>
                  <div className="snap-start shrink-0 w-[220px] lg:w-auto">{topics(4, false)}</div>
                  <div className="snap-start shrink-0 w-[220px] lg:w-auto">{projects(3, false)}</div>
                </>
              ) : skeletonTile}
            </div>
          )}
          {showMap && (
            <div className={`flex flex-col h-[260px] lg:h-[400px] min-w-0 ${showStats || dashLoading ? "" : "lg:col-span-2"}`}>
              <div className="relative flex-1 min-h-0">{mapEl(true, "absolute inset-0", undefined, 16, true)}</div>
              <p className="hidden sm:block shrink-0 px-4 pb-2 text-center text-[11px] text-ink-3">
                Hover a dot for the title · click to open · hover a project to see where it lives
              </p>
            </div>
          )}
        </section>
      </div>
    );
  }

  if (variant === "b") {
    const tile = "snap-start shrink-0 w-[78%] sm:w-[46%] lg:w-auto h-[100px] bg-raised border border-line rounded-xl px-3.5 py-2 overflow-hidden";
    return (
      <div className="space-y-3">
        {heading(title)}
        {(showStats || dashLoading) && (
          dash ? (
            <section aria-label="Dashboard" className={STRIP}>
              <div className={tile}>{added}</div>
              <div className={tile}>{reading}</div>
              <div className={tile}>{topics(6, true)}</div>
              <div className={tile}>{projects(3, true)}</div>
            </section>
          ) : skeletonTile
        )}
        {showMap && (
          <section aria-label="Topic map" className="bg-raised border border-line rounded-xl overflow-hidden">
            <button type="button" onClick={toggle} aria-expanded={!collapsed}
              className="w-full flex items-center gap-2 px-3.5 h-9 text-left hover:bg-gray-50">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-3">Topic map</span>
              <span className="text-xs text-ink-3 truncate">
                {dash ? `${fmt(dash.total)} papers${dash.references ? ` · ${fmt(dash.references)} references` : ""}` : ""}
              </span>
              <svg className={`ml-auto w-3.5 h-3.5 text-ink-3 transition-transform ${collapsed ? "" : "rotate-180"}`} viewBox="0 0 20 20" fill="currentColor"><path d="M5.5 7.5 10 12l4.5-4.5-1-1L10 10 6.5 6.5z" /></svg>
            </button>
            {!collapsed && <div className="relative h-[240px] sm:h-[280px] border-t border-line-s">{mapEl()}</div>}
          </section>
        )}
      </div>
    );
  }

  // c: the map is the band's background; the stats float on it as translucent cards
  return <BandVariant title={title} mapEl={mapEl} showMap={showMap} dash={dash} dashLoading={dashLoading}
    parts={{ added, reading, topics: topics(4, true), projects: projects(3, true) }} />;
}

function BandVariant({ title, mapEl, showMap, dash, dashLoading, parts }: {
  title: React.ReactNode; mapEl: (interactive?: boolean, className?: string, inset?: { top: number; bottom: number }) => React.ReactNode; showMap: boolean;
  dash: unknown; dashLoading: boolean; parts: Record<"added" | "reading" | "topics" | "projects", React.ReactNode>;
}) {
  const [active, setActive] = useState(false);
  const card = "snap-start shrink-0 w-[70%] sm:w-[46%] lg:w-auto h-[92px] bg-white/75 backdrop-blur-md border border-white/70 shadow-sm rounded-xl px-3 py-2 overflow-hidden pointer-events-auto";
  return (
    <section aria-label="Dashboard" className="relative h-[290px] rounded-xl overflow-hidden border border-line bg-raised"
      onPointerEnter={() => setActive(true)} onPointerLeave={() => setActive(false)}>
      {showMap && (
        <div className={`absolute inset-0 transition-opacity duration-300 ${active ? "opacity-100" : "opacity-60"}`}>
          {mapEl(active, "absolute inset-0", { top: 34, bottom: 74 })}
        </div>
      )}
      <div className="absolute inset-x-0 top-0 h-14 bg-gradient-to-b from-white/95 via-white/70 to-transparent pointer-events-none" />
      <div className="relative z-10 h-full flex flex-col justify-between p-3 pointer-events-none">
        <div className="px-1">{heading(title)}</div>
        {(dash || dashLoading) && (
          <div className="flex gap-3 overflow-x-auto snap-x snap-mandatory lg:grid lg:grid-cols-4 lg:overflow-visible [scrollbar-width:none]">
            {dash ? (
              <>
                <div className={card}>{parts.added}</div>
                <div className={card}>{parts.reading}</div>
                <div className={card}>{parts.topics}</div>
                <div className={card}>{parts.projects}</div>
              </>
            ) : <div className="h-[92px] w-full rounded-xl bg-white/60 animate-pulse" />}
          </div>
        )}
      </div>
    </section>
  );
}
