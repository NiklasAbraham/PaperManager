#!/usr/bin/env bash
set -e

PROJECT="$(cd "$(dirname "$0")" && pwd)"
FRONTEND="$PROJECT/frontend"
BACKEND="$PROJECT/backend"

resolve_python() {
  if [ -n "${PAPERMANAGER_PYTHON:-}" ] && [ -x "$PAPERMANAGER_PYTHON" ]; then
    printf '%s\n' "$PAPERMANAGER_PYTHON"
    return 0
  fi

  if [ -n "${CONDA_PREFIX:-}" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
    printf '%s\n' "$CONDA_PREFIX/bin/python"
    return 0
  fi

  for candidate in "$PROJECT/.venv/bin/python" "$PROJECT/venv/bin/python"; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  if command -v python3 &>/dev/null; then
    command -v python3
    return 0
  fi

  return 1
}

PYTHON="$(resolve_python || true)"

# Make sure Homebrew-installed binaries (node, npm) are on PATH
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# ── colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${GREEN}[start]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
error() { echo -e "${RED}[error]${NC} $*"; exit 1; }

# ── pre-flight checks ─────────────────────────────────────────────────────────
[ -n "$PYTHON" ] && [ -x "$PYTHON" ] || error "Python interpreter not found. Set PAPERMANAGER_PYTHON, activate your conda env, create .venv, or install python3."
[ -d "$FRONTEND/node_modules" ] || error "Frontend deps missing — run: cd frontend && npm install"
command -v npm &>/dev/null    || error "npm not found — install Node.js via: brew install node"

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
