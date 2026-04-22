<div align="center">
  <h1>Cerebro</h1>
  <p><b>An autonomic, persistent memory compilation engine for AI coding assistants.</b></p>

  <a href="https://pypi.org/project/cerebro-memory/"><img src="https://img.shields.io/pypi/v/cerebro-memory.svg" alt="PyPI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python Version"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License"></a>
</div>

<br>

Cerebro autonomously distills your AI chat logs and code diffs into a structured knowledge graph. It eliminates "context amnesia" in AI coding assistants without relying on heavy background daemons or external dependencies.

## The Core Concept

Most AI coding assistants suffer from context amnesia. When you open a new session, the AI has forgotten the architectural decisions, bug fixes, and design rationale from the day before. RAG (Retrieval-Augmented Generation) attempts to solve this by searching raw files, but it forces the LLM to blindly re-derive knowledge from scratch on every query.

**The Cerebro Solution:** On each `git push`, the hook merges **unpushed** patches with your **local Cursor chat** (read from the IDE’s SQLite) and compiles a persistent `KNOWLEDGE_GRAPH.md` under `.cerebro/`. 

**Context Compression & Token Economics:** By replacing raw file scraping with a highly condensed markdown graph, Cerebro drastically reduces the "Amnesia Tax." The AI no longer needs to consume tens of thousands of input tokens to re-read your project state on every new chat; it reads a single optimized file. This knowledge is compiled once and compounds over time, saving massive API costs and accelerating response times.

## Step-by-Step Installation

Cerebro is designed to be frictionless to install and run natively on your machine.

**1. Install the global package**
Requires Python 3.10+.
```bash
pip install cerebro-memory
```

**2. Configure your AI Provider (API Keys)**
Cerebro needs an AI model to compile your memory in the background. It features a Provider-Agnostic Omni-Router that natively supports Anthropic, OpenAI, Gemini, and Groq.

**Security Guarantee:** Cerebro operates on a strict zero-telemetry, local-execution security model. Your API keys are never logged, cached, or transmitted to any third-party servers. They are parsed securely from your local environment and held in memory exclusively for the milliseconds required to authenticate the compilation request.

Create a `.env` file in your project root (ensure it is secured in your `.gitignore`) and add your preferred key:
```env
ANTHROPIC_API_KEY=sk-ant-1234...
# Or OPENAI_API_KEY, GEMINI_API_KEY, GROQ_API_KEY
```
*Note: If no API key is found, Cerebro gracefully falls back to local inference via **Ollama** (`localhost:11434`), ensuring a 100% offline, air-gapped memory loop.*

## The Daily Workflow (Quickstart)

Cerebro requires zero daily maintenance. You only need to set it up once per project.

**1. Initialize the memory system**
Navigate to your project repository in the terminal and run:
```bash
cerebro init
```
*This command appends the read protocol to your IDE config, adjusts ``.gitignore`` so ``KNOWLEDGE_GRAPH.md`` can be committed, and installs a ``pre-push`` hook that recompiles the wiki.*

**2. Work normally**
Use Cursor (or your usual workflow), commit as you go. Chat history is read from the IDE’s local storage when you push—no separate shadow file.

**3. Push**
```bash
git push
```
*A ``pre-push`` hook fuses **unpushed diffs** with **Cursor chat** from the workspace ``state.vscdb`` and rewrites ``KNOWLEDGE_GRAPH.md`` via your LLM. The hook is fail-soft: if Ollama or cloud APIs are offline, the push still proceeds. The hook can add a follow-up commit that contains only the graph.*

## Core Features Explained

### Multiplayer State Sync (`share` and `import_brain`)
When a new developer joins a project, they lack historical context. Cerebro solves this with secure peer-to-peer state syncing.
* A senior developer runs `cerebro share`. This packages the current Knowledge Graph and pushes it to a Secret GitHub Gist.
* They send the resulting secure URL to the new teammate.
* The new teammate runs `cerebro import_brain <url>`, instantly downloading months of architectural decisions directly into their local environment's memory.

### Zero Background Daemons
Cerebro does not require a long-running listener. A native ``pre-push`` hook runs the compiler when you push; it exits immediately after, consuming no idle CPU.

### Platform Support
Cerebro is platform-agnostic, integrating seamlessly with the file-reading capabilities of modern AI assistants.

| Platform | Integration Method |
| :--- | :--- |
| **Cursor** | Safely appends the memory protocol to `.cursorrules`. |
| **Claude Code** | Safely appends the memory protocol to `CLAUDE.md`. |
| **OpenClaw** | Natively supported. Reads `.cerebro/KNOWLEDGE_GRAPH.md` directly. |
| **Copilot / Aider** | Point the custom instruction settings to read `.cerebro/KNOWLEDGE_GRAPH.md`. |

## Architecture Under the Hood

Cerebro 3.0 is made of three parts:

1. **Sponging (local):** The compiler locates the workspace’s Cursor ``state.vscdb``, extracts user/assistant turns (since the merge-base with the remote when possible), and reads **unpushed** patch text via ``git log <upstream>..HEAD -p``.
2. **The hook:** A `pre-push` script runs `cerebro compile` quietly, then `git add` / `git commit --no-verify` for `KNOWLEDGE_GRAPH.md` when it changed. Hook mode never blocks your push on LLM failure.
3. **The distiller (LLM):** A Graphify-style system prompt discards debug noise and emits dense, cross-linked Markdown suitable as an **OS-level LLM-wiki** at `.cerebro/KNOWLEDGE_GRAPH.md`.

## License

Released under the [MIT License](LICENSE).
# testing the autonomous hook
