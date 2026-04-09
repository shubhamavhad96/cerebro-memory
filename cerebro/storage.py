import chromadb
import uuid
from typing import Any


class MemoryBank:
    """Persistent vector-memory store used by Cerebro observers."""

    def __init__(self, path: str = "./cerebro_vault") -> None:
        """Initialize a persistent ChromaDB collection for memory storage."""
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection(name="thoughts")
        print(f"Memory Bank Initialized at {path}")

    def commit(self, text: str, metadata: dict[str, Any]) -> None:
        """Store a memory document with associated metadata."""
        mem_id = str(uuid.uuid4())
        try:
            self.collection.add(
                documents=[text],
                metadatas=[metadata],
                ids=[mem_id]
            )
        except Exception as e:
            print(f"STORAGE ERROR: Could not write to database: {e}")

    def retrieve(self, query_text: str, n_results: int = 3) -> list[str]:
        """Return top useful memories for a query sorted by vector similarity."""
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where={"utility_score": {"$gt": 0}}
        )
        return results['documents'][0] if results['documents'] else []

    def update_score(self, mem_id: str, new_score: float) -> None:
        """Update utility score for an existing memory item."""
        self.collection.update(
            ids=[mem_id],
            metadatas=[{"utility_score": new_score}]
        )
