// Ported from the thesis desk's structure/viewer.ts (keep in sync); coordinates come from the backend's proxy or inline, never from a file path.
import { apiUrl } from '../../../api/client';
import type { ModelSpec, Resi, Selection, StructureSpec } from './types';

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Atom3D = Record<string, any> & {
  x: number; y: number; z: number; chain: string; resi: number | string; resn: string; atom: string; elem: string;
  hetflag: boolean; b: number;
};

/** 3Dmol.js is vendored in public/vendor and loaded on the first structure, not bundled. */
let lib: Promise<any> | null = null;
export function load3Dmol(): Promise<any> {
  const w = window as any;
  if (w.$3Dmol) return Promise.resolve(w.$3Dmol);
  lib ??= new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = '/vendor/3dmol/3Dmol-min.js';
    s.onload = () => (w.$3Dmol ? resolve(w.$3Dmol) : reject(new Error('3Dmol did not load')));
    s.onerror = () => { lib = null; reject(new Error('could not load /vendor/3dmol/3Dmol-min.js')); };
    document.head.appendChild(s);
  });
  return lib;
}

export type CoordFormat = 'pdb' | 'cif' | 'sdf' | 'mol2';
export type Coordinates = { name: string; format: CoordFormat; data: string };

/** The request a model needs (`pdb=6VXX`, `ccd=ATP`, ...), or null for inline data. */
export function sourceQuery(m: ModelSpec): string | null {
  if (m.data != null && !m.pdb && !m.afdb && !m.ccd && m.pubchem == null) return null;
  if (m.pdb) return `pdb=${encodeURIComponent(m.pdb)}`;
  if (m.afdb) return `afdb=${encodeURIComponent(m.afdb)}`;
  if (m.ccd) return `ccd=${encodeURIComponent(String(m.ccd).toUpperCase())}`;
  if (m.pubchem != null && String(m.pubchem) !== '') return `pubchem=${encodeURIComponent(String(m.pubchem))}`;
  return null;
}

/** A short name for the model's source, for "loading ..." lines and chips: 6VXX, AF-P69905, ATP, CID 2244, inline. */
export function sourceName(m: ModelSpec): string {
  if (m.pdb) return m.pdb;
  if (m.afdb) return `AF-${m.afdb}`;
  if (m.ccd) return String(m.ccd).toUpperCase();
  if (m.pubchem != null && String(m.pubchem) !== '') return `CID ${m.pubchem}`;
  return 'inline';
}

/** The format of inline coordinates when the spec does not say: sniffed from the text, PDB otherwise. */
export function sniffFormat(data: string): CoordFormat {
  if (/@<TRIPOS>MOLECULE/.test(data)) return 'mol2';
  if (/V[23]000\b|^\$\$\$\$/m.test(data)) return 'sdf';
  if (/^data_|^_atom_site\./m.test(data)) return 'cif';
  return 'pdb';
}

const fetched = new Map<string, Promise<Coordinates>>();
export function fetchCoordinates(m: ModelSpec): Promise<Coordinates> {
  const q = sourceQuery(m);
  if (q === null) {
    if (typeof m.data !== 'string' || !m.data.trim()) return Promise.reject(new Error('model has no coordinates'));
    return Promise.resolve({ name: sourceName(m), format: m.format ?? sniffFormat(m.data), data: m.data });
  }
  let p = fetched.get(q);
  if (!p) {
    p = fetch(apiUrl(`/knowledge-chat/structures?${q}`), { credentials: 'include' }).then(async (r) => {
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail ?? `HTTP ${r.status}`);
      return body as Coordinates;
    });
    p.catch(() => fetched.delete(q));
    fetched.set(q, p);
  }
  return p;
}

/* ---------------------------------------------------------------- frames */

/**
 * A multi-model PDB read as a trajectory: the first model's text (all 3Dmol has to parse) and every
 * model's coordinates, indexed by atom serial so they can be written into 3Dmol's atoms of frame 0.
 * null when the file has fewer than two models.
 */
export type Frames = { first: string; index: Map<number, number>; xyz: Float32Array[]; uneven: boolean };
export function pdbFrames(data: string): Frames | null {
  if ((data.match(/^MODEL /gm) ?? []).length < 2) return null;
  const lines = data.split('\n');
  const index = new Map<number, number>();
  const xyz: Float32Array[] = [];
  const firstLines: string[] = [];
  let cur: number[] = [];
  let n = 0, inFirst = true, uneven = false;
  for (const l of lines) {
    const rec = l.slice(0, 6);
    if (rec === 'ATOM  ' || rec === 'HETATM') {
      if (inFirst) index.set(parseInt(l.slice(6, 11), 10), n++);
      cur.push(parseFloat(l.slice(30, 38)), parseFloat(l.slice(38, 46)), parseFloat(l.slice(46, 54)));
    } else if (rec === 'ENDMDL') {
      if (cur.length) {
        if (!inFirst && cur.length !== 3 * n) uneven = true;
        xyz.push(Float32Array.from(cur));
      }
      cur = [];
      if (inFirst) { firstLines.push(l); inFirst = false; }
      continue;
    }
    if (inFirst) firstLines.push(l);
  }
  if (cur.length) xyz.push(Float32Array.from(cur));
  return xyz.length >= 2 ? { first: firstLines.join('\n') + '\nEND\n', index, xyz, uneven } : null;
}

/* ------------------------------------------------------------------ spec */

const PDB_ID = /^[0-9][A-Za-z0-9]{3}$/;
const AF_ID = /^AF-([A-Z0-9]{6,10})(?:-F1)?$/i;

/**
 * A small molecule (SDF / MOL / MOL2) has no residues, chains or het records, so 3Dmol leaves its atoms
 * unlabelled. Make it a ligand like a HETATM residue in a PDB: chain L, residue 1, the residue name
 * from the file's title when it is a 1-3 character code (else LIG), atoms named element + 1-based index
 * (C1, O13, as RDKit writes them to PDB), so highlights by resn / hetero / atom and clicks work as usual.
 * (Ported from the desk's viewer.ts.)
 */
export function asLigand(atoms: Atom3D[], c: Coordinates) {
  if (c.format !== 'sdf' && c.format !== 'mol2') return;
  const title = (c.format === 'sdf' ? c.data.split('\n')[0] : c.data.split('@<TRIPOS>MOLECULE')[1]?.split('\n')[1] ?? '').trim();
  const resn = /^[A-Za-z0-9]{1,3}$/.test(title) ? title.toUpperCase() : 'LIG';
  atoms.forEach((a, i) => {
    a.hetflag = true; a.chain = 'L'; a.resi = 1; a.resn = resn;
    if (c.format === 'sdf' || !a.atom) a.atom = `${a.elem}${i + 1}`;
  });
}

/**
 * The block's text as a spec: `{ spec }`; `{ error }` when it is JSON but not a usable spec;
 * null while it is still streaming (incomplete JSON) or not a spec at all. A bare PDB id and
 * `AF-<UniProt>` (AlphaFold DB) are shorthand; anything else is JSON (see types.ts).
 */
export function parseSource(raw: string): { spec: StructureSpec } | { error: string } | null {
  const t = raw.trim().replace(/^`|`$/g, '');
  if (t.startsWith('{')) {
    let d: unknown;
    try { d = JSON.parse(t); } catch { return null; }
    try { return { spec: normalise(d) }; } catch (e) { return { error: e instanceof Error ? e.message : 'not a structure spec' }; }
  }
  if (PDB_ID.test(t)) return { spec: { models: [{ pdb: t.toUpperCase() }] } };
  const af = AF_ID.exec(t);
  if (af) return { spec: { models: [{ afdb: af[1].toUpperCase(), color: 'plddt' }] } };
  return null;
}

export function normalise(d: any): StructureSpec {
  if (!d || typeof d !== 'object') throw new Error('not a structure spec');
  const hasSource = (m: any) => !!m && typeof m === 'object' && !!(m.pdb || m.afdb || m.ccd || (m.pubchem != null && m.pubchem !== '') || (typeof m.data === 'string' && m.data.trim()));
  if (Array.isArray(d.models) && d.models.length) {
    const bad = d.models.findIndex((m: any) => !hasSource(m));
    if (bad >= 0) throw new Error(`model ${bad} needs one of "pdb", "afdb", "ccd", "pubchem" or "data"`);
    return d as StructureSpec;
  }
  if (hasSource(d)) {
    const { title, caption, highlights, focus, ligands, dim, representation, height, distances, ...model } = d;
    return { title, caption, highlights, focus, ligands, dim, representation, height, distances, models: [model] };
  }
  throw new Error('a structure spec needs "models" (or one of "pdb" / "afdb" / "ccd" / "pubchem" / "data")');
}

/* ------------------------------------------------------------- selection */

export function resiSet(r: Resi | undefined): ((n: number) => boolean) | null {
  if (r == null) return null;
  const ranges: [number, number][] = [];
  for (const part of (Array.isArray(r) ? r : [r]).flatMap((x) => String(x).split(','))) {
    const m = /^\s*(-?\d+)\s*(?:(?:-|–|\.\.)\s*(-?\d+))?\s*$/.exec(part);
    if (m) ranges.push([Number(m[1]), Number(m[2] ?? m[1])]);
  }
  return (n) => ranges.some(([a, b]) => n >= a && n <= b);
}

const asList = (v: string | string[] | undefined) => (v == null ? null : Array.isArray(v) ? v : [v]);

/** A predicate over atoms of model `mi` for a selection; built once per selection. */
export function matcher(sel: Selection, mi: number): (a: Atom3D) => boolean {
  if (sel.model != null && sel.model !== mi) return () => false;
  const chains = asList(sel.chain), resn = asList(sel.resn)?.map((s) => s.toUpperCase()), names = asList(sel.atom);
  const resi = resiSet(sel.resi);
  return (a) =>
    (!chains || chains.includes(a.chain)) &&
    (!resi || resi(Number(a.resi))) &&
    (!resn || resn.includes(String(a.resn).toUpperCase())) &&
    (!names || names.includes(a.atom)) &&
    (sel.hetero == null || a.hetflag === sel.hetero);
}

export const WATER = new Set(['HOH', 'WAT', 'DOD', 'H2O']);

/* --------------------------------------------------------------- colours */

/**
 * Colours by role, from PaperManager's violet palette (the concept graphs' COLORS and the
 * Tailwind accents), so structure cards sit with the rest of the app.
 */
export const ROLE: Record<string, string> = {
  ink: '#111827', accent: '#7c3aed', violet: '#7c3aed', violetL: '#c4b5fd', blue: '#0284c7', blueL: '#7dd3fc',
  warm: '#d97706', warmL: '#fcd34d', green: '#059669', greenL: '#6ee7b7', rose: '#e11d48', indigo: '#5b66f1',
  grey: '#9ca3af', greyD: '#6b7280', pale: '#e5e7eb', muted: '#6b7280',
  heavy: '#7c3aed', light: '#c4b5fd', cdr: '#d97706', antigen: '#0284c7', paratope: '#d97706', epitope: '#e11d48',
  antibody: '#7c3aed', ligand: '#e11d48', scaffold: '#7c3aed', context: '#9ca3af', reference: '#9ca3af', surface: '#e5e7eb',
};
/** Chains in order of appearance: violet first, then the app's other accents. */
export const CHAIN_CYCLE = ['#7c3aed', '#0284c7', '#d97706', '#059669', '#e11d48', '#5b66f1', '#c4b5fd', '#7dd3fc'];
export const DIM = '#e5e7eb';
export const PICK = '#e11d48';

export const colour = (c: string | undefined, fallback: string) => (c ? ROLE[c] ?? c : fallback);

/** AlphaFold's pLDDT bands, read from the B-factor column. */
export function plddtColour(b: number): string {
  const v = b <= 1 ? b * 100 : b;
  return v >= 90 ? '#0053D6' : v >= 70 ? '#65CBF3' : v >= 50 ? '#FFDB13' : '#FF7D45';
}

/* ---------------------------------------------------------- superposition */

/** Rigid fit of P onto Q (Horn's quaternion method); returns the map and the RMSD after fitting. */
export function kabsch(P: number[][], Q: number[][]): { apply: (v: number[]) => number[]; rmsd: number } {
  const n = P.length;
  const mean = (X: number[][]) => [0, 1, 2].map((k) => X.reduce((s, v) => s + v[k], 0) / n);
  const pc = mean(P), qc = mean(Q);
  const S = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < n; i++) for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) S[a][b] += (P[i][a] - pc[a]) * (Q[i][b] - qc[b]);
  const [[xx, xy, xz], [yx, yy, yz], [zx, zy, zz]] = S;
  const N = [
    [xx + yy + zz, yz - zy, zx - xz, xy - yx],
    [yz - zy, xx - yy - zz, xy + yx, zx + xz],
    [zx - xz, xy + yx, -xx + yy - zz, yz + zy],
    [xy - yx, zx + xz, yz + zy, -xx - yy + zz],
  ];
  const [w, x, y, z] = topEigenvector(N);
  const R = [
    [w * w + x * x - y * y - z * z, 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), w * w - x * x + y * y - z * z, 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), w * w - x * x - y * y + z * z],
  ];
  const apply = (v: number[]) => {
    const d = [v[0] - pc[0], v[1] - pc[1], v[2] - pc[2]];
    return [0, 1, 2].map((r) => R[r][0] * d[0] + R[r][1] * d[1] + R[r][2] * d[2] + qc[r]);
  };
  let ss = 0;
  for (let i = 0; i < n; i++) { const a = apply(P[i]); ss += (a[0] - Q[i][0]) ** 2 + (a[1] - Q[i][1]) ** 2 + (a[2] - Q[i][2]) ** 2; }
  return { apply, rmsd: Math.sqrt(ss / n) };
}

/** Eigenvector of the largest eigenvalue of a symmetric 4×4 matrix (cyclic Jacobi). */
function topEigenvector(A0: number[][]): number[] {
  const A = A0.map((r) => r.slice());
  const V: number[][] = [0, 1, 2, 3].map((i) => [0, 1, 2, 3].map((j) => (i === j ? 1 : 0)));
  for (let sweep = 0; sweep < 60; sweep++) {
    let off = 0;
    for (let p = 0; p < 4; p++) for (let q = p + 1; q < 4; q++) off += A[p][q] ** 2;
    if (off < 1e-18) break;
    for (let p = 0; p < 4; p++) for (let q = p + 1; q < 4; q++) {
      if (Math.abs(A[p][q]) < 1e-15) continue;
      const th = (A[q][q] - A[p][p]) / (2 * A[p][q]);
      const t = Math.sign(th || 1) / (Math.abs(th) + Math.sqrt(th * th + 1));
      const c = 1 / Math.sqrt(t * t + 1), s = t * c;
      for (let k = 0; k < 4; k++) {
        const akp = A[k][p], akq = A[k][q];
        A[k][p] = c * akp - s * akq; A[k][q] = s * akp + c * akq;
      }
      for (let k = 0; k < 4; k++) {
        const apk = A[p][k], aqk = A[q][k];
        A[p][k] = c * apk - s * aqk; A[q][k] = s * apk + c * aqk;
      }
      for (let k = 0; k < 4; k++) {
        const vkp = V[k][p], vkq = V[k][q];
        V[k][p] = c * vkp - s * vkq; V[k][q] = s * vkp + c * vkq;
      }
    }
  }
  let best = 0;
  for (let i = 1; i < 4; i++) if (A[i][i] > A[best][best]) best = i;
  return [V[0][best], V[1][best], V[2][best], V[3][best]];
}

/** Superpose `atoms` (model mi) on `target` in place by Cα pairs; returns what was done. */
export function superpose(atoms: Atom3D[], target: Atom3D[], a: NonNullable<ModelSpec['align']>): { n: number; rmsd: number } | { error: string } {
  const inFit = resiSet(a.resi), off = a.offset ?? 0;
  const ca = (list: Atom3D[], chain: string | undefined) => {
    const m = new Map<number, Atom3D>();
    for (const x of list) if (x.atom === 'CA' && !x.hetflag && (!chain || x.chain === chain)) m.set(Number(x.resi), x);
    return m;
  };
  const mine = ca(atoms, a.chain), theirs = ca(target, a.toChain ?? a.chain);
  const P: number[][] = [], Q: number[][] = [];
  for (const [r, x] of mine) {
    const t = theirs.get(r + off);
    if (t && (!inFit || inFit(r + off))) { P.push([x.x, x.y, x.z]); Q.push([t.x, t.y, t.z]); }
  }
  if (P.length < 3) return { error: `only ${P.length} paired Cα` };
  const fit = kabsch(P, Q);
  for (const x of atoms) { const [nx, ny, nz] = fit.apply([x.x, x.y, x.z]); x.x = nx; x.y = ny; x.z = nz; }
  return { n: P.length, rmsd: fit.rmsd };
}

export const THREE_TO_ONE: Record<string, string> = {
  ALA: 'A', ARG: 'R', ASN: 'N', ASP: 'D', CYS: 'C', GLN: 'Q', GLU: 'E', GLY: 'G', HIS: 'H', ILE: 'I',
  LEU: 'L', LYS: 'K', MET: 'M', PHE: 'F', PRO: 'P', SER: 'S', THR: 'T', TRP: 'W', TYR: 'Y', VAL: 'V',
};
