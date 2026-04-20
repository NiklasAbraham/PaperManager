import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Library from "./pages/Library";
import PaperDetail from "./pages/PaperDetail";
import People from "./pages/People";
import Projects from "./pages/Projects";
import Settings from "./pages/Settings";
import BulkImport from "./pages/BulkImport";
import { SettingsProvider } from "./contexts/SettingsContext";

// Lazy-load Graph so react-force-graph (WebGL) doesn't run on initial page load
const Graph         = lazy(() => import("./pages/Graph"));
const Cypher        = lazy(() => import("./pages/Cypher"));
const KnowledgeChat = lazy(() => import("./pages/KnowledgeChat"));

function NavBar() {
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
      <NavLink to="/bulk-import" className={cls}>Bulk Import</NavLink>
      <NavLink to="/settings" className={cls}>Settings</NavLink>
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
              <Route path="/bulk-import" element={<BulkImport />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </div>
        </div>
      </SettingsProvider>
    </BrowserRouter>
  );
}
