Installing self-hosted software is usually where people give up. So for PaperManager I stopped writing a setup guide for people and wrote one for coding agents instead.

Open Claude Code, Codex or any other coding agent and paste one line:

"Set up PaperManager for me by following https://github.com/NiklasAbraham/PaperManager/blob/main/DEPLOY.md"

The agent checks your machine, asks you four questions (your login name, Anthropic or OpenAI, where your PDFs should live, an accent colour), writes the config, starts the app with Docker and tests that everything works. About 15 minutes, most of it the first build.

The app adapts to the account you have. With an Anthropic key, summaries run on Claude Haiku and chat runs on Claude. With an OpenAI key, everything runs on GPT-5 mini. You need no GPU, no LLM proxy and no Google account. Your API key never passes through the chat: you paste it into the file yourself.

PaperManager itself is an open-source research library. It reads papers with you: summaries, figures, interactive explanations, and a chat that answers from your whole library and cites its sources. It can even load a protein structure in 3D.

Try the chat demo and set it up: https://niklas-abraham.de/projects/papermanager/
Code: https://github.com/NiklasAbraham/PaperManager

#OpenSource #AI #Research #ClaudeCode #SelfHosted
