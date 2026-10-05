import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import chromadb
except Exception:
    chromadb = None


class ChromaMemoryStore:
    """Persistent local Chroma vector store for semantic recall."""

    _client = None
    _collection = None
    _disabled = False

    @classmethod
    def _get_collection(cls):
        if cls._disabled:
            return None
        if chromadb is None:
            return None
        if cls._collection is not None:
            return cls._collection

        persist_dir = os.getenv("CHROMA_PERSIST_DIR", os.path.join(os.getcwd(), ".chroma"))
        collection_name = os.getenv("CHROMA_COLLECTION_NAME", "agent_arena_memory")
        try:
            os.makedirs(persist_dir, exist_ok=True)
            cls._client = chromadb.PersistentClient(path=persist_dir)
            cls._collection = cls._client.get_or_create_collection(name=collection_name)
            logger.info("Chroma memory initialized at %s (collection=%s).", persist_dir, collection_name)
            return cls._collection
        except BaseException as exc:
            # Chroma may raise Rust panic exceptions that do not inherit from Exception.
            cls._disabled = True
            cls._client = None
            cls._collection = None
            logger.error("Chroma disabled due to initialization failure. Falling back to Mongo vectors. Error: %s", exc)
            return None

    @classmethod
    def is_available(cls) -> bool:
        return cls._get_collection() is not None

    @classmethod
    def upsert(
        cls,
        doc_id: str,
        text: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        collection = cls._get_collection()
        if collection is None or not text or not embedding:
            return False
        try:
            collection.upsert(
                ids=[doc_id],
                documents=[text],
                embeddings=[embedding],
                metadatas=[metadata or {}],
            )
            return True
        except BaseException as exc:
            logger.warning("Chroma upsert failed: %s", exc)
            return False

    @classmethod
    def search(
        cls,
        query_embedding: List[float],
        where: Optional[Dict[str, Any]] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        collection = cls._get_collection()
        if collection is None or not query_embedding:
            return []
        try:
            where_clause = where or None
            # Newer Chroma expects an operator-style where clause.
            if where_clause and len(where_clause.keys()) > 1:
                where_clause = {"$and": [{k: {"$eq": v}} for k, v in where_clause.items()]}
            result = collection.query(
                query_embeddings=[query_embedding],
                n_results=max(1, limit),
                where=where_clause,
                include=["metadatas", "documents", "distances"],
            )
            documents = (result.get("documents") or [[]])[0]
            metadatas = (result.get("metadatas") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]

            hits = []
            for idx, doc in enumerate(documents):
                hits.append(
                    {
                        "text_chunk": doc or "",
                        "metadata": metadatas[idx] if idx < len(metadatas) else {},
                        "distance": distances[idx] if idx < len(distances) else None,
                    }
                )
            return hits
        except BaseException as exc:
            logger.warning("Chroma search failed: %s", exc)
            return []

    @classmethod
    def delete(cls, where: Optional[Dict[str, Any]] = None) -> bool:
        collection = cls._get_collection()
        if collection is None:
            return False
        try:
            where_clause = where or None
            if where_clause and len(where_clause.keys()) > 1:
                where_clause = {"$and": [{k: {"$eq": v}} for k, v in where_clause.items()]}
            collection.delete(where=where_clause)
            return True
        except BaseException as exc:
            logger.warning("Chroma delete failed: %s", exc)
            return False

