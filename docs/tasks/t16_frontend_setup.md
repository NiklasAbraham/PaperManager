# T16 — Frontend Setup

**Phase:** 5 — Frontend
**Depends on:** T03 (backend running)
**Touches:** `frontend/`

## Goal
React + Vite app boots locally. Tailwind CSS works. API client is wired to the backend.

## Steps

1. Scaffold with Vite:
   ```bash
   cd frontend
   npm create vite@latest . -- --template react-ts
   npm install
   ```

2. Install dependencies:
   ```bash
   npm install tailwindcss @tailwindcss/vite
   npm install react-router-dom
   npm install react-dropzone        # for PDF drag & drop
   npm install react-markdown        # render markdown notes
   ```

3. Configure Tailwind in `vite.config.ts`.

4. Create `src/api/client.ts`:
   ```typescript
   const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

   export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
     const res = await fetch(`${BASE}${path}`, options);
     if (!res.ok) throw new Error(`API error ${res.status}`);
     return res.json();
   }
   ```

5. Create `src/types/index.ts` with TypeScript interfaces matching backend Pydantic schemas:
   - `Paper`, `PaperCreate`, `Person`, `Topic`, `Tag`, `Project`, `Note`

6. Create `src/App.tsx` with React Router setup:
   - `/` → Library
   - `/paper/:id` → PaperDetail
   - `/projects` → Projects
   - `/people` → People
   - `/explore` → Explore

7. Add a nav bar placeholder.

## Done when
- [ ] `npm run dev` starts on localhost:5173
- [ ] Page loads without console errors
- [ ] `GET /health` call from frontend succeeds (CORS must be enabled on backend)
- [ ] React Router navigation between pages works

## Backend CORS update (part of this task)
Add to `backend/main.py`:
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], ...)
```

## Tests
- Manual: open browser, click nav links, no errors in console
- Automated: not needed for setup
