// Ported from the thesis desk's structure card (3Dmol.js, BSD-3-Clause, vendored in public/vendor/3dmol).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { StructureSpec } from './types';
import {
  CHAIN_CYCLE, DIM, PICK, THREE_TO_ONE, WATER, asLigand, colour, fetchCoordinates, kabsch, load3Dmol, matcher, pdbFrames, plddtColour,
  sourceName, superpose, type Atom3D, type Frames,
} from './viewer';

/* eslint-disable @typescript-eslint/no-explicit-any */

/** A model that plays as a trajectory: its frames, and frame 0's Cα (after alignment) to fit every frame on. */
type Traj = { fr: Frames; ref: { a: Atom3D; x: number; y: number; z: number }[]; fit: boolean };
type Loaded = { label: string; atoms: Atom3D[]; model: any; note?: string; traj?: Traj };
type Pick = { mi: number; chain: string; resi: number; resn: string };
type Hover = { mi: number; a: Atom3D } | null;

const pickKey = (p: Pick) => `${p.mi}/${p.chain}/${p.resi}`;
/** R792 for residues, SO4 1110 for het groups. */
const resName = (p: Pick) => (THREE_TO_ONE[p.resn] ? `${THREE_TO_ONE[p.resn]}${p.resi}` : `${p.resn} ${p.resi}`);

/**
 * A 3D view of one or more structures with named highlights (3Dmol.js). Used by the
 * ```structure block in replies and notes and by the preview of .pdb / .cif files.
 * Chips toggle models and highlights and zoom to them; hovering names the residue;
 * clicking residues collects them into a list that copies as text for the chat.
 */
export function StructureView({ spec: specIn, fill = false }: { spec: StructureSpec; fill?: boolean }) {
  const specKey = JSON.stringify(specIn);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const spec = useMemo(() => specIn, [specKey]);
  const stage = useRef<HTMLDivElement>(null);
  const viewer = useRef<any>(null);
  const [loaded, setLoaded] = useState<Loaded[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hiddenModels, setHiddenModels] = useState<Set<number>>(new Set());
  const [hiddenHl, setHiddenHl] = useState<Set<number>>(() => new Set((spec.highlights ?? []).flatMap((h, i) => (h.hidden ? [i] : []))));
  const [dim, setDim] = useState(!!spec.dim);
  const [surface, setSurface] = useState(spec.representation === 'surface');
  const [spin, setSpin] = useState(false);
  const [big, setBig] = useState(false);
  const [picks, setPicks] = useState<Pick[]>([]);
  const [hover, setHover] = useState<Hover>(null);
  const [copied, setCopied] = useState(false);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const firstFrames = spec.models.map((m) => m.frames).find((f) => typeof f === 'object') as
    { dt?: number; unit?: string; fps?: number } | undefined;
  const [fps, setFps] = useState(firstFrames?.fps ?? 4);
  const [loop, setLoop] = useState(true);
  const [showGraph, setShowGraph] = useState(true);

  /* Load coordinates and build the viewer once per spec. */
  useEffect(() => {
    let live = true;
    const el = stage.current!;
    setLoaded(null); setError(null); setPicks([]); setFrame(0); setPlaying(false);
    (async () => {
      const [$3Dmol, coords] = await Promise.all([load3Dmol(), Promise.all(spec.models.map(fetchCoordinates))]);
      if (!live) return;
      const v = $3Dmol.createViewer(el, { backgroundColor: 'white', antialias: true });
      viewer.current = v;
      const out: Loaded[] = coords.map((c, mi) => {
        const want = spec.models[mi].frames;
        const fr = c.format === 'pdb' && want !== false ? pdbFrames(c.data) : null;
        const model = v.addModel(fr ? fr.first : c.data, c.format);
        const atoms = model.selectedAtoms({}) as Atom3D[];
        asLigand(atoms, c);
        for (const a of atoms) a.dm = mi;
        const L: Loaded = { label: spec.models[mi].label ?? c.name, atoms, model };
        if (fr) {
          const fit = typeof want === 'object' ? want.fit !== false : true;
          L.traj = { fr, ref: [], fit };
          L.note = `${fr.xyz.length} frames${fr.uneven ? ' (atom counts differ between frames)' : ''}`;
        }
        return L;
      });
      spec.models.forEach((m, mi) => {
        if (!m.align) return;
        const to = m.align.to ?? 0;
        if (to === mi || !out[to]) { out[mi].note = 'align: bad target'; return; }
        const r = superpose(out[mi].atoms, out[to].atoms, m.align);
        out[mi].note = ('error' in r ? `not aligned: ${r.error}` : `on ${out[to].label}: ${r.rmsd.toFixed(2)} Å over ${r.n} Cα`)
          + (out[mi].traj ? ` · ${out[mi].traj!.fr.xyz.length} frames` : '');
      });
      // frame 0 as placed (after any alignment) is what every later frame is fitted onto
      for (const L of out) if (L.traj) L.traj.ref = L.atoms.filter((a) => a.atom === 'CA' && !a.hetflag).map((a) => ({ a, x: a.x, y: a.y, z: a.z }));
      v.setHoverable({}, true, (a: Atom3D) => setHover({ mi: a.dm, a }), () => setHover(null));
      v.setHoverDuration?.(60);
      v.setClickable({}, true, (a: Atom3D) => {
        if (a.hetflag && WATER.has(a.resn)) return;
        const p = { mi: a.dm, chain: a.chain, resi: Number(a.resi), resn: a.resn };
        setPicks((ps) => (ps.some((q) => pickKey(q) === pickKey(p)) ? ps.filter((q) => pickKey(q) !== pickKey(p)) : [...ps, p]));
      });
      setLoaded(out);
    })().catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
      try { viewer.current?.clear(); } catch { /* already gone */ }
      viewer.current = null;
      el.innerHTML = '';
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [specKey]);

  /* Restyle whenever what is shown changes. */
  const restyle = useCallback((zoom: boolean) => {
    const v = viewer.current;
    if (!v || !loaded) return;
    const hls = (spec.highlights ?? []).map((h, i) => ({ h, i, on: !hiddenHl.has(i) }));
    const pickSet = new Set(picks.map(pickKey));
    let chainIndex = 0;
    const chainColour = new Map<string, string>();
    loaded.forEach((L, mi) => {
      const ms = spec.models[mi];
      const visible = matcher({ chain: ms.chains }, mi);
      const fits = hls.filter((x) => x.on).map((x) => ({ ...x, f: matcher(x.h, mi) }));
      for (const a of L.atoms) {
        const water = a.hetflag && WATER.has(a.resn);
        a.dvis = !hiddenModels.has(mi) && !water && visible(a) && (!a.hetflag || spec.ligands !== false);
        const ck = `${mi}/${a.chain}`;
        if (!chainColour.has(ck)) chainColour.set(ck, CHAIN_CYCLE[chainIndex++ % CHAIN_CYCLE.length]);
        const scheme = ms.chainColors?.[a.chain] ?? ms.color ?? 'chain';
        let c = scheme === 'chain' ? chainColour.get(ck)! : scheme === 'plddt' ? plddtColour(a.b) : scheme === 'spectrum' ? '' : colour(scheme, chainColour.get(ck)!);
        a.dstick = false; a.dsphere = false; a.dsurf = -1; a.dhl = -1;
        for (const x of fits) {
          if (!x.f(a)) continue;
          a.dhl = x.i;
          c = colour(x.h.color, CHAIN_CYCLE[(x.i + 1) % CHAIN_CYCLE.length]);
          if (x.h.style === 'sticks') a.dstick = true;
          if (x.h.style === 'spheres') a.dsphere = true;
          if (x.h.style === 'surface') a.dsurf = x.i;
        }
        if (dim && a.dhl < 0 && !a.hetflag) c = DIM;
        a.dpick = pickSet.has(`${mi}/${a.chain}/${Number(a.resi)}`);
        if (a.dpick) { c = PICK; a.dstick = true; }
        a.dcol = c;
      }
    });
    const col = (a: Atom3D) => a.dcol || '#3C6DA8';
    const carbon = (a: Atom3D) => (a.elem === 'C' ? col(a) : undefined);
    v.setStyle({}, {});
    loaded.forEach((L, mi) => {
      const op = spec.models[mi].opacity ?? 1;
      const spectrum = (spec.models[mi].color ?? '') === 'spectrum';
      v.setStyle({ model: L.model, dvis: true, hetflag: false }, { cartoon: spectrum ? { color: 'spectrum', opacity: op } : { colorfunc: col, opacity: op } });
      // het groups: grey ball and stick, unless a highlight names them; then its colour, so that
      // two copies of a ligand (crystal vs prediction, frame vs frame) can be told apart
      v.addStyle({ model: L.model, dvis: true, hetflag: true, dhl: -1 }, { stick: { radius: 0.18, colorscheme: 'grayCarbon' }, sphere: { scale: 0.28, colorscheme: 'grayCarbon' } });
      v.addStyle({ model: L.model, dvis: true, dstick: true }, { stick: { radius: 0.22, colorfunc: (a: Atom3D) => carbon(a) ?? elementColour(a.elem) } });
      v.addStyle({ model: L.model, dvis: true, hetflag: true, dstick: true }, { sphere: { scale: 0.26, colorfunc: (a: Atom3D) => carbon(a) ?? elementColour(a.elem) } });
      v.addStyle({ model: L.model, dvis: true, dsphere: true }, { sphere: { scale: 0.85, colorfunc: col } });
    });
    v.removeAllSurfaces();
    v.removeAllLabels();
    if (surface) {
      loaded.forEach((L, mi) => {
        if (hiddenModels.has(mi)) return;
        v.addSurface('VDW', { opacity: 0.6, colorfunc: col }, { model: L.model, dvis: true, hetflag: false });
      });
    } else {
      hls.forEach(({ h, i, on }) => {
        if (!on || h.style !== 'surface') return;
        v.addSurface('VDW', { opacity: 0.75, color: colour(h.color, CHAIN_CYCLE[(i + 1) % CHAIN_CYCLE.length]) }, { dvis: true, dsurf: i });
      });
    }
    for (const p of picks) {
      const ca = loaded[p.mi]?.atoms.find((a) => a.chain === p.chain && Number(a.resi) === p.resi && (a.atom === 'CA' || a.hetflag));
      if (ca && ca.dvis) {
        v.addLabel(`${p.chain}:${resName(p)}`, {
          position: { x: ca.x, y: ca.y, z: ca.z }, fontSize: 11, fontColor: '#111827', backgroundColor: '#FFFFFF',
          backgroundOpacity: 0.85, borderColor: PICK, borderThickness: 1, inFront: true, font: 'ui-monospace, Menlo, monospace',
        });
      }
    }
    if (zoom) {
      const f = spec.focus;
      const fi = typeof f === 'number' ? f : (spec.highlights ?? []).findIndex((h) => h.label === f);
      if (f != null && fi >= 0 && !hiddenHl.has(fi)) v.zoomTo({ dvis: true, dhl: fi });
      else v.zoomTo({ dvis: true });
    }
    v.render();
  }, [loaded, spec, hiddenHl, hiddenModels, dim, surface, picks]);

  const zoomed = useRef(false);
  useEffect(() => { zoomed.current = false; }, [loaded]);
  useEffect(() => {
    restyle(!zoomed.current);
    if (loaded) zoomed.current = true;
  }, [restyle, loaded]);

  useEffect(() => { viewer.current?.spin(spin ? 'y' : false, 0.6); }, [spin, loaded]);

  /* Trajectories: write frame k's coordinates into the atoms of frame 0, fit, and rebuild the styles. */
  const nFrames = loaded ? Math.min(...loaded.flatMap((L) => (L.traj ? [L.traj.fr.xyz.length] : [Infinity]))) : Infinity;
  const hasFrames = Number.isFinite(nFrames) && nFrames > 1;
  const shownFrame = useRef(0);
  useEffect(() => {
    if (!loaded || !hasFrames || shownFrame.current === frame) return;
    loaded.forEach((L, mi) => {
      if (!L.traj) return;
      const { fr, ref, fit } = L.traj;
      const X = fr.xyz[frame];
      for (const a of L.atoms) {
        const i = fr.index.get(Number(a.serial));
        if (i == null || 3 * i + 2 >= X.length) continue;
        a.x = X[3 * i]; a.y = X[3 * i + 1]; a.z = X[3 * i + 2];
      }
      const al = spec.models[mi].align;
      if (al && loaded[al.to ?? 0] && (al.to ?? 0) !== mi) superpose(L.atoms, loaded[al.to ?? 0].atoms, al);
      else if (fit && ref.length >= 3) {
        const f = kabsch(ref.map((r) => [r.a.x, r.a.y, r.a.z]), ref.map((r) => [r.x, r.y, r.z]));
        for (const a of L.atoms) { const [x, y, z] = f.apply([a.x, a.y, a.z]); a.x = x; a.y = y; a.z = z; }
      }
    });
    shownFrame.current = frame;
    restyle(false);
  }, [frame, loaded, hasFrames, spec, restyle]);
  useEffect(() => { shownFrame.current = 0; }, [loaded]);

  useEffect(() => {
    if (!playing || !hasFrames) return;
    const t = setInterval(() => {
      setFrame((f) => {
        if (f + 1 < nFrames) return f + 1;
        if (loop) return 0;
        setPlaying(false);
        return f;
      });
    }, 1000 / fps);
    return () => clearInterval(t);
  }, [playing, fps, loop, nFrames, hasFrames]);
  /* Distances per frame for the strip chart. Raw frame coordinates suffice: both ends lie in one model,
     and the fit moves that model rigidly. A selection matching several atoms counts as its centroid. */
  const series = useMemo(() => {
    if (!loaded || !hasFrames || !spec.distances?.length) return [];
    return spec.distances.map((d, di) => {
      const colourOf = colour(d.color, CHAIN_CYCLE[di % CHAIN_CYCLE.length]);
      const base = { label: d.label, color: colourOf, threshold: d.threshold };
      const ends = [d.a, d.b].map((sel) => loaded.flatMap((L, mi) => {
        const f = matcher(sel, mi);
        return L.atoms.filter((a) => f(a)).map((a) => ({ a, mi }));
      }));
      const empty = ends.findIndex((e) => e.length === 0);
      if (empty >= 0) return { ...base, values: null, error: `${empty ? 'b' : 'a'} matches no atom` };
      const models = new Set(ends.flat().map((e) => e.mi));
      if (models.size > 1) return { ...base, values: null, error: 'a and b must be in one model' };
      const L = loaded[[...models][0]];
      const at = (k: number, list: { a: Atom3D }[]) => {
        const c = [0, 0, 0];
        for (const { a } of list) {
          const i = L.traj?.fr.index.get(Number(a.serial));
          const X = L.traj?.fr.xyz[k];
          const v = X && i != null ? [X[3 * i], X[3 * i + 1], X[3 * i + 2]] : [a.x, a.y, a.z];
          c[0] += v[0]; c[1] += v[1]; c[2] += v[2];
        }
        return c.map((x) => x / list.length);
      };
      const values = Array.from({ length: nFrames }, (_, k) => {
        const p = at(k, ends[0]), q = at(k, ends[1]);
        return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
      });
      return { ...base, values, error: undefined as string | undefined };
    });
  }, [loaded, hasFrames, nFrames, spec]);

  const stepFrame = (d: number) => { setPlaying(false); setFrame((f) => Math.min(nFrames - 1, Math.max(0, f + d))); };
  const timeLabel = (k: number) => {
    if (!firstFrames?.dt) return '';
    const t = k * firstFrames.dt;
    return ` · ${Number.isInteger(t) ? t : t.toFixed(2)} ${firstFrames.unit ?? ''}`.trimEnd();
  };

  /* Keep the canvas sized to its box (pane drags, fullscreen, the expand toggle). */
  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const ro = new ResizeObserver(() => { viewer.current?.resize(); viewer.current?.render(); });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const focusHighlight = (i: number) => {
    const v = viewer.current;
    if (!v) return;
    if (hiddenHl.has(i)) return;
    v.zoomTo({ dvis: true, dhl: i }, 500);
  };
  const toggle = <T,>(set: Set<T>, x: T) => { const n = new Set(set); if (n.has(x)) n.delete(x); else n.add(x); return n; };

  const pickText = () => {
    const groups = new Map<string, Pick[]>();
    for (const p of picks) {
      const k = `${loaded?.[p.mi]?.label ?? p.mi} chain ${p.chain}`;
      groups.set(k, [...(groups.get(k) ?? []), p]);
    }
    return [...groups].map(([k, ps]) => `${k}: ${ps.sort((a, b) => a.resi - b.resi).map(resName).join(', ')}`).join('; ');
  };
  const copy = async () => {
    await navigator.clipboard.writeText(pickText());
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  const png = () => {
    const uri = viewer.current?.pngURI();
    if (!uri) return;
    const a = document.createElement('a');
    a.href = uri; a.download = `${(spec.title ?? loaded?.[0]?.label ?? 'structure').replace(/[^\w.-]+/g, '_')}.png`;
    a.click();
  };
  const full = () => {
    const fig = stage.current?.closest('.structure') as HTMLElement | null;
    if (document.fullscreenElement) document.exitFullscreen(); else fig?.requestFullscreen?.();
  };

  const height = fill ? undefined : (big ? 640 : spec.height ?? 380);
  const hl = spec.highlights ?? [];
  return (
    <figure className={`kc-card structure ${fill ? 'structure-fill' : ''}`}>
      <header>
        <span className="kc-card-kind">structure</span>
        <span className="kc-card-title">{spec.title ?? loaded?.map((l) => l.label).join(' · ') ?? 'structure'}</span>
        <button type="button" className={`kc-btn ${surface ? 'on' : ''}`} title="Molecular surface over the cartoon" onClick={() => setSurface((s) => !s)}>surface</button>
        <button type="button" className={`kc-btn ${dim ? 'on' : ''}`} title="Grey everything no highlight covers" onClick={() => setDim((d) => !d)}>dim</button>
        <button type="button" className={`kc-btn ${spin ? 'on' : ''}`} title="Spin about the vertical axis" onClick={() => setSpin((s) => !s)}>spin</button>
        <button type="button" className="kc-btn" title="Back to the starting view" onClick={() => restyle(true)}>reset</button>
        {!fill && <button type="button" className="kc-btn" title="Taller stage" onClick={() => setBig((b) => !b)}>{big ? '▴' : '▾'}</button>}
        <button type="button" className="kc-btn" title="Fullscreen" onClick={full}>⤢</button>
        <button type="button" className="kc-btn" title="Save the current view as PNG" onClick={png}>png</button>
      </header>
      <div className="structure-stage" style={height ? { height } : undefined}>
        <div ref={stage} className="structure-canvas" />
        {!loaded && !error && <div className="structure-wait">loading {spec.models.map(sourceName).join(', ')} …</div>}
        {error && <div className="structure-wait structure-err">{error}</div>}
        <div className="structure-hover">
          {hover
            ? <>{loaded?.[hover.mi]?.label} · {hover.a.chain} {hover.a.resn} {hover.a.resi} · {hover.a.atom}{hover.a.b != null && <> · B {Number(hover.a.b).toFixed(1)}</>}</>
            : <span className="kc-muted">hover a residue · click to pick</span>}
        </div>
      </div>
      {loaded && hasFrames && (
        <div className="structure-player">
          <button type="button" className="kc-btn" title={playing ? 'Pause' : 'Play the trajectory'} onClick={() => {
            if (!playing && frame >= nFrames - 1) setFrame(0);
            setPlaying((p) => !p);
          }}>{playing ? '❚❚' : '▶'}</button>
          <button type="button" className="kc-btn" title="Previous frame" onClick={() => stepFrame(-1)}>‹</button>
          <input type="range" min={0} max={nFrames - 1} value={frame} aria-label="Frame"
            onChange={(e) => { setPlaying(false); setFrame(Number(e.target.value)); }} />
          <button type="button" className="kc-btn" title="Next frame" onClick={() => stepFrame(1)}>›</button>
          <span className="structure-frame">frame {frame} / {nFrames - 1}{timeLabel(frame)}</span>
          <select value={fps} title="Frames per second" onChange={(e) => setFps(Number(e.target.value))}>
            {[1, 2, 4, 8, 15].map((f) => <option key={f} value={f}>{f} fps</option>)}
          </select>
          <button type="button" className={`kc-btn ${loop ? 'on' : ''}`} title="Start again at the end" onClick={() => setLoop((l) => !l)}>loop</button>
          {series.length > 0 && (
            <button type="button" className={`kc-btn ${showGraph ? 'on' : ''}`} title="Distances per frame under the slider" onClick={() => setShowGraph((g) => !g)}>graph</button>
          )}
        </div>
      )}
      {loaded && hasFrames && showGraph && series.length > 0 && (
        <StripChart series={series} n={nFrames} frame={frame} label={timeLabel}
          onSeek={(k) => { setPlaying(false); setFrame(k); }} />
      )}
      {loaded && (
        <div className="structure-chips">
          {loaded.map((L, mi) => {
            const ms = spec.models[mi];
            const sw = ms.color && ms.color !== 'chain' && ms.color !== 'plddt' && ms.color !== 'spectrum' ? colour(ms.color, '') : CHAIN_CYCLE[0];
            return (
              <button type="button" key={`m${mi}`} className={`structure-chip ${hiddenModels.has(mi) ? 'off' : ''}`} title={L.note ?? 'Show / hide this model'}
                onClick={() => setHiddenModels((s) => toggle(s, mi))}>
                <i style={{ background: sw }} />{L.label}{ms.chains ? ` (${ms.chains.join('')})` : ''}
                {L.note && <em>{L.note}</em>}
                {ms.pdb && <a href={`https://www.rcsb.org/structure/${ms.pdb}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} title="RCSB entry">↗</a>}
                {ms.afdb && <a href={`https://alphafold.ebi.ac.uk/entry/${ms.afdb}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} title="AlphaFold DB entry">↗</a>}
                {ms.ccd && <a href={`https://www.rcsb.org/ligand/${encodeURIComponent(String(ms.ccd).toUpperCase())}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} title="RCSB chemical component">↗</a>}
                {ms.pubchem != null && String(ms.pubchem) !== '' && <a href={`https://pubchem.ncbi.nlm.nih.gov/compound/${encodeURIComponent(String(ms.pubchem))}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} title="PubChem compound">↗</a>}
              </button>
            );
          })}
          {hl.map((h, i) => (
            <span key={`h${i}`} className={`structure-chip hl ${hiddenHl.has(i) ? 'off' : ''}`}>
              <input type="checkbox" checked={!hiddenHl.has(i)} onChange={() => setHiddenHl((s) => toggle(s, i))} title="Show / hide" />
              <button type="button" onClick={() => focusHighlight(i)} title="Zoom to it">
                <i style={{ background: colour(h.color, CHAIN_CYCLE[(i + 1) % CHAIN_CYCLE.length]) }} />{h.label}
              </button>
            </span>
          ))}
        </div>
      )}
      {picks.length > 0 && (
        <div className="structure-picks">
          <span className="kc-card-kind">picked</span>
          <code>{pickText()}</code>
          <button type="button" className="kc-btn" onClick={copy}>{copied ? 'copied' : 'copy'}</button>
          <button type="button" className="kc-btn" onClick={() => setPicks([])}>clear</button>
        </div>
      )}
      {loaded && spec.models.some((m) => m.color === 'plddt') && (
        <div className="structure-legend" title="AlphaFold per-residue confidence (pLDDT), read from the B-factor column">
          <span className="kc-card-kind">pLDDT</span>
          {PLDDT_BANDS.map(([label, c]) => <span key={label}><i style={{ background: c }} />{label}</span>)}
        </div>
      )}
      {spec.caption && <figcaption>{spec.caption}</figcaption>}
    </figure>
  );
}

type Series = { label: string; color: string; threshold?: number; values: number[] | null; error?: string };

/**
 * Distances per frame under the trajectory player: one line per distance, a dashed line at its threshold,
 * a cursor at the shown frame. Click or drag to seek. The legend gives the values at the shown frame.
 */
function StripChart({ series, n, frame, label, onSeek }: {
  series: Series[]; n: number; frame: number; label: (k: number) => string; onSeek: (k: number) => void;
}) {
  const W = 1000, H = 90, PAD = 6;
  const ok = series.filter((s) => s.values);
  const all = ok.flatMap((s) => [...s.values!, ...(s.threshold != null ? [s.threshold] : [])]);
  const lo = Math.min(0, ...all), hi = Math.max(...all, 1) * 1.08;
  const x = (k: number) => (n > 1 ? (k / (n - 1)) * W : 0);
  const y = (v: number) => PAD + (1 - (v - lo) / (hi - lo)) * (H - 2 * PAD);
  const seek = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    onSeek(Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width) * (n - 1)))));
  };
  return (
    <div className="structure-strip">
      <div className="structure-strip-plot"
        onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); seek(e); }}
        onPointerMove={(e) => { if (e.buttons) seek(e); }}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-label="Distances per frame">
          {ok.map((s, i) => s.threshold != null && (
            <line key={`t${i}`} x1={0} x2={W} y1={y(s.threshold)} y2={y(s.threshold)} stroke={s.color}
              strokeDasharray="5 5" strokeOpacity={0.55} vectorEffect="non-scaling-stroke" />
          ))}
          {ok.map((s, i) => (
            <polyline key={`s${i}`} fill="none" stroke={s.color} strokeWidth={1.8} vectorEffect="non-scaling-stroke"
              points={s.values!.map((v, k) => `${x(k)},${y(v)}`).join(' ')} />
          ))}
          <line x1={x(frame)} x2={x(frame)} y1={0} y2={H} stroke="#111827" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        </svg>
        <span className="structure-strip-tick top">{hi.toFixed(1)} Å</span>
        <span className="structure-strip-tick bottom">{lo.toFixed(1)} Å</span>
      </div>
      <div className="structure-strip-legend">
        {series.map((s, i) => (
          <span key={i} title={s.error ?? ''}>
            <i style={{ background: s.color }} />{s.label}
            {s.values ? <b> {s.values[frame].toFixed(2)} Å</b> : <em> {s.error}</em>}
            {s.values && s.threshold != null && <em> {s.values[frame] <= s.threshold ? `≤ ${s.threshold}` : `> ${s.threshold}`}</em>}
          </span>
        ))}
        <span className="structure-strip-at">frame {frame}{label(frame)}</span>
      </div>
    </div>
  );
}

const PLDDT_BANDS: [string, string][] = [
  ['> 90', plddtColour(95)], ['70–90', plddtColour(80)], ['50–70', plddtColour(60)], ['< 50', plddtColour(30)],
];

/** Jmol element colours for the non-carbon atoms of highlighted sticks. */
function elementColour(e: string): string {
  return ({ N: '#3050F8', O: '#FF0D0D', S: '#C8A000', P: '#FF8000', H: '#FFFFFF', ZN: '#7D80B0', Zn: '#7D80B0' } as Record<string, string>)[e] ?? '#909090';
}
