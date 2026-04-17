# T21 — People and Projects Pages

**Phase:** 5 — Frontend
**Depends on:** T06, T08, T16
**Touches:** `frontend/src/pages/People.tsx`, `frontend/src/pages/Projects.tsx`

## Goal
Dedicated pages to browse people and projects.

---

## Projects page (/projects)

### Layout
```
┌──────────────────────────────────────────────┐
│ Projects                          [+ New]    │
├──────────────────────────────────────────────┤
│ ● PhD Thesis          (active)  8 papers     │
│   Collaboration with TU Berlin ↔             │
│                                              │
│ ● Collaboration TU Berlin (active) 4 papers  │
│   Related: PhD Thesis ↔                      │
│                                              │
│ ● Literature Review 2024 (done) 12 papers    │
└──────────────────────────────────────────────┘
```

- Click project → Library filtered by that project
- Related projects shown as links
- Status badge (active / paused / done)
- [+ New] button → inline form to create project

---

## People page (/people)

### Layout
```
┌──────────────────────────────────────────────┐
│ People                                       │
├──────────────────────────────────────────────┤
│ Jan Müller                                   │
│ TU Berlin                                    │
│ Specialties: transformers, NLP               │
│ 3 papers (author), 2 papers (working_on)     │
│                                              │
│ Nele Schmidt                                 │
│ KU Leuven                                    │
│ Specialties: graph neural networks           │
│ feedback_needed on 1 paper                   │
└──────────────────────────────────────────────┘
```

- Shows person's specialties as topic chips
- Shows paper count by relationship type
- Click person → Library filtered by that person
- Click on a specialty topic → Library filtered by topic

---

## Done when
- [ ] Projects page lists all projects with paper counts
- [ ] Click project → library filtered correctly
- [ ] New project form works
- [ ] People page lists all people with specialties and paper counts
- [ ] Click person → library filtered correctly

## Tests
- Manual: create a project, add papers, visit projects page → count correct
- Manual: person with INVOLVES role → correct role shown
