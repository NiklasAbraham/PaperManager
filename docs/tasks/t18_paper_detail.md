# T18 — Paper Detail Page + Note Editor

**Phase:** 5 — Frontend
**Depends on:** T09, T14, T16, T17
**Touches:** `frontend/src/pages/PaperDetail.tsx`, `frontend/src/components/NoteEditor.tsx`, `frontend/src/components/ChatPanel.tsx`

## Goal
Full view of a single paper. Three panels: metadata, note editor, chat.

## Layout

```
┌──────────────────────────────────────────────────────────────┐
│ ← Back to Library                               [PDF Link ↗] │
├─────────────────┬───────────────────┬────────────────────────┤
│ METADATA        │ NOTE              │ CHAT                   │
│                 │                   │                        │
│ Title           │ [Markdown editor] │ [Chat history]         │
│ Year · Venue    │                   │                        │
│                 │ @Jan works on     │ You: What is the       │
│ Authors:        │ this, see #NLP    │ main contribution?     │
│ · Vaswani       │ for context.      │                        │
│                 │                   │ Claude: The paper      │
│ Topics:         │ [Save]            │ introduces...          │
│ · transformers  │                   │                        │
│ · NLP           │                   │ [Ask a question...]    │
│                 │                   │                        │
│ Tags:           │                   │                        │
│ · arxiv         │                   │                        │
│ · foundational  │                   │                        │
│                 │                   │                        │
│ Projects:       │                   │                        │
│ · PhD thesis    │                   │                        │
│                 │                   │                        │
│ INVOLVES:       │                   │                        │
│ · Nele          │                   │                        │
│   (feedback)    │                   │                        │
└─────────────────┴───────────────────┴────────────────────────┘
```

## NoteEditor.tsx
- Textarea for markdown input
- Highlights `@Name` and `#Topic` tokens with colour as you type
- On save: PUT `/papers/{id}/note`
- Below editor: shows parsed mentions as chips ("Mentions: Jan, Nele | Topics: NLP")
- Uses `react-markdown` to show rendered preview (toggle edit/preview)

## ChatPanel.tsx
- Input box at bottom
- On submit: POST `/papers/{id}/chat` with question + history
- Renders Claude's answer as markdown
- History persists in component state (lost on page reload — that's fine for now)

## Done when
- [ ] Metadata panel shows all paper fields
- [ ] Inline add tag: type a tag and press enter → tag appears
- [ ] Inline add topic: same
- [ ] Note saves on button click, mentions are parsed
- [ ] Chat panel sends question and shows answer
- [ ] PDF link opens Google Drive URL in new tab

## Tests
- Manual: save a note with @Jan → check People page shows Jan mentioned
- Manual: ask chat question → answer appears
