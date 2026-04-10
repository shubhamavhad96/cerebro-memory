import chromadb
from loguru import logger
import asyncio
import os
import time
import math
import json
from typing import Any, Dict, List, Optional, Tuple


class MemoryBank:
    """Manage persistent semantic memory with weighted temporal retrieval.

    The memory bank provides infrastructure primitives for storing agent
    interactions, reinforcing recurring patterns, and retrieving context using
    semantic similarity re-ranked by Temporal Decay. This allows memory to stay
    both relevant and adaptive in long-running autonomous workflows.
    """

    def __init__(self, db_path: str = "./cerebro_vault") -> None:
        """Initialize the persistent vector collection for memory operations.

        Args:
            db_path: Filesystem location used by ChromaDB for local persistence.

        Returns:
            None.

        Raises:
            OSError: If the storage directory cannot be created.
            RuntimeError: If the vector database client cannot be initialized.
        """
        if not os.path.exists(db_path):
            os.makedirs(db_path)
        self.client: Any = chromadb.PersistentClient(path=db_path)
        self.collection: Any = self.client.get_or_create_collection(name="vault")
        logger.info(f"Memory Bank Initialized at {db_path}")

    async def commit(self, text: str, metadata: Dict[str, Any]) -> None:
        """Persist a single memory entry with metadata lineage.

        Args:
            text: Canonical memory payload to be indexed for retrieval.
            metadata: Structured attributes used for downstream filtering and
                policy decisions.

        Returns:
            None.

        Raises:
            RuntimeError: If the underlying vector write operation fails.
        """
        loop = asyncio.get_running_loop()
        count = self.collection.count()
        metadata["timestamp"] = time.time()

        await loop.run_in_executor(
            None,
            lambda: self.collection.add(
                ids=[f"mem_{count + 1}_{int(time.time())}"],
                documents=[text],
                metadatas=[metadata]
            )
        )

    async def check_cache(
        self, prompt_text: str, threshold: float = 0.05
    ) -> Optional[str]:
        """Resolve a prior response via semantic similarity over cache entries.

        Restricts vector search to documents tagged ``category="cache"`` so
        production retrieval and habit lanes are not conflated with the cache
        slice. Near-zero latency repeat traffic is achieved by short-circuiting
        upstream synthesis when the nearest neighbor distance falls below
        ``threshold``.

        Args:
            prompt_text: Query text embedded and compared against cached prompts.
            threshold: Maximum distance for a hit; lower values require tighter
                semantic alignment.

        Returns:
            ``cached_response`` from matching metadata when a hit occurs;
            otherwise ``None``.

        Raises:
            RuntimeError: If the vector query fails.
        """
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            lambda: self.collection.query(
                query_texts=[prompt_text],
                n_results=1,
                where={"category": "cache"},
            ),
        )
        if (
            not results
            or not results.get("ids")
            or not results["ids"][0]
            or not results.get("distances")
            or not results["distances"][0]
        ):
            return None
        dist = results["distances"][0][0]
        if dist is None or dist >= threshold:
            return None
        metas = results.get("metadatas")
        if not metas or not metas[0]:
            return None
        meta = metas[0][0]
        if not meta:
            return None
        cached = meta.get("cached_response")
        if cached is None:
            return None
        return str(cached)

    async def get_all_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Load every vault record in a category slice for batch analytics.

        Used by distillation and compaction jobs that require full scans of a
        logical lane without semantic ranking.

        Args:
            category: Metadata ``category`` value to filter (e.g. ``habit``).

        Returns:
            Records as dicts with ``id``, ``document``, and ``metadata`` keys.

        Raises:
            RuntimeError: If the backing store read fails.
        """
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: self.collection.get(where={"category": category}),
        )
        ids = raw.get("ids") or []
        docs = raw.get("documents") or []
        metas = raw.get("metadatas") or []
        return [
            {
                "id": i,
                "document": d if d is not None else "",
                "metadata": dict(m) if m else {},
            }
            for i, d, m in zip(ids, docs, metas)
        ]

    async def prune_memories(self, ids: List[str]) -> None:
        """Remove vault rows by identifier for compaction and deduplication.

        Args:
            ids: Chroma document ids to delete permanently.

        Returns:
            None.

        Raises:
            RuntimeError: If deletion fails against the vector store.
        """
        if not ids:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self.collection.delete(ids=list(ids)),
        )

    async def upsert_habit(self, habit_text: str) -> int:
        """Reinforce a recurring pattern using similarity-based upsert.

        Args:
            habit_text: Normalized pattern text representing repeat behavior.

        Returns:
            Updated habit strength after reinforcement or initialization.

        Raises:
            RuntimeError: If similarity lookup or persistence fails.
        """
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            lambda: self.collection.query(
                query_texts=[habit_text],
                n_results=1,
                where={"category": "habit"}
            )
        )

        current_time = time.time()
        if results['ids'] and results['ids'][0] and results['distances'][0][0] < 0.3:
            existing_id = results['ids'][0][0]
            existing_meta = results['metadatas'][0][0]
            new_strength = existing_meta.get("strength", 1) + 1

            new_metadata = {
                "category": "habit",
                "strength": new_strength,
                "timestamp": current_time
            }

            await loop.run_in_executor(
                None,
                lambda: self.collection.update(
                    ids=[existing_id],
                    metadatas=[new_metadata]
                )
            )
            return new_strength
        else:
            count = self.collection.count()
            await loop.run_in_executor(
                None,
                lambda: self.collection.add(
                    ids=[f"habit_{count + 1}_{int(time.time())}"],
                    documents=[habit_text],
                    metadatas=[{"category": "habit",
                                "strength": 1, "timestamp": current_time}]
                )
            )
            return 1

    async def retrieve_weighted(
        self, query_text: str, n_results: int = 5
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Retrieve memories using Semantic Retrieval and Temporal Decay ranking.

        The method first performs vector similarity search and then re-ranks
        candidates with an exponential decay factor to prioritize useful recency
        without discarding historically important context.

        Args:
            query_text: Retrieval query representing current task intent.
            n_results: Number of ranked memories returned to the caller.

        Returns:
            Ordered memory tuples of document text and metadata.

        Raises:
            RuntimeError: If the vector query fails.
        """
        loop = asyncio.get_running_loop()
        raw_results = await loop.run_in_executor(
            None,
            lambda: self.collection.query(
                query_texts=[query_text], n_results=n_results * 2)
        )

        now = time.time()
        decay_constant = 0.00001
        scored_memories = []

        if raw_results and raw_results.get('documents') and raw_results['documents'][0]:
            for i in range(len(raw_results['documents'][0])):
                doc = raw_results['documents'][0][i]
                meta = raw_results['metadatas'][0][i]
                dist = raw_results['distances'][0][i]

                similarity = 1.0 / (1.0 + dist)
                age = now - meta.get("timestamp", now)
                time_weight = math.exp(-decay_constant * age)

                final_score = similarity * time_weight
                scored_memories.append((doc, meta, final_score))

        scored_memories.sort(key=lambda x: x[2], reverse=True)
        return [(m[0], m[1]) for m in scored_memories[:n_results]]

    async def snapshot_vault_readonly(self) -> List[Dict[str, Any]]:
        """Return a point-in-time read snapshot of every row in the vault.

        Intended for observability and audit UIs. Performs no writes.

        Args:
            None.

        Returns:
            List of records with ``id``, ``document``, and ``metadata`` keys.

        Raises:
            RuntimeError: If the vector store read fails.
        """
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, lambda: self.collection.get())
        ids = raw.get("ids") or []
        docs = raw.get("documents") or []
        metas = raw.get("metadatas") or []
        return [
            {
                "id": i,
                "document": d if d is not None else "",
                "metadata": dict(m) if m else {},
            }
            for i, d, m in zip(ids, docs, metas)
        ]

    async def retrieve_weighted_with_scores(
        self, query_text: str, n_results: int = 5
    ) -> List[Dict[str, Any]]:
        """Semantic retrieval with explicit similarity and Temporal Decay weights.

        Mirrors :meth:`retrieve_weighted` ranking while exposing intermediate
        scores for observability dashboards.

        Args:
            query_text: Retrieval query text.
            n_results: Number of rows to return after re-ranking.

        Returns:
            Ordered dicts with ``document``, ``metadata``, ``similarity``,
            ``recency_weight``, ``final_score``, and ``distance``.

        Raises:
            RuntimeError: If the vector query fails.
        """
        loop = asyncio.get_running_loop()
        raw_results = await loop.run_in_executor(
            None,
            lambda: self.collection.query(
                query_texts=[query_text], n_results=n_results * 2
            ),
        )
        now = time.time()
        decay_constant = 0.00001
        scored: List[Dict[str, Any]] = []

        if raw_results and raw_results.get("documents") and raw_results["documents"][0]:
            for i in range(len(raw_results["documents"][0])):
                doc = raw_results["documents"][0][i]
                meta = raw_results["metadatas"][0][i]
                dist = raw_results["distances"][0][i]
                similarity = 1.0 / (1.0 + dist)
                age = now - meta.get("timestamp", now)
                time_weight = math.exp(-decay_constant * age)
                final_score = similarity * time_weight
                scored.append(
                    {
                        "document": doc,
                        "metadata": meta,
                        "similarity": round(float(similarity), 6),
                        "recency_weight": round(float(time_weight), 6),
                        "final_score": round(float(final_score), 6),
                        "distance": float(dist),
                    }
                )

        scored.sort(key=lambda x: x["final_score"], reverse=True)
        return scored[:n_results]

    async def export_vault(self, export_path: str = "cerebro_dna.json") -> str:
        """Export all persisted memory state into a portable snapshot.

        Args:
            export_path: Output path for serialized memory artifact.

        Returns:
            Absolute path to the exported snapshot.

        Raises:
            OSError: If the file cannot be written.
            RuntimeError: If reading from the vector store fails.
        """
        loop = asyncio.get_running_loop()
        all_data = await loop.run_in_executor(None, lambda: self.collection.get())

        dna_package = {
            "version": "1.1",
            "exported_at": time.time(),
            "entries": [
                {"text": doc, "metadata": meta}
                for doc, meta in zip(all_data['documents'], all_data['metadatas'])
            ]
        }

        with open(export_path, "w") as f:
            json.dump(dna_package, f, indent=4)
        return os.path.abspath(export_path)

    async def import_vault(self, file_path: str) -> None:
        """Rehydrate local memory from an exported snapshot artifact.

        Args:
            file_path: Path to a previously exported memory snapshot.

        Returns:
            None.

        Raises:
            FileNotFoundError: If the source artifact does not exist.
            json.JSONDecodeError: If the artifact payload is invalid JSON.
            RuntimeError: If commit operations fail during re-indexing.
        """
        with open(file_path, "r") as f:
            dna = json.load(f)
        for entry in dna["entries"]:
            await self.commit(entry["text"], entry["metadata"])
        logger.success(
            f"Successfully absorbed {len(dna['entries'])} memories.")
