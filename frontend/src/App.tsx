import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import Library from "./pages/Library";
import PaperDetail from "./pages/PaperDetail";
import People from "./pages/People";
import Projects from "./pages/Projects";
import Settings from "./pages/Settings";
import BulkImport from "./pages/BulkImport";
import Tools from "./pages/Tools";
import LiteratureSearch from "./pages/LiteratureSearch";
import Discover from "./pages/Discover";
import Blogs from "./pages/Blogs";
import BlogPostDetail from "./pages/BlogPostDetail";
import Teammates from "./pages/Teammates";
import Venues from "./pages/Venues";
import Conferences from "./pages/Conferences";
import MergeManager from "./pages/MergeManager";
import Login from "./pages/Login";
import AdminConsole from "./pages/AdminConsole";
import { SettingsProvider } from "./contexts/SettingsContext";
import { UserProvider } from "./contexts/UserContext";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import ErrorBoundary from "./components/ErrorBoundary";
import Toaster from "./components/Toaster";
import ReferenceImportTracker from "./components/ReferenceImportTracker";
import NavBar from "./components/nav/NavBar";
import { ChatRedirect } from "./components/nav/redirects";
import Cypher from "./pages/Cypher";

// Lazy-load Graph so react-force-graph (WebGL) doesn't run on initial page load
const Graph         = lazy(() => import("./pages/Graph"));
const KnowledgeChat = lazy(() => import("./pages/KnowledgeChat"));
const IdeogramChat  = lazy(() => import("./pages/IdeogramChat"));
const ConceptMap    = lazy(() => import("./pages/ConceptMap"));
// Tokens, reports, suggestions, system health (.specs/013-016)
const Tokens        = lazy(() => import("./pages/Tokens"));
const Reports       = lazy(() => import("./pages/Reports"));
const ReportView    = lazy(() => import("./pages/ReportView"));
const Suggestions   = lazy(() => import("./pages/Suggestions"));
const Health        = lazy(() => import("./pages/Health"));
const TopicMapPage  = lazy(() => import("./pages/TopicMapPage"));

function AppLayout() {
  const { pathname } = useLocation();
  const isKnowledge = pathname === "/knowledge";
  const isLogin = pathname === "/login";

  return (
    <div className="flex flex-col h-screen bg-base">
      {!isLogin && <ReferenceImportTracker />}
      {!isLogin && (
        isKnowledge ? (
          <>
            {/* md and up: navbar is fixed, hidden above the viewport, slides down on hover */}
            <div className="hidden md:block group fixed top-0 left-0 right-0 z-50">
              {/* Invisible trigger strip — always at y=0, captures hover */}
              <div className="h-1.5 w-full bg-violet-400/30 group-hover:opacity-0 transition-opacity" />
              <div className="-translate-y-full group-hover:translate-y-0 group-focus-within:translate-y-0 transition-transform duration-200 shadow-lg">
                <NavBar />
              </div>
            </div>
            {/* Touch screens have no hover: show the normal bar */}
            <div className="md:hidden">
              <NavBar />
            </div>
          </>
        ) : (
          <NavBar />
        )
      )}
      <div className={isKnowledge ? "flex-1 min-h-0 md:h-screen md:flex-none" : "flex-1 min-h-0 overflow-auto"}>
        <ErrorBoundary key={pathname}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/*" element={
            <ProtectedRoute>
              <Routes>
                <Route path="/" element={<Library />} />
                <Route path="/paper/:id" element={<PaperDetail />} />
                <Route path="/people" element={<People />} />
                <Route path="/projects" element={<Projects />} />
                <Route path="/projects/:id/map" element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading concept map…</div>}><ConceptMap /></Suspense>} />
                <Route path="/venues" element={<Venues />} />
                <Route path="/conferences" element={<Conferences />} />
                <Route path="/conferences/:key" element={<Conferences />} />
                <Route path="/graph"   element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading graph…</div>}><Graph /></Suspense>} />
                <Route path="/topic-map" element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading map…</div>}><TopicMapPage /></Suspense>} />
                <Route path="/cypher" element={<Cypher />} />
                <Route path="/knowledge" element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading…</div>}><KnowledgeChat /></Suspense>} />
                <Route path="/chat" element={<ChatRedirect />} />
                <Route path="/tools" element={<Tools />} />
                <Route path="/tools/ideogram" element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading…</div>}><IdeogramChat /></Suspense>} />
                <Route path="/discover" element={<Discover />} />
                <Route path="/literature" element={<LiteratureSearch />} />
                <Route path="/bulk-import" element={<BulkImport />} />
                <Route path="/blogs" element={<Blogs />} />
                <Route path="/teammates" element={<Teammates />} />
                <Route path="/blogs/posts/:postId" element={<BlogPostDetail />} />
                <Route path="/admin" element={<AdminConsole />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/merge" element={<MergeManager />} />
                <Route path="/tokens" element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading…</div>}><Tokens /></Suspense>} />
                <Route path="/reports" element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading…</div>}><Reports /></Suspense>} />
                <Route path="/reports/:id" element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading…</div>}><ReportView /></Suspense>} />
                <Route path="/suggestions" element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading…</div>}><Suggestions /></Suspense>} />
                <Route path="/health" element={<Suspense fallback={<div className="p-8 text-sm text-gray-400">Loading…</div>}><Health /></Suspense>} />
              </Routes>
            </ProtectedRoute>
          } />
        </Routes>
        </ErrorBoundary>
      </div>
        </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <SettingsProvider>
          <UserProvider>
            <AppLayout />
            <Toaster />
          </UserProvider>
        </SettingsProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
