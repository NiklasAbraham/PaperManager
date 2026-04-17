# T20 — Chat UI Polish

**Phase:** 5 — Frontend
**Depends on:** T14, T18
**Touches:** `frontend/src/components/ChatPanel.tsx`

## Goal
Polish the chat panel: streaming responses, loading states, copy button, clear history.

## Features to add

### Streaming (stretch goal)
- If we add streaming to the backend (`ai.py`), the chat panel can show tokens as they arrive
- Uses `EventSource` or `fetch` with `ReadableStream`
- Backend: use `anthropic.messages.stream()`
- Frontend: consume the stream, append tokens to the displayed answer
- Mark as optional — implement after everything else works

### Loading state
- Show a spinner / "thinking..." while waiting for response
- Disable input while waiting

### Copy button
- Each assistant message has a small copy icon → copies markdown to clipboard

### Clear chat
- Button to reset history for the current paper

### Error handling
- If API call fails: show inline error message, don't crash

## Done when
- [ ] Spinner shows while Claude is responding
- [ ] Input is disabled during response
- [ ] Copy button works
- [ ] Clear history button works
- [ ] Error shown gracefully if backend is unreachable

## Stretch
- [ ] Streaming responses work (tokens appear one by one)
