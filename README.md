# CEREBRO | Cognitive Memory for AI Agents

A lightweight, version-aware memory layer that helps Claude and Cursor stay aligned with your codebase while cutting repeated context. Teams often see large savings on tokens once the vault is warm.

## Installation

```bash
pip install -e .
```

Use a virtual environment if you prefer. Local inference (for example Ollama) is optional and depends on how you wire agents.

## Quick start

1. Run `cerebro init` to set up your project.
2. Run `cerebro scan` so the AI can read your code and store high-signal habits.
3. Keep coding. Export when you want manifests and lock files updated.

For the full interactive walkthrough:

```bash
cerebro guide
```

## Core features

- **Version-aware scanning** -- Reads common dependency files and pairs frameworks with versions when it can, so suggestions match what you actually ship.
- **Persona swapping** -- Switch tone with `cerebro vibe` (presets or a plain text rules file).
- **Team sync** -- Share `cerebro.lock` and use `cerebro pull` so everyone hydrates the same memory snapshot.

## Governance & Branding

`.cerebroignore` is Cerebro's governance boundary ("Sovereignty Wall"). Any path matched here is dropped before Slop Gate checks and before incubator/engram ingestion.

- Generate a default policy file with `cerebro init-ignore` (or `cerebro init` for merge behavior).
- Official icon asset for theme packs lives at `src/cerebro/resources/icons/cerebroignore.svg`.
- Recommended icon theme mapping (VS Code / Cursor icon themes):

```json
{
  "fileExtensions": {
    "cerebroignore": "cerebroignore"
  },
  "fileNames": {
    ".cerebroignore": "cerebroignore"
  },
  "iconDefinitions": {
    "cerebroignore": {
      "iconPath": "./icons/cerebroignore.svg"
    }
  }
}
```

Example `.cerebroignore` policy:

```gitignore
# Build and package artifacts
dist/
build/
target/

# Python runtime and caches
.venv/
__pycache__/
*.pyc

# Binary and generated blobs
*.bin
*.sqlite3

# Secrets and environment files
.env
.env.*
*.pem
*.key
```

## Commands

| Command | What it does |
| --- | --- |
| init | Initialize Cerebro in this project. |
| scan | Let the AI read and understand your project. |
| vibe | Change how the AI talks and acts. |
| status | See what the AI knows and how much you saved. |
| pull | Sync memory from your team. |
| export | Sync memory to your AI (CLAUDE.md). |
| guide | Open the interactive help menu. |
| destroy | Remove the vault and strip Cerebro blocks from manifests (asks first). |

Global flag: `-v` / `--verbose` mirrors more detail to the standard error stream.

## License

MIT. See the `LICENSE` file in this repository.

### Stress Test Session 1 what is happening.
# Cognitive Kernel established: Daemon stabilized.# Autonomic Test Sat Apr 18 17:30:16 EDT 2026
# V2 Architecture Active
# Stress Test 1
