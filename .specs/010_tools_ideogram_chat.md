# Tools → Ideogram Chat

A navbar **Tools** section (grid of tool cards) whose first tool is **Ideogram
Chat** — a prompt + editable-boxes image generator that runs the open-weights
**Ideogram 4** text-to-image model on the on-demand GPU 2, spun up only while a
session is active.

Added: 2026-07. Spans three codebases + one GPU host.

---

## What it does

1. Open **Tools → Ideogram Chat**. The frontend asks the backend to spin up the
   Ideogram model on GPU 2 (status pill: *Spinning up GPU… → GPU ready*).
2. Type a plain prompt and click **Expand into boxes** — an LLM (Gemma or Claude,
   selectable) rewrites it into Ideogram's structured "boxes" caption.
3. All boxes appear, each **editable** — text, description, position (`bbox`),
   colours. Add/remove boxes; adjust the style/background.
4. **Generate** → image (with box overlays). Edit one box → **Regenerate box**
   keeps the same seed so the rest of the image stays stable; **Regenerate all**
   uses a fresh seed.
5. When the tab is left closed/idle past the timeout, GPU 2 is freed
   automatically.

---

## Architecture

```
┌────────────────────┐   /ideogram/*    ┌──────────────────────┐  /ideogram/*   ┌──────────────────────┐  docker run   ┌────────────────┐
│  React frontend    │ ───────────────► │ PaperManager backend │ ─────────────► │  Inference Manager   │ ─────ssh────► │  hermione GPU2 │
│  IdeogramChat.tsx  │  (nginx proxy)   │  routers/ideogram.py │   (via URL)    │  (spiceforge repo)   │               │ ideogram-serve │
└────────────────────┘                  └──────────┬───────────┘                └──────────────────────┘               └────────────────┘
                                                   │ magic-prompt (text→boxes)
                                         ┌─────────▼─────────┐
                                         │ Gemma (LiteLLM)   │  ← GPUs 0/1, always-on
                                         │  or Claude (API)  │  ← cloud
                                         └───────────────────┘
```

- **Generation** runs on **GPU 2** (single-tenant, shared with docling PDF ingest
  and vLLM chat).
- **Magic-prompt** (text→boxes) runs on **Gemma (GPUs 0/1, always-on)** or
  **Claude (cloud)** — never on GPU 2, so it never contends with generation.

See `spiceforge/backend/.specs/015_ideogram_inference.md` for the inference-manager
side, and `spiceforge/backend/src/llm/inference_manager/ideogram/REDEPLOY.md` for
the redeploy runbook.

---

## Components (files)

### Frontend (`frontend/`)
| File | Role |
|---|---|
| `src/App.tsx` | Navbar **Tools** link; routes `/tools`, `/tools/ideogram` (lazy) |
| `src/pages/Tools.tsx` | Grid of tool cards (extensible) |
| `src/pages/IdeogramChat.tsx` | The chat/box editor: session lifecycle, image hero + box overlays, per-box editor, magic-prompt model picker, quality/resolution/seed controls, history drawer, export |
| `src/lib/ideogramHistory.ts` | IndexedDB store for past generations (image + caption + params) |
| `src/api/client.ts` | `startIdeogramSession`, `getIdeogramStatus`, `stopIdeogramSession`, `ideogramMagicPrompt(…, model)`, `ideogramGenerate` |
| `src/types/index.ts` | `IdeogramCaption`, `IdeogramElement`, `IdeogramSessionStatus`, `IdeogramGenerateBody`, … |
| `nginx.conf` | **`location /ideogram`** proxies to `backend:8000` (long timeouts) |

### UI / design
The page uses PaperManager's design tokens (`bg-raised`, `text-ink/-2/-3`,
`border-line`, `bg-accent`, `text-accent`, `bg-accent-lo`, `text-coral`, …, from
`index.css @theme`) so it matches the rest of the app. Layout:

- **Header** — 🎨 title, GPU status pill, **History** + **Export PNG** buttons.
- **Left pane** — a *Describe your image* card (prompt + model picker +
  ✨ Expand into boxes), the **image hero** (contained, with numbered box
  overlays + generating spinner + empty state), and a generate toolbar
  (preset / resolution / seed / Generate / Regenerate all).
  - **Direct box manipulation** on the hero (`ImageCanvas`): drag a box to move
    it, drag corner/edge handles to resize, and drag on empty canvas to draw a
    new box. Moves/resizes **snap** to a 10-unit grid + guides (canvas
    thirds/edges + other boxes' edges); hold **⌥/Alt** to disable snapping.
    Each box shows a live label (its text/desc). Keyboard: arrows nudge the
    selected box (⇧ = ×10), **⌥+arrows** resize, Delete/Backspace removes, `D`
    duplicates. `pointer capture` on the container keeps drags alive off-canvas;
    all edits write straight into the caption's `bbox` (0–1000 grid).
  - **Undo/redo** (⌘/Ctrl+Z, ⇧+Z / Ctrl+Y, or header ↶/↷) over a bounded
    caption-history stack. Drags snapshot once per gesture (not per frame).
- **Resolution** — the 4 presets plus a **Custom…** mode: free `W × H` inputs
  (snapped to multiples of 16 in 256–2048 on generate; a `→ WxH` hint shows the
  snapped value), an **aspect-lock** toggle, a **swap W/H** button, and quick
  ratio chips (1:1, 16:9, 9:16, 4:3, 3:4, A4).
- **GPU-asleep banner** — if the session goes `stopped`/`error`, a banner keeps
  the boxes and offers **Spin GPU back up**; a `beforeunload` guard warns before
  closing the tab with an unsaved generated image.
- **Right pane** — the **Boxes** list (polished per-element cards: type badge,
  text/desc, bbox `y/x/y2/x2` inputs, colour swatches, per-box **Regenerate box**
  + delete), a collapsible **Style & background** section, and *Export caption
  JSON*.
- **History drawer** — slide-over with a thumbnail grid of past generations.

### Backend (`backend/`)
| File | Role |
|---|---|
| `routers/ideogram.py` | Authed proxy: `session/start|status|stop`, `generate`; `magic-prompt` runs locally via Gemma/Claude |
| `services/ideogram_magic.py` | Prompt→boxes expansion; provider routing (`gemma`/`claude`), JSON parse + **normalization** |
| `services/ideogram_magic_prompt_v1.txt` | Ideogram's bundled magic-prompt system prompt (schema contract) |
| `main.py` | Registers `ideogram_router` |

---

## Caption ("boxes") schema

The structured caption Ideogram 4 consumes (and the box editor edits):

```jsonc
{
  "high_level_description": "…",
  "style_description": { "aesthetics": "…", "lighting": "…", "medium": "…",
                          "art_style": "…", "color_palette": ["#RRGGBB"] },
  "compositional_deconstruction": {
    "background": "…",
    "elements": [
      { "type": "text",   "bbox": [y_min, x_min, y_max, x_max], "text": "HELLO", "desc": "…", "color_palette": ["#1D3557"] },
      { "type": "object", "bbox": [y_min, x_min, y_max, x_max], "desc": "a red circle", "color_palette": ["#E63946"] }
    ]
  }
}
```

- **`bbox` = `[y_min, x_min, y_max, x_max]` on a 0–1000 grid, origin top-left.**
- Colours are uppercase `#RRGGBB` (style ≤16, element ≤5).
- **Single-box edit** = change one element's fields and regenerate at the **same
  seed**. These weights are not a true inpainter, so seed-lock keeps the rest as
  stable as the model allows (near-identical, not pixel-perfect).

---

## Magic-prompt (text → boxes)

Not special — just an LLM turning a plain sentence into the caption above, using
Ideogram's own system prompt (`ideogram_magic_prompt_v1.txt`). **Model is
selectable** in the UI:

| Option | Backend `model` | Runs on | Notes |
|---|---|---|---|
| Gemma (local, free) | `gemma` | LiteLLM / GPUs 0/1 | always-on, no cost, no GPU-2 contention |
| Claude (best quality) | `claude` | Anthropic API (`claude-haiku-4-5`) | strongest at the strict schema |

**Normalization** (`_normalize_caption`) repairs common small-model deviations so
the renderer accepts the output:
- key `compositional_decomposition` (and similar) → `compositional_deconstruction`
- element `type: "obj"` / `"txt"` / free text → canonical `object` / `text`
- missing/invalid `bbox` → a default `[100,100,900,900]` box the user can drag
  (Claude sometimes omits bbox for auto-placement; the editor needs a concrete one)

Retries once on malformed JSON.

---

## History & export

- **History** — every successful generation is saved to **IndexedDB**
  (`papermanager-ideogram` DB, `generations` store) via
  `src/lib/ideogramHistory.ts`: `{id, ts, prompt, caption, imageB64, seed, preset,
  width, height}`. IndexedDB (not localStorage) is used because each entry holds a
  full PNG. History is **per-browser**, best-effort (all calls are wrapped so a
  missing IndexedDB — e.g. in tests — never breaks the page). The **History**
  drawer shows a thumbnail grid; click a thumbnail to **restore** (loads the
  caption, image, seed, preset, resolution back into the editor), or download /
  delete individual entries, or **Clear all**.
- **Export** — **Export PNG** (header) downloads the current image; each history
  thumbnail has its own download; **Export caption JSON** downloads the structured
  caption for reuse/versioning. Filenames are slugged from the prompt.

## Lifecycle & timings

- **Spin-up (cold): ~4–5 min** — loading the 9.3 GB nf4 model into GPU 2 VRAM
  (bitsandbytes dequant + CUDA init; not download time).
- **First-ever spin-up: ~7–8 min** — the shared HF cache lacks the weights, so it
  also downloads ~6 GB once.
- **Stays warm while the chat tab is open** — the frontend heartbeats every 5 s
  (status poll → `touch_ideogram`), resetting the idle timer. You pay the load
  **once** per session; generations after that start immediately.
- **Idle reaper**: after `IDEOGRAM_IDLE_TIMEOUT` (default 600 s) of no activity
  (tab closed), GPU 2 is torn down automatically.
- **Per generation once ready**: Turbo-12 ≈ 30–60 s, Default-20 ≈ ~1 min,
  Quality-48 ≈ 2–3 min.

---

## API (PaperManager backend, all authed)

| Method & path | Purpose |
|---|---|
| `POST /ideogram/session/start` | Ensure the model is spinning up; returns `{job_id, status}` |
| `GET  /ideogram/session/status` | Session status (also keeps the model warm) |
| `POST /ideogram/session/stop` | Tear down now (idle-reaper is the backstop) |
| `POST /ideogram/generate` | `{caption_json|prompt, width, height, seed, sampler_preset}` → `{image_base64, seed, caption}` |
| `POST /ideogram/magic-prompt` | `{prompt, width, height, model}` → `{caption}` (Gemma/Claude, no GPU 2) |

`generate`/`session/*` proxy to the inference manager (`INFERENCE_MANAGER_URL`);
`magic-prompt` is handled in-process via Gemma/Claude.

---

## Known limitations / gotchas

- **GPU 2 is single-tenant.** While Ideogram is loaded, docling PDF ingest and
  vLLM chat are paused. The idle reaper keeps that window bounded.
- **nginx allowlists API prefixes** — every new backend prefix needs a `location`
  block in `frontend/nginx.conf` (this bit us: `/ideogram` 405'd until added).
- **No true inpainting** — "single-box edit" is edit-JSON + regenerate at locked
  seed, not region inpainting.
- **Non-commercial licence** on the Ideogram 4 weights; magic-prompt via Claude
  incurs a small API cost per expand.

---

## Tests

| Suite | Covers |
|---|---|
| `backend/tests/test_ideogram_router.py` | proxy start/status/generate, 409 conflict, proxy-error unwrap, auth |
| `backend/tests/test_ideogram_magic.py` | Gemma/Claude routing, JSON parse, fence-strip, **normalization** (key/type/bbox), retry |
| `frontend/src/pages/IdeogramChat.test.tsx` | session start, locked-seed box regen posts edited caption, fresh-seed regen, history drawer, export-disabled-until-image |
| `spiceforge/backend/tests/llm/test_inference_manager.py` | `start_ideogram` docker args, 409 busy, idle reaper, `touch_ideogram` |
| `spiceforge/backend/tests/llm/test_ideogram_server.py` | verbatim caption vs magic path, PNG out, dim validation, 503-while-loading |
