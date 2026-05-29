# Deployment

PaperManager is deployed as a Docker Compose stack behind a Traefik reverse proxy.

**Production URL:** `https://niklas-abraham.de`

---

## Stack

| Service | Image | Notes |
|---|---|---|
| `neo4j` | `neo4j:5` | Graph database; internal only (`papermanager` network) |
| `backend` | built from `backend/Dockerfile` | FastAPI on port 8000; internal only |
| `frontend` | built from `frontend/Dockerfile` | Nginx serving React build; exposed via Traefik on port 80 |

Traefik (running separately on the `proxy` network) handles SSL (Let's Encrypt) and routes `niklas-abraham.de` → frontend Nginx, and `/api` → backend.

---

## Prerequisites

- Docker and Docker Compose installed
- Traefik running and attached to the `proxy` network
- Domain `niklas-abraham.de` pointing to the server

---

## Setup

### 1. Environment Variables

Edit `.env` at the project root:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-xxxx
JWT_SECRET_KEY=replace-with-long-random-secret   # keep stable between deploys

# Google Drive
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxx
GOOGLE_DRIVE_FOLDER_ID=xxxx

# Neo4j (password pre-generated in docker-compose.yml)
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<generated>
```

### 2. Build and Start

```bash
docker-compose up -d --build

# Check logs
docker-compose logs -f

# Check status
docker-compose ps
```

### 3. Verify

- Frontend: `https://niklas-abraham.de`
- Health: `https://niklas-abraham.de/health`
- API docs: `https://niklas-abraham.de/docs`

### 4. Initial Data Setup

```bash
# Run initialization scripts inside backend container
docker-compose exec backend bash
python scripts/create_default_user.py
```

---

## Management Commands

```bash
# Stop
docker-compose stop

# Restart
docker-compose restart

# View logs
docker-compose logs -f [backend|frontend|neo4j]

# Update and rebuild
docker-compose down
docker-compose up -d --build

# Remove everything including data volumes (destructive)
docker-compose down -v
```

---

## Data Persistence (Volumes)

| Volume | Content |
|---|---|
| `neo4j_data` | Database files |
| `neo4j_logs` | Database logs |
| `neo4j_import` | Import directory |
| `neo4j_plugins` | APOC and other plugins |
| `backend_data` | Backend application data (token.json, etc.) |

---

## Security

- Neo4j only accessible from internal `papermanager` network
- Backend only accessible from internal network and Nginx proxy
- Only the frontend Nginx is exposed to the internet via Traefik
- SSL certificates managed automatically by Traefik + Let's Encrypt
- API has configurable rate limits; stricter limits on `/auth/login`
- `.env` file contains sensitive credentials — never commit to git

---

## Troubleshooting

### Frontend can't reach backend

```bash
docker-compose ps
docker network inspect papermanager
docker network inspect proxy
```

### Neo4j connection issues

```bash
docker-compose logs neo4j

# Test from backend container
docker-compose exec backend bash
python -c "
from neo4j import GraphDatabase
driver = GraphDatabase.driver('bolt://neo4j:7687', auth=('neo4j', 'YOUR_PASSWORD'))
driver.verify_connectivity()
print('Connected')
"
```

### SSL / Certificate issues

Traefik handles SSL via Let's Encrypt automatically. Check Traefik logs if certificates fail to provision:

```bash
docker logs traefik
```

---

## Dockerfiles

### `backend/Dockerfile`
- Base: `python:3.11-slim`
- Installs system deps (Docling requirements, etc.)
- Copies `requirements.txt`, runs `pip install`
- Exposes port 8000
- CMD: `uvicorn backend.main:app --host 0.0.0.0 --port 8000`

### `frontend/Dockerfile`
- Stage 1: `node:20-alpine` — `npm ci && npm run build`
- Stage 2: `nginx:alpine` — serves `dist/` with `nginx.conf`
- `nginx.conf` proxies `/api` requests to the backend service
