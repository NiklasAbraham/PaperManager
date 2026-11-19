# Conference explorer

The **Conferences** tab browses the accepted papers of the major ML, vision, NLP and robotics
conferences two ways: by **institution** (where does a university, lab or company rank, what
does it publish on, with whom) and by **topic** (type a topic or paste an abstract: which
universities and companies publish most on it, and which papers are closest). It works for
every conference-year in the list below, not one fixed conference, and runs entirely on your
own server. A search box on the landing page searches [all loaded conferences at
once](#searching-all-conferences): papers, authors and where a topic is published.

![NeurIPS 2026 in the conference explorer](../img/screenshots/conferences.webp)

---

## Which conferences

| Field | Conferences | Source |
|---|---|---|
| ML | NeurIPS 2020–2026, ICML 2022–2026, ICLR 2022–2026 | official conference site |
| ML | AISTATS, UAI, COLT | Paper Copilot |
| Vision | CVPR 2023–2026, ICCV 2025, ECCV 2024 and 2026 | official conference site |
| Vision | CVPR 2022, ICCV 2021/2023, ECCV 2022, WACV | Paper Copilot |
| NLP | ACL, EMNLP, NAACL, COLM | Paper Copilot |
| General AI | AAAI, IJCAI | Paper Copilot |
| Robotics | CoRL, RSS, ICRA, IROS | Paper Copilot |
| Data | KDD, WWW | Paper Copilot |

**Official conference sites.** NeurIPS, ICML, ICLR, CVPR, ICCV and ECCV publish every accepted
paper as one JSON file, with authors, each author's institution (92–98 % of authors carry one),
abstract, decision (poster, spotlight, oral), session and the OpenReview link.

**[Paper Copilot](https://github.com/papercopilot/paperlists)** keeps paper lists for the
other venues and older years. Most come with normalised affiliations; a few (ACL 2025, recent
OpenReview venues that hide them) do not, and for those the page says the institution views
are thin and the topic view is the useful one. Rejected and withdrawn submissions are dropped.

Some sites serve only the first page of their list without a login (CVPR 2026 at the time of
writing: 199 of 5,163 papers with authors). The titles of the rest come from the site's public
paper list, so topic search still covers the whole conference, and the page says for how many
papers institutions are known.

---

## Loading a conference

The first time you open a conference that is not loaded, PaperManager downloads its list and
indexes it in the background; the page shows the progress and fills in as it goes:

1. **Downloading** the list (a few seconds).
2. **Reading**: institution names are normalised and counted. The institution views work from
   here on.
3. **Indexing**: every title and abstract is embedded with
   [bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) on the CPU, which gives the
   research areas and semantic topic search. About two minutes for NeurIPS 2026 (6,500 papers,
   titles only so far); with abstracts 7–15 minutes (ACL 2025, 3,100 papers: 7 min; NeurIPS
   2025, 5,900 papers: 14 min) on four CPU threads. A conference with abstracts or keywords
   also gets its titles embedded on their own (20–45 s), which the
   [cross-conference search](#searching-all-conferences) compares conferences on.

A default set is loaded when the backend starts (see [Settings](#settings)), so the main
conferences are ready without anyone waiting. **refresh** at the bottom of a conference page
downloads it again; this year's conferences are also refreshed automatically every two weeks,
since the sites keep adding abstracts, sessions and late papers until the meeting.

---

## Overview

Paper count, institution count and the share of papers with at least one company author; the
research-area mix of the whole conference (click an area for its institution ranking); the top
universities and institutes, and the top companies.

## Institutions

A ranked table of every institution, searchable by name, filterable by academia / industry and
by research area. With an area selected the table ranks by papers in that area and shows what
share of each institution's own papers that area is ("of own").

Click a row for the institution card:

- **Rank** overall and among universities or companies, **papers**, **fractional papers** and
  **share** of the conference.
- **Research areas** against the whole conference: the thin bar under the institution's bar is the
  conference's mix, and areas the institution publishes in at least twice the conference rate are
  marked ×2.0, ×3.1, ...
- **Most frequent co-authoring institutions** and the authors with the most papers there.
- **Every paper**, orals and spotlights first; click an area in the legend to filter.

## Topics & papers

Type a topic ("RL for LLM reasoning", "diffusion models for protein structure") or paste a whole
abstract. The query is embedded with the same model, the closest 50 / 100 / 200 / 500 papers are
taken, and the page shows:

- their **research-area mix** and how many have a company author;
- the **universities & institutes** and the **companies** with the most of those papers (hover for
  what share of the institution's papers at the conference that is);
- the **closest papers**, each with its match score, area, decision, session and institutions.

Short queries get bge's retrieval instruction ("Represent this sentence for searching relevant
passages: ..."); a pasted abstract is embedded as is. Until a conference is indexed, topic
search falls back to keyword matching on titles and abstracts and says so.

Short queries go into the URL (`/conferences/neurips2026?view=topics&q=video%20generation`), so a
result can be shared or bookmarked.

## Papers and your library

Every paper row shows **In library** when a paper with the same title is already in your library
(it links to it), and **+ Library** otherwise. Adding creates the paper with its title, abstract,
venue ("NeurIPS 2026"), year and authors (each with their institution as affiliation), tagged
`from-conference`. Upload the PDF later from the paper page for the full pipeline. Click a title
for the abstract, the author list with institutions and the eight closest papers at the same
conference; ↗ opens the paper on the conference site.

---

## Searching all conferences

The search box at the top of the Conferences page searches every loaded conference at once.
Type a title, an author or a topic, or paste an abstract; results update 300 ms after you stop
typing. Three tabs show three readings of the same query; the page opens the one that fits
(an author's name that matches no title opens **Authors**, a text of more than twelve words
opens **Topics**, anything else **Papers**). Filters narrow the search to a field (ML, Vision,
NLP, ...), a series (NeurIPS) or a range of years. Query, tab and filters are kept in the URL
(`/conferences?q=Charlotte%20Deane&kind=author`), so a search can be shared or bookmarked. A tab
you pick stays picked for the next query.

Capital and small letters never matter, nor do accents: `CHARLOTTE DEANE`, `charlotte deane`
and `Charlotte Déane` give the same results. Matched words are marked in titles and names.
When a word looks like a typo, the page asks "Did you mean ...?" (the results already include
the corrected word).

Keys: **Enter** searches at once, **Esc** clears the box (or returns to it from a result),
**↑ / ↓** move through the results, **Enter** on a result opens it.

### Papers

- **Title matches**: titles containing the query's words, best first: the whole title, then
  titles starting with the query, then the query as a phrase, then all its words in any order,
  then (for queries of three words or more) all but one. A word also matches its plural, the
  last word matches as a prefix while you type it ("video gen"), and a word of five letters or
  more matches with one typo ("difusion"). Ties are broken by closeness in meaning.
- **Closest by meaning**: the papers whose titles are nearest to the query in embedding space
  and that did not already match by words. A typo is corrected before embedding.

Each paper carries a chip with its conference; it expands, links and goes into your library as
anywhere else in the explorer.

### Authors

Names are matched with case and accents folded, by full name, surname, "Surname, First",
initials (`c deane`), the start of a name or with one typo. Each author card shows the number
of papers, conferences and distinct co-authors, the institutions given on those papers, and
the papers grouped by conference, newest first, each with the author's position and their
institution on that paper.

A name is not a person: two researchers can share one. When an author's papers fall into
groups that share neither an institution nor a co-author, the card says so and lists the
groups ("may belong to 2 people: Tsinghua University · Stanford University").

### Topics

Type a topic or paste an abstract to see where it is published:

- **Per conference**: how many of the closest papers each conference holds, per 1,000 of its
  papers, so a conference of 2,700 papers compares with one of 6,600.
- **Over the years**: the same rate for every series loaded for more than one year
  (NeurIPS 2025 → 2026), with the change.
- **Universities & institutes** and **companies** counted over all conferences together
  (hover for the count per conference), and the research-area mix of those papers.
- **Closest papers** over all conferences.

"Closest" means the 100 / 300 / 1,000 papers nearest to the query among all papers of all
selected conferences together. The similarity of the last of them is one threshold for every
conference, shown under the heading.

Conferences are compared on **title** embeddings only. A title-plus-abstract embedding sits
0.03–0.07 higher in cosine similarity to any query than a title-only one, so NeurIPS 2025 (with
abstracts) would otherwise hold five times as many "diffusion models for protein structure"
papers per 1,000 as NeurIPS 2026 (titles only so far) when the papers' titles say they are
about equally common. For this reason the numbers differ from a single conference's
**Topics & papers** view, which uses titles and abstracts.

Example, all nine default conferences, closest 300: "diffusion models for protein structure"
is densest at ICLR 2026 (12.1 per 1,000) and NeurIPS 2025 (12.0), then ICML 2026 (8.7) and
NeurIPS 2026 (7.4); MIT and Google lead with 19 papers each. "video generation" is densest at
ECCV 2026, CVPR 2026 and ICCV 2025 (14–17 per 1,000, against 4–7 at the ML venues), with
ByteDance (33) and Alibaba (26) the top companies.

**Search all conferences →** next to a single conference's topic result runs the same query
here.

---

## How things are counted

- **Papers**: a paper counts once for every institution with at least one author on it. A paper
  by MIT and Google counts for both.
- **Fractional**: each author is 1/n of a paper (n authors), split equally over that author's
  institutions. Fractional counts sum to the number of papers with affiliations.
- **Rank**: by papers, ties share a rank.
- **Institution names** are normalised: HTML entities and full-width letters are cleaned,
  department names dropped ("Department of Computer Science, ETH Zurich" → ETH Zurich), several
  affiliations in one field split ("Google, TUM" → Google and TU Munich), and spellings merged.
  About 220 alias rules merge the common cases: Google with DeepMind, Meta with FAIR, the
  institutes of the Chinese Academy of Sciences, campus spellings ("University of California,
  Berkeley", "UC Berkeley"), acronyms (MIT, CMU, KAIST, EPFL). Everything else keeps its own
  spelling and is merged by case, accents and punctuation.
- **Academia / industry**: aliases carry it; otherwise a name with "university", "institute",
  "college", "laboratory", "hospital", ... is academia, anything else a company. Non-profit
  institutes (Allen Institute for AI, Mila, Max Planck, Shanghai AI Laboratory) count as academia.
  "Independent researcher" is not counted, nor are placeholders and fragments the sources
  contain: anonymised names ("AXXX", "Anonymous Institution"), bare words ("University", "ML",
  "Research"), names of one or two letters without an alias ("HY"; "LG" and "HP" are aliases),
  e-mail addresses and web addresses of universities. "Head of AI @ Squirrel AI" counts as
  Squirrel AI.
- **Research areas** are one fixed taxonomy of 24 areas for every conference, so the mix of
  NeurIPS and ICML can be compared and an area keeps its colour everywhere. Each paper gets the
  area whose description is closest to its embedding, after both are centred on the conference's
  mean paper vector; the area centres are then moved halfway towards their papers twice. Areas
  are a coarse map, not a label: a paper on, say, RL for theorem proving lands in one area only.

A wrong institution mapping is fixed by an alias line in
`backend/services/conferences/institutions.py`.

---

## From Claude (MCP)

Five [MCP tools](mcp-server.md) expose the same data to Claude Desktop and Claude Code:

| Tool | Answers |
|---|---|
| `list_conferences` | Which conference-years are loaded, with paper and institution counts |
| `conference_topic` | Who publishes on a topic at a conference: top universities and companies, area mix, closest papers. With `conference="all"`: the same over every loaded conference, plus papers per 1,000 per conference and the trend over years |
| `conference_institution` | What one institution published at a conference: rank, counts, area mix against the conference, collaborators, authors, papers |
| `conference_search_papers` | Papers across all loaded conferences by title words (typos tolerated), then by meaning |
| `conference_search_author` | An author across all loaded conferences: papers per conference with their institution on each, co-author count, and whether the name looks like more than one person |

`conference` takes a key (`neurips2026`), a name (`ICML 2025`), a bare series (`iclr` = its
latest year) or, for `conference_topic`, `all`. Papers already in your library come back with
their `library_paper_id`.

---

## Settings

All optional; set them in `.env` and pass them to the backend in `docker-compose.yml`.

| Variable | Default | What it does |
|---|---|---|
| `CONFERENCES_AUTO` | `true` | Load the default conferences at startup |
| `CONFERENCES_DEFAULT` | `neurips2026,icml2026,iclr2026,cvpr2026,iccv2025,eccv2026,neurips2025,acl2025` | Which ones |
| `CONFERENCES_REFRESH_DAYS` | `14` | Reload this year's default conferences when older than this |
| `CONFERENCE_DATA_DIR` | `/data/conferences` | Where datasets and the model live (the backend's volume) |
| `CONFERENCE_EMBED_THREADS` | `4` | CPU threads for embedding |
| `CONFERENCE_EMBED_MODEL` | empty | The explorer's embedding model. Read first; `EMBED_MODEL` is used only when this is empty. Set it to the model the explorer's datasets were built with before you move the library to another one ([how](switching-the-embedding-model.md)) |
| `CONFERENCE_CACHE_MAX` | `32` | Conferences held in memory at once (20–40 MB each); searching all conferences needs every loaded one in memory |

Each conference takes 5–30 MB on disk (papers, institutions, float16 embeddings); the model
takes 130 MB once. No API key is involved and nothing is sent anywhere except the download
of the paper lists and, once, the model.
