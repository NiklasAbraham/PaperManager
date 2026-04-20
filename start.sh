#!/usr/bin/env bash
set -e

PROJECT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/Users/M350238/miniforge3/envs/papermanager/bin/python"
FRONTEND="$PROJECT/frontend"
BACKEND="$PROJECT/backend"

# Make sure Homebrew-installed binaries (node, npm, ollama) are on PATH
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# ── colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${GREEN}[start]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
error() { echo -e "${RED}[error]${NC} $*"; exit 1; }

# ── pre-flight checks ─────────────────────────────────────────────────────────
[ -f "$PYTHON" ]              || error "Python env not found at $PYTHON"
[ -d "$FRONTEND/node_modules" ] || error "Frontend deps missing — run: cd frontend && npm install"
command -v npm &>/dev/null    || error "npm not found — install Node.js via: brew install node"

# ── Ollama (optional) ─────────────────────────────────────────────────────────
if command -v ollama &>/dev/null; then
  if ! pgrep -x ollama &>/dev/null; then
    info "Starting Ollama..."
    ollama serve &>/tmp/ollama.log &
    sleep 2
  else
    info "Ollama already running."
  fi
  if ! ollama list 2>/dev/null | grep -q "llama3.2:3b"; then
    info "Pulling llama3.2:3b (first-time only, may take a while)..."
    ollama pull llama3.2:3b
  fi
else
  warn "Ollama not found — metadata extraction will use heuristics only."
fi

# ── Backend ───────────────────────────────────────────────────────────────────
info "Starting backend..."
cd "$BACKEND"
# Process substitution: logs go to terminal AND the log file simultaneously
"$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload \
  > >(tee /tmp/papermanager-backend.log) 2>&1 &
BACKEND_PID=$!

# Wait until backend is accepting connections (max 15s)
info "Waiting for backend to be ready..."
for i in $(seq 1 15); do
  if curl -sf http://localhost:8000/health &>/dev/null; then
    info "Backend ready."
    break
  fi
  sleep 1
done

# ── Frontend ──────────────────────────────────────────────────────────────────
info "Starting frontend..."
cd "$FRONTEND"
# Frontend (Vite) logs to file only — terminal stays readable for backend logs
npm run dev &>/tmp/papermanager-frontend.log &
FRONTEND_PID=$!

# Wait until Vite is up (max 15s)
info "Waiting for frontend to be ready..."
for i in $(seq 1 15); do
  if curl -sf http://localhost:5173 &>/dev/null; then
    break
  fi
  sleep 1
done

# ── Open browser ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  PaperManager is running!${NC}"
echo -e "  ${GREEN}→ http://localhost:5173${NC}"
echo ""
echo "  Backend logs:  tail -f /tmp/papermanager-backend.log"
echo "  Frontend logs: tail -f /tmp/papermanager-frontend.log"
echo "  App logs:      tail -f $PROJECT/logs/app.log"
echo ""
echo "  Press Ctrl+C to stop all services."
echo ""

open "http://localhost:5173" 2>/dev/null || true

# ── Wait / cleanup ────────────────────────────────────────────────────────────
trap "
  echo '';
  info 'Shutting down...';
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null;
  exit 0
" INT TERM

wait
