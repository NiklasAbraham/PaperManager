# LinkedIn post: PaperManager, November 2026

Status: draft, not posted. Niklas posts it himself.

## Text

```
I asked my paper library how AlphaFold 3 predicts a protein complex. It queried its own graph, found 28 papers that cite it, pulled 16 figures and showed the spike protein in 3D.

That is PaperManager, the open-source research library I build next to my thesis. New this month:

Chat. Every answer shows its tool calls (the actual graph queries), a row of sources linked to the papers, figure strips and 3D structure cards for PDB entries and ligands.

Reports. A question becomes a long read written from your library, every claim cited, exported as HTML or Markdown.

Tokens. Every LLM call is logged with its cost per feature and model. On its first day it counted 3,156 calls for $0.66 in total.

Search. Filters for year, date added, reading status, PDF, notes, rating, tag, topic and venue, all in the URL. "protein binder design", from 2024, unread, with PDF, one tag: 1,173 papers down to 5.

Setup. Paste one line into Claude Code or Codex and the agent installs it: four questions, about 15 minutes, Docker. Anthropic or OpenAI key, no GPU.

Project page and chat demo: https://niklas-abraham.de/projects/papermanager/
Code: https://github.com/NiklasAbraham/PaperManager

#OpenSource #Research #KnowledgeGraph #ClaudeCode #SelfHosted
```

About 1,250 characters including links and hashtags. The first two lines (what LinkedIn shows before "see more") carry the hook: a question, what the
library did, three real numbers.

Every number is real: 28 library papers cite the AlphaFold 3 paper and it has 16 figures (read-only Cypher on the live
library, 12 Nov 2026); 3,156 calls / $0.656 is the Tokens page of 12 Nov 2026, the ledger's first day (3,146 of the calls are the
people-enrichment feature, $0.63); 1,173 → 5 is the filter path recorded in the search reel.

Music credit (CC BY 4.0, required wherever the reels are published): put it in the first comment under a post that
carries a reel:

```
Music: "Deliberate Thought" / "Floating Cities" by Kevin MacLeod (incompetech.com), CC BY 4.0.
```

## Media in posting order

LinkedIn does not mix a video and images in one post. Post 1 carries the chat reel; the four screenshots go in as a
document/image post a few days later (or in place of the video if you prefer images); the search reel is a third, short
post ("1,173 papers, one query, four filters: the five you need.").

| # | File | Format | Alt text |
|---|---|---|---|
| 1 | `../reels/reel-chat.mp4` (poster `../reels/reel-chat-poster.webp`) | video 1080x1920, 41 s | Screen recording of the PaperManager chat answering a question about AlphaFold 3: tool calls find the paper, 28 library papers cite it and 16 figures are pulled in. A 3D structure of the SARS-CoV-2 spike spins, then the sources open. |
| 2 | `li-1-chat-structure.png` | 1080x1350 | PaperManager chat answer showing the SARS-CoV-2 spike trimer (PDB 6VXX) in 3D with three highlighted receptor-binding domains, above the list of cited library papers. |
| 3 | `li-2-chat-tools.png` | 1080x1350 | PaperManager chat tool trace: a Cypher query and its result, a graph lookup returning 28 citing papers, and a Figures row with 16 thumbnails from the AlphaFold 3 paper. |
| 4 | `li-3-library-filters.png` | 1080x1350 | PaperManager library search for "protein binder design" with four active filters (year from 2024, unread, has PDF, tag de-novo-design) narrowing to 5 results. |
| 5 | `li-4-tokens.png` | 1080x1350 | PaperManager Tokens page: $0.656 spent across 3,156 LLM calls, 4.2M input and 105k output tokens, with a cost-per-day chart and a per-feature table. |
| 6 | `../reels/reel-search.mp4` (poster `../reels/reel-search-poster.webp`) | video 1080x1920, 40 s | Screen recording of the PaperManager library: a search for "protein binder design" gives 83 results. Filters for year 2024, unread, with PDF and the tag de-novo-design narrow it to five papers. |

There is no report screenshot: the live library has no report yet, and making one would have cost API money and written
to production. Once a real report exists, a shot of its view can replace #5 or join the image post.
