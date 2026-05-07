import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { listVenues, getVenuePapers } from "../api/client";
import type { VenueOut, Paper } from "../types";
import PaperCard from "../components/PaperCard";

// Heuristic to detect venue type
function detectVenueType(name: string): "Conference" | "Journal" | "Preprint" {
  const lowerName = name.toLowerCase();
  
  if (lowerName.includes("arxiv")) return "Preprint";
  
  const conferenceKeywords = [
    "neurips", "icml", "iclr", "cvpr", "eccv", "iccv", "aaai", "ijcai",
    "acl", "emnlp", "naacl", "coling", "sigir", "kdd", "www", "icde",
    "vldb", "sigmod", "chi", "uist", "siggraph", "icra", "iros",
    "conference", "workshop", "symposium", "proceedings"
  ];
  
  if (conferenceKeywords.some(k => lowerName.includes(k))) {
    return "Conference";
  }
  
  return "Journal";
}

const TYPE_COLORS = {
  Conference: "bg-blue-100 text-blue-700",
  Journal: "bg-green-100 text-green-700",
  Preprint: "bg-yellow-100 text-yellow-700",
};

export default function Venues() {
  const [searchParams] = useSearchParams();
  const [venues, setVenues] = useState<VenueOut[]>([]);
  const [filteredVenues, setFilteredVenues] = useState<VenueOut[]>([]);
  const [filter, setFilter] = useState("");
  const [sortBy, setSortBy] = useState<"count" | "name" | "recent">("count");
  const [loading, setLoading] = useState(true);
  const [selectedVenue, setSelectedVenue] = useState<string | null>(null);
  const [venuePapers, setVenuePapers] = useState<Paper[]>([]);
  const [loadingPapers, setLoadingPapers] = useState(false);

  useEffect(() => {
    loadVenues();
  }, []);

  // Auto-select venue from URL (only run once when venues are loaded)
  useEffect(() => {
    const selected = searchParams.get("selected");
    if (selected && venues.length > 0 && !selectedVenue) {
      openVenue(selected);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("selected"), venues.length]);

  useEffect(() => {
    // Apply filter and sort
    let result = [...venues];
    
    if (filter) {
      result = result.filter(v => v.name.toLowerCase().includes(filter.toLowerCase()));
    }
    
    // Sort
    result.sort((a, b) => {
      switch (sortBy) {
        case "count":
          return b.count - a.count;
        case "name":
          return a.name.localeCompare(b.name);
        case "recent":
          const maxYearA = Math.max(...a.years);
          const maxYearB = Math.max(...b.years);
          return maxYearB - maxYearA;
        default:
          return 0;
      }
    });
    
    setFilteredVenues(result);
  }, [venues, filter, sortBy]);

  const loadVenues = async () => {
    setLoading(true);
    try {
      const data = await listVenues();
      setVenues(data);
    } catch (err) {
      console.error("Failed to load venues:", err);
    } finally {
      setLoading(false);
    }
  };

  const openVenue = async (venueName: string) => {
    setSelectedVenue(venueName);
    setLoadingPapers(true);
    try {
      const papers = await getVenuePapers(venueName);
      setVenuePapers(papers);
    } catch (err) {
      console.error("Failed to load venue papers:", err);
      setVenuePapers([]);
    } finally {
      setLoadingPapers(false);
    }
  };

  const closePanel = () => {
    setSelectedVenue(null);
    setVenuePapers([]);
  };

  const getYearRange = (years: number[]) => {
    if (years.length === 0) return "—";
    const min = Math.min(...years);
    const max = Math.max(...years);
    return min === max ? `${min}` : `${min}–${max}`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-500">Loading venues...</div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-4 border-b border-gray-200 bg-white">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-bold text-gray-800">Venues</h1>
          <div className="text-sm text-gray-600">
            {venues.length} venue{venues.length !== 1 ? "s" : ""} • {venues.reduce((sum, v) => sum + v.count, 0)} papers
          </div>
        </div>
        
        <div className="flex gap-4">
          <input
            type="text"
            placeholder="Search venues..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-violet-500 focus:border-transparent"
          />
          
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "count" | "name" | "recent")}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-violet-500 focus:border-transparent"
          >
            <option value="count">Sort by: Paper count</option>
            <option value="name">Sort by: Venue name (A–Z)</option>
            <option value="recent">Sort by: Most recent</option>
          </select>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {filteredVenues.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            {filter ? "No venues match your search" : "No venues found in your library"}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredVenues.map((venue) => {
              const venueType = detectVenueType(venue.name);
              return (
                <div
                  key={venue.name}
                  onClick={() => openVenue(venue.name)}
                  className="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-lg transition-shadow cursor-pointer"
                >
                  <div className="flex items-start justify-between mb-2">
                    <h3 className="font-semibold text-gray-800 text-sm line-clamp-2 flex-1">
                      {venue.name}
                    </h3>
                    <span className={`ml-2 px-2 py-0.5 text-xs font-medium rounded ${TYPE_COLORS[venueType]} whitespace-nowrap`}>
                      {venueType}
                    </span>
                  </div>
                  
                  <div className="space-y-1 text-sm text-gray-600">
                    <div>
                      <span className="font-medium">{venue.count}</span> paper{venue.count !== 1 ? "s" : ""}
                    </div>
                    <div className="text-xs text-gray-500">
                      {getYearRange(venue.years)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Venue Papers Panel */}
      {selectedVenue && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-6xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <h2 className="text-xl font-semibold text-gray-800">{selectedVenue}</h2>
              <button
                onClick={closePanel}
                className="text-gray-400 hover:text-gray-600 transition-colors"
                title="Close"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-6">
              {loadingPapers ? (
                <div className="text-center py-8">
                  <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-violet-600 mb-4"></div>
                  <p className="text-gray-600">Loading papers...</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {venuePapers.map((paper) => (
                    <PaperCard
                      key={paper.id}
                      paper={paper}
                      showAbstract={false}
                      onDeleted={() => {
                        setVenuePapers(venuePapers.filter(p => p.id !== paper.id));
                      }}
                      onUpdated={(updated) => {
                        setVenuePapers(venuePapers.map(p => p.id === updated.id ? updated : p));
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
