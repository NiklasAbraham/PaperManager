import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../api/client";
import type { Person } from "../types";

interface PersonWithMeta extends Person {
  specialties?: string[];
  paper_count?: number;
}

export default function People() {
  const [people, setPeople] = useState<PersonWithMeta[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    apiFetch<Person[]>("/people").then(setPeople).catch(() => {});
  }, []);

  return (
    <div className="max-w-2xl mx-auto p-6">
      <h1 className="text-lg font-semibold text-gray-900 mb-6">People</h1>
      {people.length === 0 ? (
        <p className="text-sm text-gray-400">No people yet. They're added automatically when you ingest papers.</p>
      ) : (
        <ul className="space-y-3">
          {people.map((p) => (
            <li
              key={p.id}
              onClick={() => navigate(`/?person_id=${p.id}`)}
              className="bg-white border border-gray-200 rounded-lg p-4 cursor-pointer hover:shadow-sm hover:border-violet-300 transition-all"
            >
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-medium text-gray-900 text-sm">{p.name}</p>
                  {p.affiliation && (
                    <p className="text-xs text-gray-400">{p.affiliation}</p>
                  )}
                </div>
                {p.paper_count != null && (
                  <span className="text-xs text-gray-400">{p.paper_count} papers</span>
                )}
              </div>
              {p.specialties && p.specialties.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {p.specialties.map((s) => (
                    <span
                      key={s}
                      onClick={(e) => { e.stopPropagation(); navigate(`/?topic=${s}`); }}
                      className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full hover:bg-blue-100 cursor-pointer"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
