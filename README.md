# PaperManager

A personal academic paper manager. Upload PDFs, ingest papers from URLs, chat with papers using AI, explore a knowledge graph of authors and topics, and use built-in login with admin-managed users.

> Full documentation: [https://niklasabraham.github.io/PaperManager/](https://niklasabraham.github.io/PaperManager/)

---

## Quick Start

```bash
# 1. Clone and enter
git clone <repo> && cd PaperManager

# 2. Create conda env
conda create -n papermanager python=3.11 -y
conda activate papermanager
pip install -r backend/requirements.txt

# 3. Install frontend
cd frontend && npm install && cd ..

# 4. Configure
cp .env.example .env
# Fill in: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
#          GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_DRIVE_FOLDER_ID,
#          ANTHROPIC_API_KEY, JWT_SECRET_KEY

# 5. Start everything
./start.sh
# Backend: http://localhost:8000  |  Frontend: http://localhost:5173

# 6. Create the admin user
cd backend && python scripts/create_default_user.py && cd ..
```

---

## Developer Context

All in-depth context files for working on this codebase live in [.specs/](.specs/):

| File | Contents |
|---|---|
| [000_general.md](.specs/000_general.md) | Overview, tech stack, env vars, quick start |
| [001_architecture.md](.specs/001_architecture.md) | Module map, design decisions, ingestion flow |
| [002_data_model.md](.specs/002_data_model.md) | Neo4j graph schema — all nodes, relationships, indexes |
| [003_ingestion.md](.specs/003_ingestion.md) | PDF upload, URL ingest, bulk import, reference import |
| [004_ai_pipelines.md](.specs/004_ai_pipelines.md) | All AI models and pipelines |
| [005_knowledge_chat.md](.specs/005_knowledge_chat.md) | Knowledge chat pipeline in depth |
| [006_api.md](.specs/006_api.md) | Full API reference |
| [007_deployment.md](.specs/007_deployment.md) | Docker / production deployment |
| [008_mcp_server.md](.specs/008_mcp_server.md) | MCP server for Claude Desktop |

---

## User Documentation

Browse the full user guide in [docs/](docs/) or at the hosted docs site above.

| Section | Location |
|---|---|
| Getting Started | [docs/user-guide/getting-started.md](docs/user-guide/getting-started.md) |
| Ingesting Papers | [docs/user-guide/ingestion.md](docs/user-guide/ingestion.md) |
| Library | [docs/user-guide/library.md](docs/user-guide/library.md) |
| Paper Detail | [docs/user-guide/paper-detail.md](docs/user-guide/paper-detail.md) |
| Knowledge Features | [docs/user-guide/knowledge-features.md](docs/user-guide/knowledge-features.md) |
| MCP Server | [docs/user-guide/mcp-server.md](docs/user-guide/mcp-server.md) |
| Architecture | [docs/technical/architecture.md](docs/technical/architecture.md) |
| Data Model | [docs/technical/data-model.md](docs/technical/data-model.md) |
| AI Pipelines | [docs/technical/ai-pipelines.md](docs/technical/ai-pipelines.md) |
