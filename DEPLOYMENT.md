# PaperManager Production Deployment

This directory contains the production deployment configuration for PaperManager using Docker Compose with Traefik reverse proxy.

## Prerequisites

- Docker and Docker Compose installed on your server
- Traefik proxy running on the `proxy` network
- Domain `niklas-abraham.de` pointing to your server

## Architecture

The deployment consists of three services:

1. **Neo4j Database** - Graph database for storing papers, people, and relationships
2. **Backend (FastAPI)** - Python API server running on port 8000 (internal)
3. **Frontend (React + Nginx)** - Static frontend served by Nginx on port 80 (exposed via Traefik)

## Setup

### 1. Configure Environment Variables

Edit `.env` file and set your API keys:

```bash
# Required: Add your Anthropic API key
ANTHROPIC_API_KEY=your_api_key_here

# Optional: Configure other services as needed
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

The Neo4j password has been pre-generated: `Yrq/+quulIR3ESs9906w+NcW7kmdnOM0M4t3Z0k06tE=`

### 2. Build and Start Services

```bash
# Build and start all services
docker-compose up -d --build

# Check logs
docker-compose logs -f

# Check status
docker-compose ps
```

### 3. Verify Deployment

- Visit https://niklas-abraham.de to access the frontend
- Check health: https://niklas-abraham.de/health
- API docs: https://niklas-abraham.de/docs
- Neo4j Browser (if exposed): http://your-server:7474

### 4. Initial Data Setup

If you need to import existing data:

```bash
# Access the backend container
docker-compose exec backend bash

# Run any initialization scripts
python scripts/backfill_user_niklas.py
```

## Management Commands

```bash
# Stop all services
docker-compose stop

# Restart services
docker-compose restart

# View logs
docker-compose logs -f [service_name]

# Update and rebuild
docker-compose down
docker-compose up -d --build

# Remove everything (including data)
docker-compose down -v
```

## Data Persistence

The following volumes are created for data persistence:

- `neo4j_data` - Database files
- `neo4j_logs` - Database logs
- `neo4j_import` - Import directory
- `neo4j_plugins` - APOC and other plugins
- `backend_data` - Backend application data

## Troubleshooting

### Frontend can't reach backend

Check that all services are on the correct networks:
```bash
docker-compose ps
docker network inspect papermanager
docker network inspect proxy
```

### Neo4j connection issues

Check Neo4j logs:
```bash
docker-compose logs neo4j
```

Verify connectivity from backend:
```bash
docker-compose exec backend bash
pip install neo4j
python -c "from neo4j import GraphDatabase; driver = GraphDatabase.driver('bolt://neo4j:7687', auth=('neo4j', 'YOUR_PASSWORD')); driver.verify_connectivity()"
```

### SSL/Certificate issues

The Traefik proxy handles SSL certificates automatically via Let's Encrypt.

## Security Notes

- Neo4j is only accessible from the internal `papermanager` network
- Backend is only accessible from the internal network and via Nginx proxy
- Only the frontend (Nginx) is exposed to the internet via Traefik
- The `.env` file contains sensitive credentials - keep it secure and never commit it to git
