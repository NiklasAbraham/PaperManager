# Set up with your coding agent

The quickest way to your own PaperManager is to let a coding agent install it. This works with
[Claude Code](https://claude.com/claude-code), [Codex](https://github.com/openai/codex), Cursor
and other agents that can run commands on your computer. Open one in any folder and say:

> Set up PaperManager for me by following
> https://github.com/NiklasAbraham/PaperManager/blob/main/DEPLOY.md

[`DEPLOY.md`](https://github.com/NiklasAbraham/PaperManager/blob/main/DEPLOY.md) is a runbook
written for the agent. It tells the agent to:

1. **Check your machine.** Git and Docker must be present and Docker must be running. If
   something is missing, the agent explains how to install it and asks before installing.
2. **Ask you a few questions**, one at a time:
    - your login name
    - which AI account you have: Anthropic, OpenAI, both, or your own OpenAI-compatible server
    - where to keep PDFs: on this computer (default) or in Google Drive
    - an accent colour for the app
3. **Write `.env`.** The agent generates the database password and session secret itself. You
   paste your API key into the file yourself, so it never passes through the chat.
4. **Build and start** the app with Docker. The first build takes about 10 minutes.
5. **Hand you one command** to set your password in your own terminal.
6. **Run `scripts/check_setup.py`.** It checks the database, the AI provider (with one tiny test
   message) and the file storage, then shows the address to open.

## What your answers change

Every answer is stored in `.env`, and the app reads it at startup:

| Answer | Setting | Effect |
|---|---|---|
| Anthropic key | `ANTHROPIC_API_KEY` | Summaries, topics, claims and the concept map run on Claude Haiku 4.5. Chat and concept visualisations use Claude Sonnet/Opus |
| OpenAI key | `OPENAI_API_KEY` | Summaries and chat run on GPT-5 mini |
| Own server | `LITELLM_ENDPOINT`, `LITELLM_MODEL` | Any OpenAI-compatible API (LiteLLM, OpenRouter, Ollama, vLLM) runs the fast tasks |
| PDFs on this computer | `STORAGE_BACKEND=local` | Files go into the Docker volume `paper_files`. No Google account needed |
| PDFs in Drive | `STORAGE_BACKEND=drive` | Files go to a Google Drive folder ([setup](self_hosting.md#step-2-google-drive-access-once-on-your-own-computer)) |
| Accent colour | `UI_ACCENT` | Buttons, links and highlights use your colour (a preset name or any `#RRGGBB`) |

`AI_PROVIDER=auto` uses the first configured provider in this order: your own server, then
Anthropic, then OpenAI. Set `AI_PROVIDER` or `FAST_MODEL` to override that choice. If your own
server fails and an Anthropic key is set, the fast tasks retry on Claude Haiku
(`AI_FALLBACK=false` turns that off). The model
menus in the app show the active model by name, and Claude options appear only for users who
have a Claude key.

To change something later, edit `.env` and run
`docker compose -f docker-compose.selfhost.yml up -d`. A colour or model change needs no rebuild.

## Without an agent

Every step in `DEPLOY.md` is a plain shell command, so you can follow it yourself. The
[hosting guide](self_hosting.md) covers Heroku, servers and Google Drive in detail.
