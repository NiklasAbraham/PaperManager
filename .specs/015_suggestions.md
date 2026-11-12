# Suggestions — developer context

PaperManager collects ideas for improving itself: the knowledge chat proposes one when a session
reveals a gap (a missing feature, a tool that could not do what was asked), users submit their
own, and everyone sees one list with status and votes.

## Shape

```
backend/db/queries/suggestions.py   Suggestion nodes: create, list, get, update, vote, delete, find_similar
backend/services/suggestions.py     SUGGESTION_INSTRUCTION, SuggestionFilter, filter_events(),
                                    record_chat_suggestion(), normalise / dedupe
backend/routers/suggestions.py      /suggestions/* HTTP API
frontend/src/pages/Suggestions.tsx  /suggestions
frontend/src/components/insights/SuggestionChip.tsx   the chip under a chat answer
```

## Storage (Neo4j)

`(:Suggestion {id, text, detail, source, status, created_by, created_at, updated_at, voters,
context, conversation_id, seen})`. `source` ∈ `chat | user | report`; `status` ∈
`open | planned | done | dismissed`; `voters` a list of user names (votes = its length; the
creator's vote is added on create); `seen` how many times the chat proposed the same thing;
`context` ≤ 300 characters of the question that led to it. Constraint `suggestion_id`.
Suggestions are shared by all users of the instance (they are about the app, not the library).

## From the chat

The knowledge chat's system prompt ends with `SUGGESTION_INSTRUCTION`: when, and only when, the
session shows that PaperManager lacks something the user needed, the model may end its answer
with one line `<suggestion>short concrete improvement</suggestion>`. The answer stream passes
through `filter_events()` (wrapped around `knowledge_chat_stream` in `routers/knowledge_chat.py`):
`SuggestionFilter` holds back any text that could be the start of the tag, removes the tag and its
content from the token stream (so neither the browser nor the saved message ever contains it; held-back text is released before any non-token event, e.g. a tool step or an interim answer),
and at the end of the stream records the suggestion (`record_chat_suggestion`) and yields one
extra event:

```json
{"type": "suggestion", "suggestion": SuggestionOut}
```

The chat shows it as a small dismissible chip under the answer (link to `/suggestions`, a vote
button, × hides it; dismissed chip ids are remembered in `localStorage`
`pm_dismissed_suggestion_chips`). A suggestion that matches an open or planned one (same
normalised text, or word-set Jaccard ≥ 0.75) bumps `seen` and adds the user's vote instead of
creating a duplicate. `SUGGESTIONS_FROM_CHAT=false` keeps stripping the tag but records nothing
and emits no event.

## API (`routers/suggestions.py`)

| Method | Path | Body / query | Who | Returns |
|---|---|---|---|---|
| GET | `/suggestions` | `?status=&source=&sort=votes\|new` | any user | `[SuggestionOut]` |
| GET | `/suggestions/counts` | | any user | `{"open": 0, "planned": 0, "done": 0, "dismissed": 0}` |
| POST | `/suggestions` | `{"text": str (3–280), "detail"?: str (≤ 2000)}` | any user | 201, `SuggestionOut` (source `user`) |
| PATCH | `/suggestions/{id}` | `{"status"?, "text"?, "detail"?}` | status: admin; text/detail: author or admin | `SuggestionOut` |
| POST | `/suggestions/{id}/vote` | | any user (toggles) | `SuggestionOut` |
| DELETE | `/suggestions/{id}` | | author or admin | 204 |

`SuggestionOut`: `{"id", "text", "detail", "source", "status", "created_by", "created_at",
"updated_at", "votes", "voted", "context", "conversation_id", "seen"}` (`voted`: the current user
voted). Default sort: open and planned first, then votes, then newest.

## Settings

| Variable | Default | |
|---|---|---|
| `SUGGESTIONS_FROM_CHAT` | `true` | record chat suggestions and emit the event |

## Tests

`tests/test_suggestions_filter.py` (tag split across tokens, no tag, unterminated tag, two tags),
`tests/test_suggestions_router.py` (CRUD, votes, permissions; query layer replaced by an in-memory
fake).
