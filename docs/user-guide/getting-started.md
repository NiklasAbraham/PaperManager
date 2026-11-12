# Local development

This page sets PaperManager up from source, with the backend and frontend running directly on
your machine so code changes show up immediately. To simply **use** PaperManager, the Docker
setup in [Hosting your own](../self_hosting.md) is quicker.

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Use conda or pyenv |
| Node.js | 18+ | For the frontend |
| Neo4j | 5.x | Local Docker container (below) or a free AuraDB instance |
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
NEO4J_URI=bolt://localhost:7687
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

### Neo4j setup

The quickest option is a local container:

```bash
docker run -d --name papermanager-neo4j -p 7687:7687 -p 7474:7474 \
  -e NEO4J_AUTH=neo4j/change-me neo4j:5
```

Then set `NEO4J_URI=bolt://localhost:7687`, `NEO4J_USER=neo4j` and `NEO4J_PASSWORD=change-me`
in `.env`. A free [AuraDB](https://console.neo4j.io) instance works too: copy its
`neo4j+s://` URI and credentials instead.

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

## Demo data

To try the app before adding your own papers, load the demo library into your **local**
development database:

```bash
cd backend
python scripts/seed_demo.py                  # your login (DEFAULT_USER_NAME) joins the demo projects
python scripts/seed_demo.py --member alice   # or name the login(s) that should see them
```

It adds ten well-known papers (Attention Is All You Need, DDPM, Score SDE, EDM, Flow Matching,
AlphaFold 2 and 3, RFdiffusion, ESM-2 and a GNN survey) with their authors, topics, tags and
citations, two projects, notes with `@mentions` and `#topics`, claims, a project concept map and a
conversation. It is the same data the tests use (`backend/tests/fixtures/demo_library.json`).
The script only adds data, does nothing when the demo is already loaded, and refuses a Neo4j
that is not on this machine unless you pass `--force`.

---

## Running the tests

```bash
backend/scripts/run_tests.sh                          # everything except @integration tests
backend/scripts/run_tests.sh -q tests/test_search.py  # any pytest arguments
```

The script starts a throwaway Neo4j and runs pytest in a one-off container of the backend image
(build it first with `docker compose build backend`), on a Docker network with no route to the
internet, then removes both. Your `.env` is not used. Tests that would reach an outside service
fail and name the host; tests that really need one (Anthropic, Google Drive) are marked
`@pytest.mark.integration` and are left out by default.

Tests write to the database, so they refuse to run against a Neo4j that is not on this machine
unless `PM_TESTS_ALLOW_DB=1` says it is disposable. Never point them at your real library.
Tests that need a populated graph use the `demo_library` fixture, which empties the test
database and loads the demo library.

---

## What's Next?

- [First steps](first-steps.md) — one paper from upload to concept map
- [Ingest your first paper](ingestion.md) — drag a PDF or paste a URL
- [Browse the library](library.md) — search, filter, sort your papers
- [Chat with a paper](paper-detail.md#chat-with-paper) — ask Claude questions about any paper
- [Explore the knowledge graph](graph.md) — visualise connections
