const DB_NAME = "paper-manager";
const DB_VERSION = 1;
const STORE_NAME = "upload-queue";

export type PersistedQueueItem = {
  id: string;
  fileName: string;
  fileType: string;
  fileBytes: ArrayBuffer;
  meta: unknown;
  status: "ready" | "error";
  error: string | null;
  duplicateId?: string;
  duplicateTitle?: string;
  duplicateHasPdf?: boolean;
  uploadResult?: unknown;
  preprocessKey?: string;
  preprocessStatus?: string;
  analysisKey?: string;
  analysisStatus?: string;
  tagSuggestions?: unknown;
};

function getDb(): Promise<IDBDatabase> {
  if (typeof indexedDB === "undefined") {
    return Promise.reject(new Error("IndexedDB unavailable"));
  }

  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("Failed to open IndexedDB"));
  });
}

export async function persistItem(item: PersistedQueueItem): Promise<void> {
  try {
    const db = await getDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).put(item);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error("Failed to persist item"));
      tx.onabort = () => reject(tx.error ?? new Error("Persist aborted"));
    });
    db.close();
  } catch {
    // no-op fallback when IndexedDB is unavailable
  }
}

export async function removePersistedItem(id: string): Promise<void> {
  try {
    const db = await getDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).delete(id);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error("Failed to remove item"));
      tx.onabort = () => reject(tx.error ?? new Error("Remove aborted"));
    });
    db.close();
  } catch {
    // no-op fallback when IndexedDB is unavailable
  }
}

export async function loadPersistedQueue(): Promise<PersistedQueueItem[]> {
  try {
    const db = await getDb();
    const result = await new Promise<PersistedQueueItem[]>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readonly");
      const req = tx.objectStore(STORE_NAME).getAll();
      req.onsuccess = () => resolve((req.result ?? []) as PersistedQueueItem[]);
      req.onerror = () => reject(req.error ?? new Error("Failed to load queue"));
      tx.onabort = () => reject(tx.error ?? new Error("Load aborted"));
    });
    db.close();
    return result;
  } catch {
    return [];
  }
}

export function fileToBuffer(file: File): Promise<ArrayBuffer> {
  return file.arrayBuffer();
}

export function bufferToFile(bytes: ArrayBuffer, fileName: string, fileType: string): File {
  return new File([bytes], fileName, { type: fileType });
}
