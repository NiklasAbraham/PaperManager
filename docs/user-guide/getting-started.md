# Getting Started

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Use conda or pyenv |
| Node.js | 18+ | For the frontend |
| Neo4j Aura | Free tier | Cloud-hosted graph DB |
| Google account | — | Google Drive for PDF storage |
| Anthropic API key | — | Claude for summaries & chat |
| Ollama (optional) | latest | Local AI for metadata extraction |

---

## Installation

### 1 — Clone the repository

```bash
git clone https://github.com/NiklasAbraham/PaperManager
cd PaperManager
```

### 2 — Set up the Python environment

```bash
conda create -n papermanager python=3.11 -y
conda activate papermanager
pip install -r backend/requirements.txt
```

### 3 — Install the frontend

```bash
cd frontend
npm install
cd ..
```

### 4 — Install Ollama (optional, recommended)

Ollama is used for local metadata extraction (layer 2), tag suggestions, Cypher assist, and figure captions. Without it the system still works using Semantic Scholar and Claude.

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Pull the model
ollama pull llama3.2:3b
```

---

## Configuration

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# ── Neo4j ──────────────────────────────────────────────────────
NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password

# ── Google Drive ───────────────────────────────────────────────
# OAuth desktop app credentials from Google Cloud Console
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxx
GOOGLE_DRIVE_FOLDER_ID=xxxx   # Folder where PDFs will be stored

# ── Anthropic ─────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-xxxx

# Anthropic Foundry enterprise gateway (optional)
ANTHROPIC_WORK_API_KEY=xxxx
ANTHROPIC_WORK_BASE_URL=https://your-foundry-gateway.com/...

# ── App ────────────────────────────────────────────────────────
BACKEND_PORT=8000
FRONTEND_URL=http://localhost:5173

# ── Ollama ─────────────────────────────────────────────────────
OLLAMA_MODEL=llama3.2:3b

# ── Corporate network (optional) ──────────────────────────────
SSL_VERIFY=true
SSL_CA_BUNDLE=/path/to/corporate-ca.pem
```

### Neo4j Aura setup

1. Go to [https://neo4j.com/cloud/platform/aura-graph-database/](https://neo4j.com/cloud/platform/aura-graph-database/)
2. Create a free AuraDB instance
3. Copy the connection URI, username, and password into `.env`

### Google Drive setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the **Google Drive API**
3. Create **OAuth 2.0 credentials** (Desktop application type)
4. Download the credentials JSON
5. On first backend start, a browser window opens for OAuth authorisation
6. Credentials are saved to `backend/token.json` and reused automatically

---

## Starting the Application

```bash
./start.sh
```

This script:

- Starts the **FastAPI backend** on port 8000 (logs → `/tmp/papermanager-backend.log`)
- Starts the **Vite frontend** on port 5173 (logs → `/tmp/papermanager-frontend.log`)
- Optionally starts **Ollama** if configured

Open [http://localhost:5173](http://localhost:5173) in your browser.

!!! tip "Checking logs"
    ```bash
    tail -f /tmp/papermanager-backend.log
    tail -f /tmp/papermanager-frontend.log
    ```

---

## First Run

On startup the backend automatically:

1. Verifies the Neo4j connection
2. Runs schema setup (creates indexes and constraints)
3. Seeds 157 default tags across source, workflow, content, and domain categories

You should see the library page with a drop zone and a **+** button to add papers.

---

## What's Next?

- [Ingest your first paper](ingestion.md) — drag a PDF or paste a URL
- [Browse the library](library.md) — search, filter, sort your papers
- [Chat with a paper](paper-detail.md#chat-with-paper) — ask Claude questions about any paper
- [Explore the knowledge graph](knowledge-features.md#knowledge-graph) — visualise connections
