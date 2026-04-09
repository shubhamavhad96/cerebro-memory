import chromadb
from chromadb.config import Settings
import uuid


class MemoryBank:
    def __init__(self, path="./cerebro_vault"):
        # We add 'is_persistent' to ensure it saves correctly
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection(name="thoughts")
        print(f"Memory Bank Initialized at {path}")

    def commit(self, text, metadata):
        mem_id = str(uuid.uuid4())
        try:
            self.collection.add(
                documents=[text],
                metadatas=[metadata],
                ids=[mem_id]
            )
            # Log for debugging
            # print(f"DEBUG: Successfully saved to DB: {text[:30]}...")
        except Exception as e:
            print(f"STORAGE ERROR: Could not write to database: {e}")

    def retrieve(self, query_text, n_results=3):
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            # This filter ensures we only get GOOD memories
            where={"utility_score": {"$gt": 0}}
        )
        return results['documents'][0] if results['documents'] else []

    def update_score(self, mem_id, new_score):
        self.collection.update(
            ids=[mem_id],
            metadatas=[{"utility_score": new_score}]
        )
