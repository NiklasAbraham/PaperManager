# Similar papers

**Explore → Similar papers** (`/similar`) answers one question: *does a paper like this already exist?*

You write or paste an abstract, PaperManager compares its meaning with the abstracts of the papers in your
library (and, if your instance runs the [paper feed](paper-feed.md), with the new preprints it has fetched), and
lists the closest ones with a similarity score. Use it to check whether a paper you are about to look for is
already on your shelf, or whether something close has shown up in the feed.

The text can describe a paper that **does not exist**: "I am looking for work that trains a diffusion model on
protein backbones with a fixed-length latent." The search does not need a real paper to start from.

Nothing leaves your instance. The text is embedded by the same small model that powers the library's semantic
search, running on your own server; no outside service and no language-model API is called, so it costs no
tokens.

## How to use it

1. Open **Explore → Similar papers**.
2. Write or paste the text into the box. A **title and one paragraph** work best.
3. Choose where to look (only if your instance has the feed): **Library**, **Feed** or **Both**.
4. Optionally set **Published since** and the number of **Results**.
5. Click **Search**.

Each result shows:

- a **similarity bar** and the score (0 to 1, higher is closer);
- a **Library** or **Feed** badge, and **In your library** on a feed paper you already have;
- the title: a library paper opens its page in PaperManager, a feed paper opens on the preprint server;
- authors, year or date, and a short abstract you can expand.

Two actions per result:

- **Add to library** (feed papers you do not have yet) does the same as the Add button on the feed page.
- **Use this paper as the query** copies its title and abstract into the box, without searching. Edit the text
  (cut a part away, add a sentence about what you want different) and search again. This is the quickest way
  to walk through a field: start from a paper you know, ask for its neighbours, pick the closest new one.

## What "scope" means

| Scope | Looks in |
|---|---|
| **Library** | the papers you may see: those outside every project and those in projects you are a member of |
| **Feed** | the candidates the feed has fetched and kept (it keeps them for 30 days by default, longer if somebody rated them) |
| **Both** | both lists merged by score |

Without the feed the toggle is not shown and the search runs on the library. Reference stubs (papers that only
exist because another paper cites them) are left out, because a title alone embeds poorly.

**Published since** limits feed papers by their publication date. A library paper only has a year, so it counts
as published on 1 January of that year; library papers without a year are left out when you set a date.

## Writing a good query

- **Write an abstract, not keywords.** The index holds title and abstract text, and a text of the same shape
  lands near it. A bare "diffusion protein" is treated as a short search phrase and matches loosely.
- **Say what the work does and how**, in the words a paper would use: the problem, the method, the result.
- **Hypothetical is fine.** Describe the paper you wish existed. A high score on a result means that paper
  probably exists; if the best score is low, probably nobody has written it, or the library does not hold it.
- **Keep to a title and a paragraph.** Only roughly the first 200 words are used (the same limit as the stored
  papers), so a long text is read from its start.
- **Vary it.** Two or three wordings of the same idea show you whether the neighbours are stable.

As a rough guide for the default model, a score above about **0.8** is a close match, **0.6 to 0.8** related
work, and **below 0.6** weak.

## Using it from Claude (MCP)

If you have connected [Claude to your library](mcp-server.md), two tools do the same search:

- `find_similar_papers(text, scope="both", k=10, since="", min_score=0.0)`
- `papers_like(paper_id, scope="both", k=10)`

Give `find_similar_papers` a title and a paragraph, not keywords. Example prompt:

> Here is the abstract of a paper I wish existed: "Sparse attention for long documents ... (a paragraph)".
> Check with find_similar_papers whether something like it is already in my library or in the feed since
> 1 October, and tell me which results are really the same idea and which only share the topic.

The tools return titles, links, scores, whether a feed paper is already in your library, and a 300-character
snippet. The MCP server reads the same index as the app, so it needs the same `VECTOR_STORE_DIR` (and, for the
feed, `PAPER_FEED` and `PAPER_FEED_DIR`) as the backend, and a running backend to embed your text.

## When it says the index is not ready

The page shows **The index is not ready for this search** with the reason, and the same text appears as
`available: false` from the API and the tools. It happens when

- the server has just started and is still building the index of the library (a few minutes for a large
  library; the first start after switching on semantic search takes longest),
- the embedding model was changed (`EMBED_MODEL`) and the index is being rebuilt with it (it answers again as
  soon as the new index is complete),
- the embedding model is still loading after a start,
- semantic search is switched off (`LIBRARY_SEMANTIC=false`), or
- you chose **Feed** and the feed has not embedded any papers yet.

Try again in a few minutes. With **Both**, one list that is not ready is named in a note and the other still
answers.

## Limits

- **Quality depends on the embedding model and on the abstracts you hold.** The default model is small and
  fast; it finds topics and approaches well and subtle differences poorly. A paper in your library without an
  abstract (or with only a title) embeds badly and will rarely be found. If the library has a summary instead
  of an abstract, the summary is used.
- **Similar is not the same.** A high score says two texts are about the same thing, not that one paper repeats
  the other. Read the abstract before deciding.
- **Feed papers are only recent ones** from the sources and categories your instance chose; the feed is a
  window, not an archive.
- **Other users' papers stay hidden.** You only get papers you may see, and on a shared instance a feed paper is
  marked *In your library* only if it is among them. Your thumbs-ups and thumbs-downs from the feed are yours
  alone.
