# Paper feed

The **Paper feed** (**Explore → Paper feed**, `/feed`) is a digest of new preprints from arXiv, bioRxiv
and medRxiv, ranked for you by what you already keep in your library. It is **optional and off by
default**: the menu entry does not exist until the person who runs the server switches it on.

(Not to be confused with the **Feed** tab of **Explore → Find papers**, which streams recent papers for keywords
you type; the paper feed here is chosen by arXiv category and ranked by your library.)

Open the feed once a day, look at the top of the list, add what you want with one click, and tell it what
it got wrong. Every thumbs-up and thumbs-down makes the next ranking a little better.

## Turning it on

The server owner sets one variable in `.env` and restarts the backend:

```env
PAPER_FEED=true
```

With `PAPER_FEED=false` (the default) nothing runs: no background thread, no folder, no model, no request
to any other server, and the feed's API answers *not found*. The other settings are in
`.env.example`:

| Variable | Default | Meaning |
|---|---|---|
| `PAPER_FEED` | `false` | Master switch |
| `PAPER_FEED_DIR` | `/data/feed` | Where the feed keeps its small database (`feed.sqlite`) |
| `PAPER_FEED_INTERVAL` | `21600` | Seconds between refreshes (6 hours) |
| `PAPER_FEED_RETENTION_DAYS` | `30` | How long fetched papers are kept (papers you rated are kept) |
| `PAPER_FEED_MAX_PER_REFRESH` | `2000` | Most papers fetched per source and refresh |
| `PAPER_FEED_CONTACT` | empty | Optional contact (an address or a URL) added to the User-Agent that arXiv and bioRxiv see, so they can reach you if your instance misbehaves |

The papers the feed has fetched are called *candidates* on this and the other pages. They are embedded with the
same model as the library search and [similar papers](similar-search.md): `EMBED_MODEL`, by default
`BAAI/bge-small-en-v1.5` (384 numbers per paper) on the CPU. No GPU, no API key and no extra package is needed. If
the operator changes the model, see [Switching the embedding model](switching-the-embedding-model.md); the
feed's ranking retrains by itself afterwards.

## Choosing what you see

The first time you open the page it asks what the feed should show:

- **Sources.** arXiv, bioRxiv, medRxiv. bioRxiv and medRxiv have no categories: you get every new preprint
  and the ranking puts the relevant ones first.
- **arXiv categories.** Type names such as `cs.LG`, `cs.CV` or `q-bio.BM`, or click an example. arXiv has
  too many papers to fetch everything, so the feed fetches **only the categories you choose**, and nothing
  at all until someone has chosen one. The [arXiv category list](https://arxiv.org/category_taxonomy) shows
  every name.
- **Digest window.** How many days back the list reaches (1 to 14, default 3).

You can change this later with **Settings** in the status strip. Each person on the instance has their own
choices, ratings and ranking; the server fetches the union of what everybody chose.

## Reading the list

Each row shows the title (it opens the preprint), authors, date, a **relevance bar**, **why** (the three papers
in your library it is closest to) and the abstract on a click. The buttons:

- **Add to library** ingests the paper the same way pasting its link on the Library page does. **Add to
  project** does the same and puts it in a project you pick. Both count as a thumbs-up.
- **Thumbs up** and **thumbs down** say "more like this" and "less like this".
- **Dismiss** hides a paper and counts as "not for me".

Rated and dismissed papers disappear from the list; tick **Show rated** to see them again. Papers you
already have are marked **In your library** and sorted to the bottom. The strip at the top shows when the
feed last fetched, how many papers it holds and how it is ranking right now. **Refresh now** fetches
immediately (admins, or anybody on an instance with one user).

## How the ranking works

The method follows Scholar Inbox: Flicke et al., *Scholar Inbox: Personalized Paper Recommendations for
Scientists* ([arXiv 2504.08385](https://arxiv.org/abs/2504.08385)). PaperManager has no connection to that
service; this is a small local version of the same idea.

1. Every new paper's title and abstract is turned into a list of numbers (an *embedding*) that places
   papers on similar topics close together.
2. Your library teaches the feed what you like, and you do not have to rate anything for that. A real paper
   with an abstract or summary that you added yourself, or that sits in one of your projects, counts as a mild
   "yes" (a paper with neither embeds badly: [fill missing abstracts](abstract-backfill.md)). Ratings and
   bookmarks sharpen it: a paper you rated 4 or 5 stars, or bookmarked, is a clear "yes"; one you read and
   highlighted is a stronger "yes" than one that is merely kept; one you rated 1 or 2 stars is a "no". A paper
   counts once, by its strongest sign. Reference stubs (papers that only exist because another paper cites them) do not count. Your
   thumbs in the feed count too.
3. From these "yes" and "no" papers, plus a random sample of the feed's other papers as a stand-in for
   "everything else", the server trains a small model (a logistic regression) that scores how likely you
   are to want a new paper.
4. The list is sorted by that score.

**Few signals at first.** With fewer than 10 papers that count as a "yes" (added, in a project, rated, bookmarked, read
or thumbs-up) there is not enough to train a model. The feed then sorts by how close each paper is to the nearest of
those papers, and with none at all it shows the newest first. The strip tells you which of the three modes is active:
*Ranked by a model trained on N papers from your library*, *Ranked by similarity to N paper(s) from your library (a
model needs 10)*, or *Newest first*.

**Several people on one server.** Ratings, bookmarks and reading status are stored once per paper, not per
person. On an instance with several users they therefore only teach the feed about papers *you added*. What
you added and what sits in projects you can see always counts as your own library, and so do your thumbs in the feed. On an instance with a single user all of them count.

**How good is it?** From 30 liked papers on, the strip shows a *held-out AUC*: the feed sets aside your newest
likes, trains without them, and checks how often it ranks one of them above a random paper. 0.5 is a coin
flip, 1.0 is perfect. It is a rough guide and not a promise.

## Privacy

Everything stays on your instance: the fetched papers, your ratings, your choices and the model are stored in
a small database in `PAPER_FEED_DIR` and never leave it. Embedding runs on your own server. The only requests
that leave it go to **arXiv** and **bioRxiv / medRxiv**, and they carry nothing about you: the categories you
chose, a date range and the User-Agent `PaperManager-feed` (plus the optional contact). Your library, your
ratings and your name are never sent anywhere. (**Add to library** uses the normal URL ingest, which looks the
paper up the same way pasting its link on the Library page does.)

## When something looks wrong

- *The page says the feed is switched off.* `PAPER_FEED=true` is missing on the server.
- *Nothing shows.* Choose at least one category, then **Refresh now**. The first fetch takes a few minutes,
  because arXiv allows one request every three seconds.
- *arXiv answered "too many requests" or timed out.* The feed waits as long as arXiv asks (30 to 120 s when it
  does not say), keeps to one request at a time and tries again. A category that did not finish is fetched again
  from the start at the next refresh; nothing is lost.
- *A problem is listed under the strip.* One source failed on the last refresh (for example arXiv was
  unreachable). The other source still ran, and the next refresh tries again.
- *The ranking looks random.* Rate a few papers. Ten papers that count as a "yes" switch the model on.

## See also

- [Similar papers](similar-search.md): paste an abstract and look in the library and in the feed's candidates.
- [Switching the embedding model](switching-the-embedding-model.md): what runs behind the ranking and how to change it.
- [Fill missing abstracts](abstract-backfill.md): papers without an abstract teach the feed less.
