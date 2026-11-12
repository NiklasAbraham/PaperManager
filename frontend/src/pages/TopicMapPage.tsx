import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import TopicMap, { type TopicMapApi } from "../components/dashboard/TopicMap";
import { useTopicMapData } from "../components/dashboard/useTopicMapData";
import { canCopyImage, copyPng, downloadPng, type ExportOptions } from "../components/dashboard/mapExport";
import {
  COLOR_MODES, DEFAULTS, LIMITS, filterPoints, isDefault, legendFor, matchingIds, parseSettings, settingsToParams, yearExtent,
  type Legend, type MapSettings,
} from "../components/dashboard/mapSettings";
import { fmt } from "../components/dashboard/helpers";
import { errorMessage } from "../components/insights/ui";

const sectionLabel = "text-[10px] font-semibold uppercase tracking-wide text-ink-3";
const chip = "h-7 px-2.5 rounded-full border text-xs";
const chipOn = "bg-accent-lo border-accent-border text-accent";
const chipOff = "bg-raised border-line text-ink-2 hover:border-accent-border hover:text-accent";

function Slider({ label, value, min, max, step, onChange, show }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; show?: string;
}) {
  return (
    <label className="block">
      <span className="flex justify-between text-xs text-ink-2"><span>{label}</span><span className="tabular-nums text-ink-3">{show ?? value}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full accent-[#7c3aed]" />
    </label>
  );
}

function LegendView({ legend }: { legend: Legend }) {
  if (legend.kind === "gradient") {
    return (
      <div className="flex items-center gap-2 text-[11px] text-ink-2">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-3">{legend.title}</span>
        <span>{legend.minLabel}</span>
        <span className="h-2 w-40 rounded-full" style={{ background: `linear-gradient(90deg, ${legend.stops.join(",")})` }} />
        <span>{legend.maxLabel}</span>
      </div>
    );
  }
  return (
    <ul className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]" aria-label={legend.title}>
      <li className="text-[10px] font-semibold uppercase tracking-wide text-ink-3">{legend.title}</li>
      {legend.items.map((it) => (
        <li key={it.label} className={`flex items-center gap-1.5 ${it.muted ? "text-ink-3" : "text-ink-2"}`}>
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: it.color }} />{it.label}
        </li>
      ))}
    </ul>
  );
}

export default function TopicMapPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const settings = useMemo(() => parseSettings(params), [params]);
  const set = (patch: Partial<MapSettings>) => setParams(settingsToParams({ ...settings, ...patch }), { replace: true });

  const { map, status, reclustering } = useTopicMapData(settings.clusters);
  const apiRef = useRef<TopicMapApi | null>(null);
  const [sheet, setSheet] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  // Debounced controls: the slider / search box move at once, the URL (and a re-cluster request) follows.
  const [kLocal, setKLocal] = useState<number | null>(settings.clusters);
  const [qLocal, setQLocal] = useState(settings.q);
  useEffect(() => {
    if (kLocal === settings.clusters) return;
    const t = setTimeout(() => set({ clusters: kLocal }), 500);
    return () => clearTimeout(t);
  });
  useEffect(() => {
    if (qLocal === settings.q) return;
    const t = setTimeout(() => set({ q: qLocal }), 250);
    return () => clearTimeout(t);
  });

  const extent = useMemo(() => yearExtent(map?.points ?? []), [map]);
  const checked = useMemo(
    () => settings.projects.filter((id) => map?.projects.some((p) => p.id === id)),
    [settings.projects, map]);
  const shownPoints = useMemo(() => filterPoints(map?.points ?? [], settings), [map, settings]);
  const view = useMemo(() => (map ? { ...map, points: shownPoints } : null), [map, shownPoints]);
  const matches = useMemo(() => matchingIds(shownPoints, settings.q), [shownPoints, settings.q]);
  const legend = useMemo(() => (view ? legendFor(settings.color, view, { projects: checked }, extent) : null), [view, settings.color, checked, extent]);
  const lib = shownPoints.filter((p) => !p.r).length;

  const autoK = map ? Math.min(LIMITS.clusters[1], Math.max(LIMITS.clusters[0], map.clusters.filter((c) => !c.muted).length || map.clusters.length)) : 6;
  const kShown = kLocal ?? autoK;

  const toggleProject = (id: string) =>
    set({ projects: checked.includes(id) ? checked.filter((x) => x !== id) : [...checked, id] });

  const exportOpts = (scale: number): ExportOptions | null => {
    const api = apiRef.current;
    if (!api) return null;
    const { w, h } = api.size();
    return { paint: (g) => api.paintView(g), width: w, height: h, scale, legend };
  };
  const run = async (what: "png2" | "png4" | "copy") => {
    const o = exportOpts(what === "png4" ? 4 : 2);
    if (!o) return;
    setBusy(true); setNote(null);
    try {
      if (what === "copy") { await copyPng(o); setNote({ ok: true, text: "Image copied" }); }
      else setNote({ ok: true, text: `Saved ${await downloadPng(o)}` });
    } catch (e) {
      setNote({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  const panel = (
    <div className="space-y-5 text-sm">
      <div className="flex items-center justify-between max-lg:justify-end">
        <h2 className="hidden lg:block text-sm font-semibold text-ink">Settings</h2>
      <button type="button" disabled={isDefault(settings) && kLocal === null && qLocal === ""} onClick={() => { setKLocal(null); setQLocal(""); setParams(settingsToParams(DEFAULTS), { replace: true }); }}
        className="h-7 px-2.5 text-xs border border-line text-ink-2 rounded-lg hover:border-accent-border hover:text-accent disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink-2">
        Reset
      </button>
      </div>
      <section>
        <h2 className={sectionLabel}>Colour by</h2>
        <div className="mt-1.5 flex flex-wrap gap-1.5" role="group" aria-label="Colour by">
          {COLOR_MODES.map((m) => (
            <button key={m.value} type="button" aria-pressed={settings.color === m.value} onClick={() => set({ color: m.value })}
              className={`${chip} ${settings.color === m.value ? chipOn : chipOff}`}>{m.label}</button>
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <h2 className={sectionLabel}>Show</h2>
        <label className="flex items-center gap-2 text-xs text-ink-2">
          <input type="checkbox" checked={settings.refs} onChange={(e) => set({ refs: e.target.checked })} className="accent-[#7c3aed]" />
          References (cited papers without a PDF)
        </label>
        <label className="flex items-center gap-2 text-xs text-ink-2">
          <input type="checkbox" checked={settings.labels} onChange={(e) => set({ labels: e.target.checked })} className="accent-[#7c3aed]" />
          Cluster labels
        </label>
        <Slider label="Label size" value={settings.labelSize} min={LIMITS.labelSize[0]} max={LIMITS.labelSize[1]} step={1}
          show={`${settings.labelSize} px`} onChange={(v) => set({ labelSize: v })} />
      </section>

      <section className="space-y-2">
        <h2 className={sectionLabel}>Dots</h2>
        <Slider label="Dot size" value={settings.size} min={LIMITS.size[0]} max={LIMITS.size[1]} step={0.05}
          show={`${settings.size.toFixed(2)}×`} onChange={(v) => set({ size: v })} />
        <Slider label="Dot opacity" value={settings.opacity} min={LIMITS.opacity[0]} max={LIMITS.opacity[1]} step={0.05}
          show={`${Math.round(settings.opacity * 100)} %`} onChange={(v) => set({ opacity: v })} />
      </section>

      <section className="space-y-2">
        <h2 className={sectionLabel}>Clusters</h2>
        <Slider label="Number of clusters" value={kShown} min={LIMITS.clusters[0]} max={LIMITS.clusters[1]} step={1}
          show={kLocal === null ? `${autoK} (auto)` : String(kLocal)} onChange={(v) => setKLocal(v)} />
        {kLocal !== settings.clusters || reclustering ? (
          <p className="text-[11px] text-ink-3" role="status">Re-clustering in the background…</p>
        ) : null}
      </section>

      {map && map.projects.length > 0 && (
        <section>
          <h2 className={sectionLabel}>Projects</h2>
          <p className="text-[11px] text-ink-3 mt-0.5">Check projects to light up where they live; the rest fades.</p>
          <ul className="mt-1.5 space-y-1 max-h-44 overflow-y-auto pr-1">
            {map.projects.map((p) => (
              <li key={p.id}>
                <label className="flex items-center gap-2 text-xs text-ink-2 cursor-pointer">
                  <input type="checkbox" checked={checked.includes(p.id)} onChange={() => toggleProject(p.id)} className="accent-[#7c3aed]" />
                  <span className="inline-block w-2.5 h-2.5 rounded-full shrink-0" style={{ background: p.color }} />
                  <span className="truncate">{p.name}</span>
                  <span className="ml-auto text-ink-3 tabular-nums">{p.count}</span>
                </label>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-2">
        <h2 className={sectionLabel}>Filters</h2>
        {extent && extent.max > extent.min && (
          <div className="space-y-1">
            <Slider label="Year from" value={settings.yearMin ?? extent.min} min={extent.min} max={extent.max} step={1}
              onChange={(v) => set({ yearMin: v <= extent.min ? null : v, yearMax: settings.yearMax !== null && settings.yearMax < v ? v : settings.yearMax })} />
            <Slider label="Year to" value={settings.yearMax ?? extent.max} min={extent.min} max={extent.max} step={1}
              onChange={(v) => set({ yearMax: v >= extent.max ? null : v, yearMin: settings.yearMin !== null && settings.yearMin > v ? v : settings.yearMin })} />
          </div>
        )}
        <label className="block">
          <span className="text-xs text-ink-2">Highlight titles containing</span>
          <input type="search" value={qLocal} onChange={(e) => setQLocal(e.target.value)} placeholder="e.g. diffusion"
            className="mt-1 w-full h-8 px-2.5 rounded-lg border border-line bg-raised text-xs text-ink placeholder:text-ink-3 focus:outline-none focus:border-accent" />
        </label>
        {matches && <p className="text-[11px] text-ink-3">{fmt(matches.size)} match{matches.size === 1 ? "" : "es"}</p>}
      </section>

    </div>
  );

  const btn = "h-8 px-3 text-xs border border-line text-ink-2 rounded-lg hover:border-accent-border hover:text-accent disabled:opacity-50 bg-raised";

  return (
    <div className="h-[calc(100vh-53px)] min-h-[560px] flex flex-col" data-testid="topic-map-page">
      <header className="shrink-0 flex flex-wrap items-center gap-x-3 gap-y-2 px-4 sm:px-6 py-2.5 border-b border-line bg-raised">
        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-ink">Topic map</h1>
          {view && <p className="text-xs text-ink-3">{fmt(lib)} library papers{shownPoints.length > lib ? ` · ${fmt(shownPoints.length - lib)} references` : ""}</p>}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {note && <span role="status" className={`text-xs ${note.ok ? "text-ink-3" : "text-coral"}`}>{note.text}</span>}
          <button type="button" className={btn} disabled={!view || busy} onClick={() => run("png2")}>Export PNG</button>
          <button type="button" className={btn} disabled={!view || busy} onClick={() => run("png4")} title="Four times the pixels, for print">PNG 4×</button>
          {canCopyImage() && <button type="button" className={btn} disabled={!view || busy} onClick={() => run("copy")}>Copy image</button>}
          <button type="button" className={`${btn} lg:hidden`} aria-expanded={sheet} onClick={() => setSheet((v) => !v)}>Settings</button>
        </div>
      </header>

      <div className="flex-1 min-h-0 flex">
        <div className="flex-1 min-w-0 flex flex-col">
          <div className="relative flex-1 min-h-0 bg-raised">
            {view && status === "ready" ? (
              <TopicMap data={view} apiRef={apiRef} onOpenPaper={(id) => navigate(`/paper/${id}`)} className="absolute inset-0"
                colorMode={settings.color} checkedProjects={checked} dotSize={settings.size} dotOpacity={settings.opacity}
                showLabels={settings.labels} labelSize={settings.labelSize} refsVisible={settings.refs} highlightIds={matches}
                yearRange={extent} zoomButtons pad={16} fit />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center text-sm text-ink-3">
                {status === "none" ? "No map yet: add papers with embeddings to see your library as a map."
                  : status === "building" ? "Building the map for the first time (about two minutes)…" : "Loading the map…"}
              </div>
            )}
            {reclustering && view && (
              <div role="status" className="absolute left-3 top-3 rounded-full bg-raised/90 border border-line px-2.5 py-1 text-[11px] text-ink-2">Re-clustering…</div>
            )}
          </div>
          <div className="shrink-0 border-t border-line-s bg-raised px-4 sm:px-6 py-2 space-y-1">
            {legend && <LegendView legend={legend} />}
            <p className="text-[11px] text-ink-3">Hover a dot for the title · click to open · drag to pan · Ctrl/⌘ + scroll to zoom</p>
          </div>
        </div>
        <aside aria-label="Map settings" className="hidden lg:block w-72 shrink-0 border-l border-line bg-raised overflow-y-auto p-4">{panel}</aside>
      </div>

      {sheet && (
        <div role="dialog" aria-label="Map settings" className="lg:hidden fixed inset-x-0 bottom-0 z-40 max-h-[65vh] overflow-y-auto rounded-t-xl border-t border-line bg-raised shadow-[0_-8px_24px_rgba(0,0,0,0.12)] p-4 pb-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-ink">Map settings</h2>
            <button type="button" onClick={() => setSheet(false)} className="h-7 px-2.5 text-xs text-ink-2 border border-line rounded-lg">Close</button>
          </div>
          {panel}
        </div>
      )}
    </div>
  );
}
