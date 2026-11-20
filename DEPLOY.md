# Set up PaperManager with your coding agent

**For people:** you don't need to read this file. Open a coding agent (Claude Code, Codex, Cursor,
or similar) in an empty folder or in this repository and say:

> Set up PaperManager for me by following
> https://github.com/NiklasAbraham/PaperManager/blob/main/DEPLOY.md

The agent asks you a few questions, writes the settings file, starts the app with Docker and
checks that it works. You type your password into your own terminal. Plan for about 15 minutes,
most of it the first Docker build. You need Docker and one AI key (Anthropic or OpenAI).

---

**For the agent:** the rest of this file is your runbook. Follow it step by step.

## Ground rules

- **Ask before acting, one topic at a time.** Use your question tool if you have one (Claude Code:
  AskUserQuestion), otherwise ask in plain text. Offer the recommended answer first, then wait.
  Keep each message short. The user may not be technical.
- **Secrets stay out of the chat.** Generate passwords and JWT secrets yourself and write them
  straight into `.env`. Never echo secrets back. Let the user paste API keys into `.env`
  themselves (open the file for them or tell them the exact line). If they paste a key into the
  chat anyway, write it into `.env` and don't repeat it.
- **Never commit or push `.env`**, `backend/credentials.json` or `backend/token.json`. They are
  git-ignored. Keep it that way.
- **Use `docker-compose.selfhost.yml`.** Never use `docker-compose.example.yml` (the maintainer's
  server) or `docker-compose.yml`.
- **Never run `docker compose ... down -v`** or delete Docker volumes. They hold the user's
  library.
- Before each long-running step, tell the user what it does and how long it takes.
- If a step fails, read the logs, fix what you can and explain the rest in plain words. Don't
  move on with a broken setup.

## Step 1: check the machine

Run these and summarise the result in one or two sentences:

```bash
git --version
docker --version && docker compose version     # Compose v2 is required ("docker compose", not "docker-compose")
docker info --format '{{.ServerVersion}} {{.MemTotal}}'   # fails when the Docker daemon is not running
```

- **No Docker:** point the user to [Docker Desktop](https://docs.docker.com/get-docker/) (macOS,
  Windows) or `curl -fsSL https://get.docker.com | sh` (Linux, needs sudo). Ask before
  installing anything. Wait until `docker info` works.
- **Docker installed but not running:** ask the user to start Docker Desktop.
- **Under 4 GB of memory for Docker:** warn that PDF processing needs about 2 GB, and that
  Docker Desktop can give it more under *Settings → Resources*.
- **Not inside the repository yet:** clone it, then `cd` into it. Check for a `DEPLOY.md` and a
  `docker-compose.selfhost.yml`.

  ```bash
  git clone https://github.com/NiklasAbraham/PaperManager.git && cd PaperManager
  ```

- **`.env` already exists:** this is a re-run. Ask whether to keep the current settings and only
  change some (default), or start over. Never overwrite the existing `NEO4J_PASSWORD`: the
  database was created with it.

## Step 2: interview

Ask these in order. Each answer becomes one or more lines in `.env` (step 3).

**Q1. Login name.** "What name do you want to log in with?" Suggest their first name in lower
case. → `DEFAULT_USER_NAME`

**Q2. AI provider.** "Which AI account do you have? One is enough."

| Answer | `.env` | What the app then uses |
|---|---|---|
| Anthropic (recommended) | `ANTHROPIC_API_KEY=` | Claude Haiku 4.5 for summaries, topics, claims and the concept map; Claude Sonnet/Opus for chat and concept visualisations |
| OpenAI | `OPENAI_API_KEY=` | GPT-5 mini for summaries and chat. The concept visualisations need an Anthropic key and the quick tour needs a Claude subscription, so these two stay off |
| Both | both keys | Haiku for the fast tasks, Claude for chat (set `AI_PROVIDER=openai` to use GPT-5 mini for the fast tasks instead) |
| Own OpenAI-compatible server (LiteLLM, OpenRouter, Ollama, vLLM) | `LITELLM_ENDPOINT`, `LITELLM_API_KEY`, `LITELLM_MODEL` | that model for the fast tasks |
| None yet | nothing | Explain where to get a key: [console.anthropic.com](https://console.anthropic.com) → *API keys* (pay as you go; summaries usually cost about a cent per paper) or [platform.openai.com](https://platform.openai.com/api-keys). The app runs without a key, but summaries and chat are off until one is added |

Leave `AI_PROVIDER=auto` and `FAST_MODEL=` empty unless the user asks for a specific model.
Don't ask about models otherwise: the defaults are chosen for cost and quality.

**Q3. Where to keep PDFs.**

- **On this computer (recommended):** `STORAGE_BACKEND=local`. Files go into the Docker volume
  `paper_files`. No other accounts needed.
- **Google Drive:** `STORAGE_BACKEND=drive`. This needs a Google Cloud OAuth client, about 10
  minutes of clicking. Walk the user through step 2 of
  [docs/self_hosting.md](docs/self_hosting.md). Then uncomment the two `credentials.json` /
  `token.json` lines under `volumes:` in `docker-compose.selfhost.yml`. Only offer this if the
  user wants their PDFs in Drive.

**Q4. Accent colour.** "Pick an accent colour for the app: violet (default), blue, teal, green,
amber, rose or slate. Or give any hex colour, like your lab's or company's colour."
→ `UI_ACCENT`. The app applies it at load time, with no rebuild.

**Q5. Port.** Check whether port 8080 is free, using `lsof -i :8080`, `ss -ltn | grep :8080` or,
on Windows, `netstat -ano | findstr :8080`. If it is free, don't ask: use it. If it is taken,
suggest 8090 → `PM_PORT`.

**Q6. Only if they mentioned a Claude Pro/Max subscription:** "Do you want the app to use your
Claude subscription for the quick tour and the Claude Code chat option?" If yes: they run
`claude setup-token` in their own terminal and paste the token into `CLAUDE_CODE_OAUTH_TOKEN`.
You set `CLAUDE_CODE_USERS=<their login name>`. Only the subscription owner may be listed.
Otherwise skip this question.

Finish with a three-line summary of the choices and ask "Shall I set it up like this?"

## Step 3: write `.env`

```bash
cp .env.example .env
```

Then set the values with your file-editing tool, not with `sed` on secrets:

| Key | Value |
|---|---|
| `DEFAULT_USER_NAME` | Q1 |
| `JWT_SECRET_KEY` | generate: `openssl rand -hex 32` (or `python3 -c "import secrets; print(secrets.token_hex(32))"`) |
| `NEO4J_PASSWORD` | generate the same way, e.g. `openssl rand -hex 24` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `LITELLM_*` | Q2, pasted by the user |
| `STORAGE_BACKEND` | Q3: `local` or `drive` (and `GOOGLE_DRIVE_FOLDER_ID` for Drive) |
| `UI_ACCENT` | Q4 |
| `PM_PORT` | Q5 |
| `CLAUDE_CODE_USERS`, `CLAUDE_CODE_OAUTH_TOKEN` | Q6, else empty |

Keep every comment on its own line. Docker reads `KEY=   # note` as the value `# note`.

For the API key: open `.env` in the user's editor, or tell them "open `.env` and paste your key
after `ANTHROPIC_API_KEY=`". Then confirm that the line is filled without printing the key, e.g.
`grep -c '^ANTHROPIC_API_KEY=.' .env` → `1`.

## Step 4: build and start

Tell the user: "Building the app takes about 10 minutes the first time."

```bash
docker compose -f docker-compose.selfhost.yml up -d --build
```

Wait until the backend is up. Poll; don't stream logs forever:

```bash
docker compose -f docker-compose.selfhost.yml logs --tail=50 app     # look for "Application startup complete"
curl -sf http://localhost:${PM_PORT:-8080}/health                     # {"status":"ok","neo4j":"connected"}
```

Neo4j needs about 30 seconds after its first start. If `/health` reports `neo4j` as
`unreachable`, wait and try again. If it still fails after 2 minutes, run
`docker compose -f docker-compose.selfhost.yml restart app`.

## Step 5: the user sets their password

The password must not pass through you. Ask the user to run this in their own terminal, inside
the `PaperManager` folder. In Claude Code they can type it after a `!` in the prompt:

```bash
docker compose -f docker-compose.selfhost.yml exec app python scripts/create_default_user.py
```

It asks for a password (at least 8 characters) twice.

## Step 6: check everything

```bash
docker compose -f docker-compose.selfhost.yml exec app python scripts/check_setup.py
```

Every required line must show `[ok  ]`. Each `FAIL` line says what is missing; fix it and run the
check again. The check sends one tiny test message to the AI provider. If that fails with an
authentication error, the key in `.env` is wrong. After any `.env` change, run
`docker compose -f docker-compose.selfhost.yml up -d` (it recreates the app with the new values),
then check again.

## Step 7: hand over

Tell the user, briefly:

1. Open **http://localhost:8080** (or their port) and log in with their name and password.
2. Drag a PDF onto the library, or paste an arXiv link. The summary appears after a minute.
3. Open the paper, then try **Chat** and, with Anthropic, the **Concepts** tab.
4. A short guide: [First steps](docs/user-guide/first-steps.md).

Then the everyday commands:

| To | Run |
|---|---|
| Stop | `docker compose -f docker-compose.selfhost.yml down` (the library is kept) |
| Start again | `docker compose -f docker-compose.selfhost.yml up -d` |
| Change a setting | edit `.env`, then `docker compose -f docker-compose.selfhost.yml up -d` |
| Update to the latest version | `git pull && docker compose -f docker-compose.selfhost.yml up -d --build` |

Do not switch on the optional features unless the user asks: the paper feed (`PAPER_FEED=true`,
[docs/user-guide/paper-feed.md](docs/user-guide/paper-feed.md)) and another embedding model
(`EMBED_MODEL`, [docs/user-guide/switching-the-embedding-model.md](docs/user-guide/switching-the-embedding-model.md)).
Their data goes to `/app/data/feed` and `/app/data/vectors` on the `paper_files` volume, which the compose
file already sets up. Never delete that volume.

Offer one optional extra: **connect PaperManager to their agent** through the MCP server, so the
agent can search and annotate the library. See [docs/user-guide/mcp-server.md](docs/user-guide/mcp-server.md).
The MCP command is `docker exec -i <app container> python mcp_server.py`. Get the container
name from `docker compose -f docker-compose.selfhost.yml ps` (usually `papermanager-app-1`).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `port is already allocated` | Set another `PM_PORT` in `.env`, then `up -d` |
| Build stops with "killed" or exit code 137 | Docker is out of memory: give it at least 4 GB |
| `400 Invalid host header` | Open the app at `localhost` or `127.0.0.1`, not at the machine's IP. For other host names, add them to `TRUSTED_HOSTS` in `docker-compose.selfhost.yml` |
| Summary says "could not be generated" | `check_setup.py` shows the provider error. Usually the key is wrong or the account has no credit |
| "Personal Anthropic key is not configured" in chat | No `ANTHROPIC_API_KEY`: use the fast-model option in the chat's model menu, or add a key |
| `ServiceUnavailable` / Neo4j errors | Neo4j is still starting; wait 30 s. If you changed `NEO4J_PASSWORD` after the first start, set it back: the database keeps its first password |
| Apple Silicon build is slow | Normal for the first build (PyTorch). Later builds use the cache |

Hosting on a server or on Heroku instead of this computer: see [docs/self_hosting.md](docs/self_hosting.md).
