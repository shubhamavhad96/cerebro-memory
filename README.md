# Cerebro-Memory

**A persistent, self-correcting memory layer for local AI agents.**

---

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![Status](https://img.shields.io/badge/status-active-success.svg)](https://github.com/shubhamavhad/cerebro-memory)
[![Inference](https://img.shields.io/badge/inference-local--first-orange.svg)](https://ollama.com)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

## Project Overview

Cerebro-Memory is a Python middleware library designed to provide long-term semantic context and autonomous runtime learning for AI agents. By integrating a local vector database with on-device inference, the library enables agents to retain state across sessions and automatically adjust their reasoning based on execution outcomes.

The system is architected for environments where data sovereignty and cyber security are paramount, such as financial reconciliation, PII handling, or internal engineering infrastructure.

---

## Technical Specifications

| Feature | Description |
| :--- | :--- |
| **Self-Healing Loop** | Captures Python exceptions at runtime to generate and store negative-utility "Critical Lessons." |
| **Data Sovereignty** | 100% on-device processing via **ChromaDB** and **Ollama**. |
| **Semantic Retrieval** | Vector-based search (RAG) ensures context injection based on intent, not keywords. |
| **Lazy Initialization** | Optimized for macOS to prevent database locking and minimize memory overhead. |
| **Middleware Design** | Decouples memory management from core agent logic using a decorator-based interface. |

---

## Installation

### 1. Prerequisites

Cerebro-Memory requires **Ollama** for local inference. Ensure Ollama is running and the `llama3` model is available:

```bash
# Verify Ollama installation
ollama --version

# Pull the required model
ollama pull llama3
```

### 2. Setup and Installation

Clone the repository and install the library in editable mode within a virtual environment.

```bash
# Clone the repository
git clone [https://github.com/shubhamavhad/cerebro-memory.git](https://github.com/shubhamavhad/cerebro-memory.git)
cd cerebro-memory

# Initialize virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install library in editable mode
pip install -e .
```

---

## Quick Start

The library exposes a single decorator interface to equip any function with persistent memory.

```python
from cerebro.observer import observe_brain

@observe_brain
def my_agent(prompt: str, context: str = ""):
    """
    Cerebro-Memory automatically injects 'context' from relevant 
    past lessons and memories prior to function execution.
    """
    import ollama
    
    system_instruction = f"Informed by past lessons: {context}"
    
    response = ollama.generate(
        model='llama3',
        prompt=prompt,
        system=system_instruction
    )
    
    return response['response']
```

---

## Architecture: The Feedback Loop

Cerebro-Memory functions as an autonomous middleware layer using a three-phase cycle:

*   **Recall Phase**: Upon function invocation, the current prompt is embedded and queried against the local **ChromaDB** instance. Memories with high utility scores are injected into the function's context.
*   **Execution Phase**: The agent processes the prompt using the reinforced context provided by the middleware.
*   **Commit Phase**: 
    - **On Success**: The response is indexed with a standard utility weight.
    - **On Failure**: If the function raises an exception, the traceback is intercepted and committed as a **"Critical Lesson"** with high-priority negative weight to prevent recurrence.

---

## Security and Privacy

Designed for zero-leakage environments, Cerebro-Memory ensures that all vector embeddings, prompts, and execution data remain strictly within the local host's physical boundary. This architecture eliminates the third-party dependency risks associated with cloud-based LLM providers.

---

## License

This project is licensed under the MIT License - see the `LICENSE` file for details.

**Author:** [Shubham Avhad](https://github.com/shubhamavhad)
