import { createContext, useContext, useState, type ReactNode } from "react";

export interface AppSettings {
  // Library
  defaultView: "grid" | "list";
  defaultSort: "date_desc" | "date_asc" | "year_desc" | "year_asc" | "title_asc";
  showAbstractPreview: boolean;
  papersPerPage: 20 | 50 | 100 | 0; // 0 = all

  // Graph
  defaultGraphMode: "full" | "papers";
  graphNodeSize: number;
  graphShowNodeLabels: boolean;
  graphShowEdgeLabels: boolean;
}

export const SETTINGS_DEFAULTS: AppSettings = {
  defaultView: "grid",
  defaultSort: "date_desc",
  showAbstractPreview: true,
  papersPerPage: 50,
  defaultGraphMode: "full",
  graphNodeSize: 16,
  graphShowNodeLabels: true,
  graphShowEdgeLabels: true,
};

const STORAGE_KEY = "paperManager:settings";

function loadFromStorage(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return SETTINGS_DEFAULTS;
    return { ...SETTINGS_DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return SETTINGS_DEFAULTS;
  }
}

function saveToStorage(s: AppSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

interface SettingsContextValue {
  settings: AppSettings;
  update: (patch: Partial<AppSettings>) => void;
  reset: () => void;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(loadFromStorage);

  const update = (patch: Partial<AppSettings>) => {
    setSettings(prev => {
      const next = { ...prev, ...patch };
      saveToStorage(next);
      return next;
    });
  };

  const reset = () => {
    localStorage.removeItem(STORAGE_KEY);
    setSettings(SETTINGS_DEFAULTS);
  };

  return (
    <SettingsContext.Provider value={{ settings, update, reset }}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useAppSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useAppSettings must be used inside SettingsProvider");
  return ctx;
}
