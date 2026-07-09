// Client-side history for Ideogram Chat generations.
//
// Stored in IndexedDB (not localStorage) because each entry holds a full PNG —
// IndexedDB has room for many images and survives reloads. History is
// per-browser; it is a convenience log for recovering / re-exporting past work,
// not authoritative data.

import type { IdeogramCaption } from "../types";

export interface HistoryEntry {
  id: string;
  ts: number; // epoch ms
  prompt: string; // the plain prompt used (may be empty for manual boxes)
  caption: IdeogramCaption; // the full boxes + style state
  imageB64: string; // PNG, base64 (no data: prefix); "" for a boxes-only snapshot
  seed: number;
  preset: string;
  width: number;
  height: number;
  magicModel?: "gemma" | "claude"; // which expander produced the boxes
  autosave?: boolean; // true = the rolling auto-saved working draft (updated in place)
}

const DB_NAME = "papermanager-ideogram";
const STORE = "generations";
const VERSION = 1;

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: "id" });
        store.createIndex("ts", "ts");
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDB().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(STORE, mode);
        const req = fn(t.objectStore(STORE));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
        t.oncomplete = () => db.close();
      }),
  );
}

export async function saveGeneration(entry: HistoryEntry): Promise<void> {
  await tx("readwrite", (s) => s.put(entry));
}

export async function listGenerations(): Promise<HistoryEntry[]> {
  const all = await tx<HistoryEntry[]>("readonly", (s) => s.getAll() as IDBRequest<HistoryEntry[]>);
  return all.sort((a, b) => b.ts - a.ts); // newest first
}

export async function deleteGeneration(id: string): Promise<void> {
  await tx("readwrite", (s) => s.delete(id));
}

export async function clearHistory(): Promise<void> {
  await tx("readwrite", (s) => s.clear());
}

export function newId(): string {
  // crypto.randomUUID is available in all supported browsers; fall back just in case.
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `gen-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
