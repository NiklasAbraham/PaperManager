# Library dashboard and topic map — developer context

The unfiltered Library page opens with a stats strip and a 2D map of every embedded paper
("topic map"), clustered and labelled. Two endpoints on `backend/routers/stats.py` (prefix `/stats`).
Nothing is computed on the request path (except the first attribute read query).

## Shape

```
backend/services/topic_map.py            layout, clustering, labels, caching, payload (pure functions + cache)
backend/routers/stats.py                 GET /stats/dashboard, GET /stats/topic-map
backend/scripts/topic_map_bench.py       bench + PNG check of the layout (EMB_DIR, --attrs, --png, --seeded, --limit)
frontend/src/components/dashboard/       Dashboard.tsx (variants), TopicMap.tsx (canvas), Pieces.tsx (stat tiles),
                                         useDashboardData.ts, api.ts, helpers.ts
```

"Library papers" = papers not tagged `from-references`; "reference papers" = tagged `from-references`.
Both honour `paper_visibility_clause` / `project_visibility_clause` (`db.queries.visibility`).

## GET /stats/dashboard

`total`, `references`, `added_7d`, `added_30d`, `added_weekly` (exactly 12 ISO weeks, Monday start,
oldest first, zeros filled), `reading` (`unread|reading|read` counts; null status = unread),
`top_topics` and `top_tags` (≤ 8; system tags such as `from-references` excluded), `projects` (visible,
≤ 6, most recent `last_added` first, each with `count`, `read`, `reading`).

## GET /stats/topic-map

Query `refs` (default 1; `refs=0` drops reference points: smaller payload, the frontend asks for it first).

```
{state: "ready"|"building"|"empty", computed_at, seconds, n, stale,
 points:   [{id, x, y, c, t, r, p, topic}],   x,y in [0,1] (4 decimals), c cluster, r=1 reference, p project indices
 clusters: [{id, label, color, x, y, size, library, muted}],
 projects: [{id, name, color, count}]}        visible only; projects with no papers on the map omitted
```

States: `building` = no layout yet (first request after install / update starts the build; the frontend polls every 4 s,
about two minutes); `empty` = no embedded papers (the dashboard hides the map).

## Layout algorithm

Input is the semantic-search index (`emb.npy` + `meta.json` from `services.library_search.semantic`), so every
paper with an embedding is on the map, no second embedding pass.

1. numpy-only UMAP-style layout: exact kNN (k = 15, chunked), fuzzy-graph weights, stochastic attract/repel
   optimisation (UMAP curve a=1.577, b=0.895), PCA init; 200 epochs fresh, 60 when seeded. `normalize_xy` to [0,1].
2. Clusters: deterministic k-means++ on the 2D layout, `k = clamp(round(sqrt(n)/5), 3, 8)`, ids ordered by size.
3. Labels (`label_clusters_info`): candidates are topics, tags, title bigrams and unigrams, scored by
   coverage x distinctiveness; topics/tags must cover ≥ 10 % of the cluster; tags in > 40 % of papers and system
   tags are banned; weak words ("model", "learning"...) are down-weighted; labels in a map are unique.
4. Junk: `junk_title` flags author lists, "et al." tails, statements ("Competing interests"), bare names. A
   cluster with ≥ 50 % junk titles is `muted`: label "Unparsed references", colour `#b4b2a9`, no palette slot
   (the others take the palette `#2a78d6 #eb6834 #1baf7a #eda100 #e87ba4 #008300 #6250d6 #e34948` by size rank).
5. Two label sets: admins see labels from all papers; non-admins labels from papers that are in no project only, so
   a label never leaks a hidden paper. Project colours are the same 8 hues offset by 3, stable per project
   (sorted id order).

## Caching and rebuilds

- `layout.json` under `TOPIC_MAP_DIR` (else `/data/topic_map`, else a temp dir). Loaded once per process.
- Stale = the layout's recorded embedding fingerprint differs from `emb.npy` / `meta.json`. The layout is rebuilt at
  most every `TOPIC_MAP_MIN_INTERVAL` s (default 1800) unless none exists or the paper count changed by > 5 %;
  meanwhile the old layout is served with `stale: true`.
- Layout builds and `derive` (cluster assignment + labels, ~7 s on 10k papers) run in a child process: a lazily
  created one-worker spawn `ProcessPoolExecutor`, `os.nice(10)`, one job at a time, so they never compete with
  requests for the GIL. A done-callback updates the cache. If the pool cannot start, a thread is used (warning logged).
  A failed job is not retried for 60 s.
- The child persists `layout.json` and `derived.json` (per-paper records + clusters, a few MB), so a restarted backend
  serves the map at once.
- Rebuilds are seeded (`seed_init`): papers already in the previous layout keep their coordinates as the start, new
  ones are placed near their neighbours, 60 epochs, so the map does not jump when a paper is added.
- Paper attributes (title, topics, tags, projects, created) come from one read query, refreshed in a background thread
  after `ATTR_TTL` = 120 s; labels are re-derived only when the attributes' content hash changed.
- The request path never derives: it serves the last derived result (even from older attributes) and returns
  `state: "building"` only when nothing has been derived yet.
- Per request only `build_payload` runs: drop hidden papers and projects, optionally drop references.

## Frontend

`Library.tsx` renders `<Dashboard variant onFilter title>` only on the unfiltered page (no query, no filters); with a
filter or query the normal result list shows. Variant from `?dash=` (`parseVariant`): `a` hero card, stats
left and map right (stats strip on top and scrolling on phones), `b` (default, chosen by Niklas 12 Nov 2026) stat tiles above a collapsible map card,
`c` stat cards floating over the map, `off` plain heading.
`useDashboardData` fetches both endpoints once per mount (5-min module cache), polls while `building`, hides on failure.
Clicks: reading bar -> `reading_status` filter, topic chip -> `topic`, project -> `project_id`; hovering a project lights
its papers on the map. `TopicMap` is a canvas: library papers big, references small and faint (toggle), cluster colours
and labels (collision-avoiding), hover = title, click = open paper, Ctrl/Cmd+wheel or pinch zoom (max 8x), drag pan,
"Reset zoom".

## Tests

`backend/tests/test_topic_map.py` (layout, clustering, labels, junk, seeding, payload visibility; pure, no DB),
`backend/tests/test_stats_dashboard.py` (dashboard aggregation), `frontend/src/components/dashboard/*.test.ts(x)`.
Run: `cd backend && env -u NEO4J_URI python -m pytest -q tests/test_topic_map.py tests/test_stats_dashboard.py`
(never point `NEO4J_URI` at production) and `cd frontend && NODE_ENV=test npx vitest run src/components/dashboard`.
