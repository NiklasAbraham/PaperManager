# Hosting your own PaperManager

!!! tip "Easiest: let your coding agent do it"
    Tell Claude Code, Codex or another coding agent: *"Set up PaperManager for me by following
    https://github.com/NiklasAbraham/PaperManager/blob/main/DEPLOY.md"*. It asks a few questions
    and runs the local setup below for you. See [Set up with your agent](agent-setup.md).

This guide sets up your own instance with your own database and your own keys. You can run it on
your own computer (localhost) or on Heroku. Both use the same container image,
`Dockerfile.selfhost`. It holds the React frontend, served by nginx, and the FastAPI backend, and
serves both from one port. The login cookie only works when the page and the API come from the
same origin, so they share that port.

`docker-compose.example.yml` mirrors the maintainer's production stack (Traefik, his domain,
a remote GPU machine). Don't use it. Use `docker-compose.selfhost.yml` or `heroku.yml`.

## What you need

| Thing | Required? | Used for |
|---|---|---|
| Git and Docker (Docker Desktop on macOS/Windows) | yes | building and running the app |
| An Anthropic API key ([console.anthropic.com](https://console.anthropic.com)) **or** an OpenAI API key ([platform.openai.com](https://platform.openai.com/api-keys)) | one of them | summaries, topics, chat. With Anthropic the fast tasks run on Claude Haiku 4.5; with OpenAI everything runs on GPT-5 mini |
| A Google account plus a Google Cloud project | only for Drive storage, and always on Heroku | PDFs in Google Drive. Locally, `STORAGE_BACKEND=local` keeps them in a Docker volume |
| An OpenAI-compatible endpoint (LiteLLM, OpenRouter, Ollama) | optional | runs the fast tasks on your own model |
| A Heroku account plus the Heroku CLI | only for Heroku | hosting |
| A Neo4j AuraDB Free instance ([console.neo4j.io](https://console.neo4j.io)) | only for Heroku | the database (locally, Docker runs Neo4j for you) |

Expect around 2 GB of RAM for the app container. The PDF layout model (Docling) runs inside it
and loads PyTorch.

## Step 1: get the code and create `.env`

```bash
git clone https://github.com/NiklasAbraham/PaperManager.git
cd PaperManager
cp .env.example .env
```

Edit `.env`. Keep it private, since it is your secrets file and is git-ignored. Change these
values and leave everything else at its default:

```bash
NEO4J_PASSWORD=<any long random string>        # locally: Docker creates the DB with this password
JWT_SECRET_KEY=<output of: openssl rand -hex 32>
DEFAULT_USER_NAME=<your login name>             # the owner/admin account
DEFAULT_USER_PASSWORD=                          # leave empty; you set it in step 4
ANTHROPIC_API_KEY=sk-ant-...                    # or OPENAI_API_KEY=sk-...
STORAGE_BACKEND=local                           # or drive, with GOOGLE_DRIVE_FOLDER_ID from step 2
UI_ACCENT=violet                                # or blue, teal, green, amber, rose, slate, #RRGGBB

# The maintainer's private infrastructure: switch it off
DOCLING_MODE=local
INFERENCE_MANAGER_URL=
HERMIONE_HOST=
LITELLM_ENDPOINT=
LITELLM_EMBED_MODEL=
```

Keep comments on their own line in the real file: Docker reads `KEY=   # note` as the value
`# note`. The comments above are only there to explain each line.

For your own model on the fast tasks, point LiteLLM at any OpenAI-compatible API, for example
`LITELLM_ENDPOINT=https://openrouter.ai/api/v1`, `LITELLM_API_KEY=<openrouter key>`,
`LITELLM_MODEL=google/gemma-3-27b-it`.

Leave `CLAUDE_CODE_USERS` and `CLAUDE_CODE_OAUTH_TOKEN` empty. That feature runs chats on the
server owner's personal Claude subscription, and only the owner may use it. If you have your own
Claude Pro/Max plan and want it for yourself, set `CLAUDE_CODE_USERS=<your login name>`. Then put
the output of `claude setup-token` (from [Claude Code](https://claude.com/claude-code)) into
`CLAUDE_CODE_OAUTH_TOKEN`. Never list other people there.

## Step 2: Google Drive access (once, on your own computer)

Skip this step locally with `STORAGE_BACKEND=local`. On Heroku it is required, because Heroku
has no disk to keep files on. For Drive locally, also uncomment the two `credentials.json` /
`token.json` lines in `docker-compose.selfhost.yml`.

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project.
   Open **APIs & Services → Library**, then enable the **Google Drive API**.
2. Open **APIs & Services → OAuth consent screen**. Choose user type *External*, fill in the
   app name and your e-mail, and add yourself as a *test user*.
3. Open **APIs & Services → Credentials → Create credentials → OAuth client ID**, with application
   type **Desktop app**. Download the JSON and save it as `backend/credentials.json`.
4. In Google Drive, create a folder for the PDFs. Its ID is the last part of the folder URL
   (`https://drive.google.com/drive/folders/<THIS>`). Put it into `GOOGLE_DRIVE_FOLDER_ID`.
5. Create the login token. A browser window opens; log in and allow access:

   ```bash
   python3 -m venv .venv-drive
   .venv-drive/bin/pip install google-auth-oauthlib google-api-python-client
   .venv-drive/bin/python backend/scripts/setup_drive_oauth.py
   ```

   This writes `backend/token.json`. Both `credentials.json` and `token.json` are git-ignored.
   Never commit them.

## Step 3a: run on localhost

```bash
docker compose -f docker-compose.selfhost.yml up -d --build   # first build takes ~10 min
docker compose -f docker-compose.selfhost.yml logs -f app      # wait for "Application startup complete"
```

Create your account (step 4), then open **http://localhost:8080**.

- Stop: `docker compose -f docker-compose.selfhost.yml down`. Your data stays in the `neo4j_data`
  volume (the graph) and the `paper_files` volume (PDFs, figures, conference datasets, and under
  `/app/data` the embedding vectors in `vectors/` and, with the paper feed on, `feed/`). `down -v`
  deletes both.
- Update: `git pull`, then run the `up -d --build` command again.

### Optional: paper feed and embedding model

Both are off or default unless you set them in `.env` (then `up -d` again):

- `PAPER_FEED=true` switches on the [paper feed](user-guide/paper-feed.md), a digest of new preprints
  ranked by your library. Its database lives in `PAPER_FEED_DIR`.
- `EMBED_MODEL` chooses the model behind library search, the feed and
  [similar papers](user-guide/similar-search.md). The default `BAAI/bge-small-en-v1.5` needs nothing
  more; for another one, and for doing the re-embedding on a GPU machine, see
  [Switching the embedding model](user-guide/switching-the-embedding-model.md).

`docker-compose.selfhost.yml` already points `PAPER_FEED_DIR` (`/app/data/feed`) and `VECTOR_STORE_DIR`
(`/app/data/vectors`) at the `paper_files` volume, so both survive a rebuild. If you run the backend
some other way, put both folders (and `CONFERENCE_DATA_DIR`) on a persistent disk.

## Step 3b: run on Heroku

Heroku has no free tier and no persistent disk, so the database lives on Neo4j AuraDB Free.

1. Create an AuraDB Free instance at [console.neo4j.io](https://console.neo4j.io). Save the
   generated password. Note the connection URI (`neo4j+s://xxxx.databases.neo4j.io`).
2. Create the app and switch it to container builds:

   ```bash
   heroku login
   heroku create <app-name>                  # e.g. papers-alex → https://papers-alex-xxxx.herokuapp.com
   heroku stack:set container -a <app-name>
   ```

3. Set the configuration. Use the same values as in `.env`, plus the Heroku-specific ones:

   ```bash
   APP_HOST=<app-name>-xxxx.herokuapp.com    # the host from `heroku apps:info -a <app-name>`
   heroku config:set -a <app-name> \
     NEO4J_URI='neo4j+s://xxxx.databases.neo4j.io' NEO4J_USER=neo4j NEO4J_PASSWORD='<aura password>' \
     JWT_SECRET_KEY="$(openssl rand -hex 32)" DEFAULT_USER_NAME='<your login name>' \
     ANTHROPIC_API_KEY='sk-ant-...' \
     GOOGLE_DRIVE_FOLDER_ID='<folder id>' \
     GOOGLE_CLIENT_ID='<client_id from credentials.json>' \
     GOOGLE_CLIENT_SECRET='<client_secret from credentials.json>' \
     GOOGLE_TOKEN_JSON="$(cat backend/token.json)" \
     DOCLING_MODE=local INFERENCE_MANAGER_URL= HERMIONE_HOST= LITELLM_ENDPOINT= LITELLM_EMBED_MODEL= \
     FRONTEND_URL="https://$APP_HOST" TRUSTED_HOSTS="$APP_HOST" TRUST_PROXY_HEADERS=true
   ```

   Heroku has no disk to keep `token.json` on, so `GOOGLE_TOKEN_JSON` passes its contents as a
   variable. `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are inside `backend/credentials.json`.

4. Deploy. `heroku.yml` makes Heroku build `Dockerfile.selfhost`:

   ```bash
   git push heroku main
   heroku ps:type web=standard-2x -a <app-name>   # 1 GB RAM; basic (512 MB) runs out of memory
   heroku logs --tail -a <app-name>               # wait for "Application startup complete"
   ```

   If a PDF upload crashes with "Memory quota exceeded" in the logs, the layout model needs more
   memory. Use `performance-m`. Heroku also cuts every request off after 30 seconds (error
   `H12`). Long PDFs can take longer than that to process, so very large uploads may fail on
   Heroku even though they work locally.

5. Create your account (step 4), then open `https://<APP_HOST>`.

To update: `git pull` from GitHub, then `git push heroku main` again.

Heroku's disk is wiped at every restart. The vectors of the library search are then rebuilt on the
CPU (search answers by keywords until that is done) and the paper feed would lose its ratings and
fetched papers, so leave `PAPER_FEED` off there.

## Step 4: create your account

The account named `DEFAULT_USER_NAME` is the owner and admin. It is also the only account that
uses the server-wide `ANTHROPIC_API_KEY`. Other users you add later enter their own key under
**Settings**.

```bash
# localhost
docker compose -f docker-compose.selfhost.yml exec app python scripts/create_default_user.py
# Heroku
heroku run -a <app-name> python scripts/create_default_user.py
```

The script asks for a password (at least 8 characters).

Log in, then follow [First steps](user-guide/first-steps.md) to add your first paper and try
the tour, the concept map and the chat.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `400 Invalid host header` | `TRUSTED_HOSTS` must list the exact host name you open in the browser |
| Login works but every page says "Session expired" | The page and the API are on different origins. Open the app on the URL you set as `FRONTEND_URL` |
| Upload fails with `Drive upload failed` | `token.json` is missing or expired, or `GOOGLE_DRIVE_FOLDER_ID` is wrong. Re-run step 2.5 (on Heroku, update `GOOGLE_TOKEN_JSON`) |
| Upload hangs or the dyno restarts | Out of memory in the Docling layout model: give the container more RAM |
| `ServiceUnavailable` / Neo4j errors at start | Locally, Neo4j needs ~30 s after the first start; the app retries on restart. On Heroku, check `NEO4J_URI` uses `neo4j+s://` |
| Chat says "Personal Anthropic key is not configured" | Set `ANTHROPIC_API_KEY`, and log in as the `DEFAULT_USER_NAME` account (or enter a key under Settings) |
