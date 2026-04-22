import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Library from "./pages/Library";
import PaperDetail from "./pages/PaperDetail";
import People from "./pages/People";
import Projects from "./pages/Projects";
import Settings from "./pages/Settings";
import BulkImport from "./pages/BulkImport";
import LiteratureSearch from "./pages/LiteratureSearch";
import { SettingsProvider, useAppSettings } from "./contexts/SettingsContext";

// Lazy-load Graph so react-force-graph (WebGL) doesn't run on initial page load
const Graph         = lazy(() => import("./pages/Graph"));
const Cypher        = lazy(() => import("./pages/Cypher"));
const KnowledgeChat = lazy(() => import("./pages/KnowledgeChat"));

function NavBar() {
  const { settings, update } = useAppSettings();
  const cls = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-2 rounded text-sm font-medium transition-colors ${
      isActive
        ? "bg-violet-100 text-violet-700"
        : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
    }`;
  return (
    <nav className="border-b border-gray-200 bg-white px-6 py-3 flex items-center gap-2">
      <span className="font-semibold text-gray-900 mr-4">PaperManager</span>
      <NavLink to="/" end className={cls}>Library</NavLink>
      <NavLink to="/people" className={cls}>People</NavLink>
      <NavLink to="/projects" className={cls}>Projects</NavLink>
      <NavLink to="/graph" className={cls}>Graph</NavLink>
      <NavLink to="/cypher" className={cls}>Cypher</NavLink>
      <NavLink to="/knowledge" className={cls}>Knowledge</NavLink>
      <NavLink to="/literature" className={cls}>Literature</NavLink>
      <NavLink to="/bulk-import" className={cls}>Bulk Import</NavLink>
      <NavLink to="/settings" className={cls}>Settings</NavLink>
      <div className="ml-auto">
        <button
          onClick={() => update({ debugMode: !settings.debugMode })}
          title={settings.debugMode ? "Debug mode ON — click to disable" : "Debug mode OFF — click to enable"}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold border transition-colors ${
            settings.debugMode
              ? "bg-amber-500 border-amber-500 text-white"
              : "bg-white border-gray-300 text-gray-400 hover:border-gray-400 hover:text-gray-600"
          }`}
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
            <path fillRule="evenodd" d="M6.28 5.22a.75.75 0 0 1 0 1.06L2.56 10l3.72 3.72a.75.75 0 0 1-1.06 1.06L1 10.53a.75.75 0 0 1 0-1.06l4.22-4.25a.75.75 0 0 1 1.06 0Zm7.44 0a.75.75 0 0 1 1.06 0l4.22 4.22a.75.75 0 0 1 0 1.06l-4.22 4.22a.75.75 0 0 1-1.06-1.06L17.44 10l-3.72-3.72a.75.75 0 0 1 0-1.06ZM11.377 2.011a.75.75 0 0 1 .612.867l-2.5 14.5a.75.75 0 0 1-1.478-.255l2.5-14.5a.75.75 0 0 1 .866-.612Z" clipRule="evenodd" />
          </svg>
          {settings.debugMode && <span>DEBUG</span>}
        </button>
      </div>
    </nav>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <SettingsProvider>
        <div className="flex flex-col h-screen bg-gray-50">
          <NavBar />
          <div className="flex-1 min-h-0 overflow-auto">
            <Routes>
              <Route path="/" element={<Library />} />
              <Route path="/paper/:id" element={<PaperDetail />} />
              <Route path="/people" element={<People />} />
              <Route path="/projects" element={<Projects />} />
              <Route path="/graph"   element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading graph…</div>}><Graph /></Suspense>} />
              <Route path="/cypher" element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading…</div>}><Cypher /></Suspense>} />
              <Route path="/knowledge" element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading…</div>}><KnowledgeChat /></Suspense>} />
              <Route path="/literature" element={<LiteratureSearch />} />
              <Route path="/bulk-import" element={<BulkImport />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </div>
        </div>
      </SettingsProvider>
    </BrowserRouter>
  );
}
