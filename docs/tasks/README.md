# Build Tasks

Tasks are grouped into phases. Each task has its own file.
Work through them in order — later tasks depend on earlier ones.

## Phases

### Phase 1 — Foundation (no AI, no Drive yet)
| Task | File | Description |
|---|---|---|
| T01 | [t01_scaffolding.md](t01_scaffolding.md) | Create folder structure, venv, install deps |
| T02 | [t02_neo4j_setup.md](t02_neo4j_setup.md) | Neo4j Aura account + connection test |
| T03 | [t03_fastapi_skeleton.md](t03_fastapi_skeleton.md) | FastAPI app boots, health endpoint works |
| T04 | [t04_neo4j_schema.md](t04_neo4j_schema.md) | Create constraints + indexes in Neo4j |

### Phase 2 — Core data (papers, people, tags, projects)
| Task | File | Description |
|---|---|---|
| T05 | [t05_paper_crud.md](t05_paper_crud.md) | Create / read / list papers in Neo4j |
| T06 | [t06_person_crud.md](t06_person_crud.md) | Create / read people + SPECIALIZES_IN |
| T07 | [t07_tags_topics.md](t07_tags_topics.md) | Tags and Topics CRUD + link to papers |
| T08 | [t08_projects.md](t08_projects.md) | Projects CRUD + IN_PROJECT + RELATED_TO |
| T09 | [t09_notes.md](t09_notes.md) | Notes CRUD + @/# mention parser |

### Phase 3 — File handling + AI
| Task | File | Description |
|---|---|---|
| T10 | [t10_pdf_parser.md](t10_pdf_parser.md) | Extract text + metadata from uploaded PDF |
| T11 | [t11_google_drive.md](t11_google_drive.md) | Upload PDF to Drive, store drive_file_id |
| T12 | [t12_claude_summary.md](t12_claude_summary.md) | Auto-summarize paper text via Claude |
| T13 | [t13_paper_ingest.md](t13_paper_ingest.md) | Full ingest pipeline: drop PDF → everything |
| T14 | [t14_chat.md](t14_chat.md) | Chat with a paper via Claude |

### Phase 4 — Search
| Task | File | Description |
|---|---|---|
| T15 | [t15_search.md](t15_search.md) | Full-text search across title, summary, notes |

### Phase 5 — Frontend
| Task | File | Description |
|---|---|---|
| T16 | [t16_frontend_setup.md](t16_frontend_setup.md) | React + Vite + Tailwind, boots locally |
| T17 | [t17_library_page.md](t17_library_page.md) | Paper grid + drag & drop upload |
| T18 | [t18_paper_detail.md](t18_paper_detail.md) | Paper detail page + note editor |
| T19 | [t19_filters.md](t19_filters.md) | Filter by tag, topic, project, person |
| T20 | [t20_chat_ui.md](t20_chat_ui.md) | Chat panel in paper detail |
| T21 | [t21_people_projects.md](t21_people_projects.md) | People and Projects pages |

### Phase 6 — MCP Server
| Task | File | Description |
|---|---|---|
| T22 | [t22_mcp_server.md](t22_mcp_server.md) | MCP server: expose all tools to Claude Code |

### Phase 7 — Discovery & Intelligence
| Task | File | Description | Depends on |
|---|---|---|---|
| T23 | [t23_literature_search.md](t23_literature_search.md) | Discover page: search arXiv/S2/PubMed, add papers in one click | T05, T13, T15 |
| T24 | [t24_related_papers.md](t24_related_papers.md) | "Related" tab on paper detail via S2 recommendations API | T05, T13 |
| T25 | [t25_author_tracking.md](t25_author_tracking.md) | Track authors, nightly S2 check, auto-import new papers | T06, T13 |
| T26 | [t26_knowledge_chat_web_search.md](t26_knowledge_chat_web_search.md) | Knowledge chat gains web search (pre-pass before streaming) | web_search service |
| T27 | [t27_cross_paper_synthesis.md](t27_cross_paper_synthesis.md) | Multi-select papers, ask Claude to compare/synthesise them | T05, T14 |
| T28 | [t28_claim_extractor.md](t28_claim_extractor.md) | Extract claims/findings/hypotheses as Neo4j nodes on upload | T04, T05, T13 |
| T29 | [t29_research_gap_finder.md](t29_research_gap_finder.md) | AI analysis of what's missing from your library on a topic | T05, T15, web_search |
| T30 | [t30_venue_aggregation.md](t30_venue_aggregation.md) | Venues page: group library by conference/journal, filter papers | T05 |

#### Recommended build order for Phase 7
T30 → T24 → T23 → T26 → T27 → T28 → T29 → T25

- **T30** first — pure query, zero new concepts, instant value
- **T24** second — small backend addition, immediate UX win
- **T23** third — biggest UX win, new page, uses existing API services
- **T26** next — one function change, no new endpoints
- **T27 / T28** — richer features, build on solid foundation
- **T29** — highest complexity (web search + library analysis), build last
- **T25** — author tracking can be done any time but stores s2_author_id which T23/T24 benefit from if done first

#### Shared infrastructure (already done before Phase 7)
- `backend/services/web_search.py` — DuckDuckGo search, `WEB_SEARCH_TOOL` schema
- `backend/services/ai.py::_run_claude_with_tools` — agentic Claude tool-use loop
- Both were added alongside the per-paper chat web search feature.

## Status legend
- [ ] not started
- [~] in progress
- [x] done
