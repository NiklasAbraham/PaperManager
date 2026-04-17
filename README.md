# PaperManager

My private personal paper manager — upload PDFs, auto-extract metadata, take notes, chat with papers, visualise the knowledge graph, and track references.

## Quick start

```bash
./start.sh
```

Opens:
- **Frontend** → http://localhost:5173
- **Backend API** → http://localhost:8000

The script also starts Ollama (if installed) and pulls `llama3.2:3b` on first run.

---

## First-time setup

### 1. Python environment (conda)

```bash
conda create -n papermanager python=3.11
conda activate papermanager
pip install -r backend/requirements.txt
```

### 2. Frontend dependencies

```bash
cd frontend && npm install
```

### 3. Environment variables

Copy and fill in `.env` at the project root:

```
NEO4J_URI=neo4j+s://...
NEO4J_USER=neo4j
NEO4J_PASSWORD=...

GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_DRIVE_FOLDER_ID=...

ANTHROPIC_API_KEY=sk-ant-...

OLLAMA_MODEL=llama3.2:3b   # optional — falls back to heuristics if omitted
```

### 4. Google Drive auth (one-time)

Place `credentials.json` (OAuth desktop app) in `backend/`, then run:

```bash
cd backend
/Users/M350238/miniforge3/envs/papermanager/bin/python -c "from services.drive import upload_pdf"
```

Follow the browser prompt. A `token.json` is saved and auto-refreshed from then on.

### 5. Ollama (optional — improves metadata extraction)

```bash
brew install ollama
ollama pull llama3.2:3b
```

`./start.sh` handles `ollama serve` automatically after this.

---

## Features

| Feature | How to use |
|---|---|
| Upload PDF | Drag & drop on Library page → confirm metadata → upload |
| References | After upload a modal asks which references to save; or use the References tab in paper detail |
| Notes | Notes tab in paper detail — supports `@person` and `#topic` mentions |
| Chat | Chat tab — ask questions about the paper content |
| Graph | Graph page — force-directed view of all nodes and relationships |
| Search | Search bar on Library page — full-text across titles, abstracts, notes |

---

## MCP server (Claude Desktop integration)

```json
// ~/.claude/claude_desktop_config.json
{
  "mcpServers": {
    "paperManager": {
      "command": "/Users/M350238/miniforge3/envs/papermanager/bin/python",
      "args": ["backend/mcp_server.py"],
      "cwd": "/Users/M350238/Desktop/PaperManager"
    }
  }
}
```
