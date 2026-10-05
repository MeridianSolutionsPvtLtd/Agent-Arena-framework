import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
import math
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import OperationFailure, PyMongoError

logger = logging.getLogger(__name__)

class AgentRuntimeStore:
    # The Arena application owns the Motor client lifecycle. This compatibility
    # facade binds Agentic AI's proven persistence methods to that shared DB.
    client = None
    db = None
    collection = None
    users_collection = None
    threads_collection = None
    messages_collection = None
    summaries_collection = None
    vectors_collection = None
    token_usage_collection = None
    @staticmethod
    def _is_cosmos_sort_index_error(exc: Exception) -> bool:
        msg = str(exc or "").lower()
        return (
            "index path corresponding to the specified order-by item is excluded" in msg
            or "codename': 'badvalue'" in msg
            or "codeName': 'BadValue'".lower() in msg
        )

    @staticmethod
    def _oid(value: str) -> ObjectId:
        """Convert a string ObjectId when possible; callers validate ownership separately."""
        if not ObjectId.is_valid(value or ""):
            raise ValueError("Invalid ObjectId")
        return ObjectId(value)

    @staticmethod
    def _serialize_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not doc:
            return doc
        out = dict(doc)
        if "_id" in out:
            out["_id"] = str(out["_id"])
        return out

    @staticmethod
    def _bounded_limit(limit: int, default: int = 50, max_limit: int = 200) -> int:
        try:
            value = int(limit)
        except (TypeError, ValueError):
            value = default
        return max(1, min(value, max_limit))

    @classmethod
    def connect(cls, db=None):
        from database import get_db

        # PyMongo/Motor database objects intentionally reject truth-value
        # testing. Use an explicit None check instead of ``db or get_db()``.
        cls.db = db if db is not None else get_db()
        if cls.db is None:
            raise RuntimeError("Arena MongoDB connection is not initialized")

        try:
            cls.collection = cls.db["agents"]
            cls.users_collection = cls.db["users"]
            cls.threads_collection = cls.db["threads"]
            cls.messages_collection = cls.db["messages"]
            cls.summaries_collection = cls.db["memory_summaries"]
            cls.vectors_collection = cls.db["memory_vectors"]
            cls.token_usage_collection = cls.db["token_usage"]

            logger.info("Agent runtime bound to Arena MongoDB database")
        except Exception as e:
            logger.error("Failed to bind agent runtime collections: %s", e, exc_info=True)
            raise

    @classmethod
    async def ensure_indexes(cls) -> None:
        """Create production indexes for canonical runtime collections.

        Uses ensure_index() from core/startup/indexes for Cosmos DB
        compatibility — name-first deduplication prevents spurious
        create_index attempts on every 60-second recovery probe.
        """
        from core.startup.indexes import ensure_index

        if cls.db is None:
            return

        async def create(collection, keys, **kwargs):
            if collection is None:
                return
            await ensure_index(collection, keys, **kwargs)

        await create(cls.users_collection, [("username", ASCENDING)], unique=True, sparse=True, name="uq_users_username")
        await create(cls.users_collection, [("email", ASCENDING)], unique=True, sparse=True, name="uq_users_email")
        await create(cls.collection, [("user_id", ASCENDING), ("agent_id", ASCENDING)], unique=True, name="uq_agents_user_agent")
        await create(cls.threads_collection, [("user_id", ASCENDING), ("agent_id", ASCENDING), ("thread_id", ASCENDING)], unique=True, name="uq_threads_user_agent_thread")
        await create(
            cls.threads_collection,
            [("provider", ASCENDING), ("provider_thread_id", ASCENDING)],
            unique=True,
            sparse=True,
            name="uq_threads_provider_thread",
        )
        await create(cls.messages_collection, [("user_id", ASCENDING), ("agent_id", ASCENDING), ("thread_id", ASCENDING), ("created_at", DESCENDING)], name="ix_messages_user_agent_thread")
        await create(cls.summaries_collection, [("user_id", ASCENDING), ("agent_id", ASCENDING), ("thread_id", ASCENDING), ("version", DESCENDING)], name="ix_summaries_user_agent_thread")
        await create(cls.vectors_collection, [("user_id", ASCENDING), ("agent_id", ASCENDING), ("thread_id", ASCENDING), ("source_type", ASCENDING), ("source_id", ASCENDING)], unique=True, name="uq_memory_vectors_source")
        await create(cls.token_usage_collection, [("user_id", ASCENDING), ("agent_id", ASCENDING), ("thread_id", ASCENDING), ("created_at", DESCENDING)], name="ix_token_usage_user_agent_thread")

    @classmethod
    def disconnect(cls):
        # The Arena lifespan closes the shared Mongo client.
        cls.db = None

    @classmethod
    async def save_agent(cls, agent_data: Dict[str, Any]) -> str:
        """Inserts or updates an agent blueprint."""
        if cls.collection is None: return None
        result = await cls.collection.insert_one(agent_data)
        return str(result.inserted_id)

    @classmethod
    async def get_agent(cls, agent_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves an agent blueprint ensuring it belongs to the user."""
        if cls.collection is None: return None
        return await cls.collection.find_one({"agent_id": agent_id, "user_id": user_id}, {"_id": 0})

    @classmethod
    async def list_agents_for_user(cls, user_id: str) -> list:
        """Lists agents belonging to a specific user"""
        if cls.collection is None: return []
        cursor = cls.collection.find({"user_id": user_id}, {"_id": 0})
        return await cursor.to_list(length=100)

    @classmethod
    async def create_user(cls, user_data: Dict[str, Any]) -> bool:
        if cls.users_collection is None: return False
        # Ensure distinct username
        existing = await cls.users_collection.find_one({"username": user_data["username"]})
        if existing: return False
        await cls.users_collection.insert_one(user_data)
        return True

    @classmethod
    async def get_user(cls, username: str) -> Optional[Dict[str, Any]]:
        if cls.users_collection is None: return None
        return await cls.users_collection.find_one({"username": username})

    @classmethod
    async def delete_agent(cls, agent_id: str, user_id: str) -> bool:
        """Removes an agent from the registry."""
        if cls.collection is None: return False
        try:
            result = await cls.collection.delete_one({"agent_id": agent_id, "user_id": user_id})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting agent {agent_id}: {e}")
            return False

    @classmethod
    async def update_agent_name(cls, agent_id: str, user_id: str, new_name: str) -> bool:
        """Updates the name of an existing agent."""
        if cls.collection is None: return False
        result = await cls.collection.update_one(
            {"agent_id": agent_id, "user_id": user_id},
            {"$set": {"name": new_name}}
        )
        return result.modified_count > 0

    # ------------------------ Memory Layer ------------------------
    @classmethod
    async def ensure_thread(cls, thread_id: str, user_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
        if cls.threads_collection is None:
            return None
        now = datetime.utcnow()
        await cls.threads_collection.update_one(
            {"thread_id": thread_id, "user_id": user_id, "agent_id": agent_id},
            {
                "$setOnInsert": {
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "created_at": now,
                    "turn_count": 0,
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )
        return await cls.threads_collection.find_one(
            {"thread_id": thread_id, "user_id": user_id, "agent_id": agent_id},
            {"_id": 0},
        )

    @classmethod
    async def append_message(
        cls,
        thread_id: str,
        user_id: str,
        agent_id: str,
        role: str,
        text: str,
        pair_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if cls.messages_collection is None:
            return None
        now = datetime.utcnow()
        token_estimate = int((len(text or "") / 4) + 1)
        doc = {
            "thread_id": thread_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "role": role,
            "text": text,
            "pair_id": pair_id,
            "token_estimate": token_estimate,
            "trace_id": trace_id,
            "metadata": metadata or {},
            "created_at": now,
        }
        result = await cls.messages_collection.insert_one(doc)
        await cls.threads_collection.update_one(
            {"thread_id": thread_id, "user_id": user_id, "agent_id": agent_id},
            {
                "$set": {"updated_at": now, "last_message_at": now},
                "$inc": {"turn_count": 1},
            },
        )
        return str(result.inserted_id)

    @classmethod
    async def get_recent_messages(
        cls,
        thread_id: str,
        user_id: str,
        agent_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        if cls.messages_collection is None:
            return []
        base_query = {"thread_id": thread_id, "user_id": user_id, "agent_id": agent_id}
        try:
            cursor = (
                cls.messages_collection.find(base_query, {"_id": 0})
                .sort("created_at", -1)
                .limit(limit)
            )
            docs = await cursor.to_list(length=limit)
        except Exception as e:
            if not cls._is_cosmos_sort_index_error(e):
                raise
            logger.warning(
                "Cosmos rejected sort(created_at). Falling back to _id sort for thread %s: %s",
                thread_id,
                e,
            )
            cursor = (
                cls.messages_collection.find(base_query, {"_id": 0})
                .sort("_id", -1)
                .limit(limit)
            )
            docs = await cursor.to_list(length=limit)
        docs.reverse()
        return docs

    @classmethod
    async def get_thread_turn_count(cls, thread_id: str, user_id: str, agent_id: str) -> int:
        if cls.threads_collection is None:
            return 0
        thread = await cls.threads_collection.find_one(
            {"thread_id": thread_id, "user_id": user_id, "agent_id": agent_id},
            {"_id": 0, "turn_count": 1},
        )
        return int((thread or {}).get("turn_count", 0))

    @classmethod
    async def get_latest_thread(cls, user_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
        if cls.threads_collection is None:
            return None
        docs = await (
            cls.threads_collection.find(
                {"user_id": user_id, "agent_id": agent_id},
                {"_id": 0},
            )
            .sort("_id", -1)
            .limit(1)
            .to_list(length=1)
        )
        return docs[0] if docs else None

    @classmethod
    async def get_messages_for_thread(
        cls,
        thread_id: str,
        user_id: str,
        agent_id: str,
        limit: int = 80,
    ) -> List[Dict[str, Any]]:
        if cls.messages_collection is None:
            return []
        bounded_limit = max(1, min(int(limit or 80), 200))
        cursor = (
            cls.messages_collection.find(
                {"thread_id": thread_id, "user_id": user_id, "agent_id": agent_id},
                {"_id": 0},
            )
            .sort("_id", -1)
            .limit(bounded_limit)
        )
        docs = await cursor.to_list(length=bounded_limit)
        docs.reverse()
        return docs

    @classmethod
    async def get_latest_summary(cls, thread_id: str, user_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
        if cls.summaries_collection is None:
            return None
        base_query = {"thread_id": thread_id, "user_id": user_id, "agent_id": agent_id}
        try:
            return await cls.summaries_collection.find_one(
                base_query,
                {"_id": 0},
                sort=[("version", -1)],
            )
        except Exception as e:
            if not cls._is_cosmos_sort_index_error(e):
                raise
            logger.warning(
                "Cosmos rejected sort(version). Falling back to _id sort for thread %s: %s",
                thread_id,
                e,
            )
            return await cls.summaries_collection.find_one(
                base_query,
                {"_id": 0},
                sort=[("_id", -1)],
            )

    @classmethod
    async def save_summary(
        cls,
        thread_id: str,
        user_id: str,
        agent_id: str,
        summary_payload: Dict[str, Any],
    ) -> int:
        if cls.summaries_collection is None:
            return 1
        latest = await cls.get_latest_summary(thread_id, user_id, agent_id)
        next_version = int((latest or {}).get("version", 0)) + 1
        doc = {
            "thread_id": thread_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "version": next_version,
            "updated_at": datetime.utcnow(),
            **summary_payload,
        }
        await cls.summaries_collection.insert_one(doc)
        return next_version

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @classmethod
    async def upsert_memory_vector(
        cls,
        thread_id: str,
        user_id: str,
        agent_id: str,
        source_type: str,
        source_id: str,
        text_chunk: str,
        embedding: List[float],
        importance_score: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if cls.vectors_collection is None:
            return
        await cls.vectors_collection.update_one(
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "source_type": source_type,
                "source_id": source_id,
            },
            {
                "$set": {
                    "text_chunk": text_chunk,
                    "embedding": embedding,
                    "importance_score": importance_score,
                    "metadata": metadata or {},
                    "updated_at": datetime.utcnow(),
                },
                "$setOnInsert": {"created_at": datetime.utcnow()},
            },
            upsert=True,
        )

    @classmethod
    async def search_memory_vectors(
        cls,
        thread_id: str,
        user_id: str,
        agent_id: str,
        query_embedding: List[float],
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        if cls.vectors_collection is None:
            return []
        cursor = cls.vectors_collection.find(
            {"thread_id": thread_id, "user_id": user_id, "agent_id": agent_id},
            {"_id": 0},
        )
        all_docs = await cursor.to_list(length=500)
        scored = []
        for doc in all_docs:
            similarity = cls._cosine_similarity(query_embedding, doc.get("embedding", []))
            importance = float(doc.get("importance_score", 0.5))
            final_score = (0.8 * similarity) + (0.2 * importance)
            scored.append((final_score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for score, doc in scored[:limit] if score > 0.2]

    @classmethod
    async def record_token_usage(
        cls,
        thread_id: str,
        user_id: str,
        agent_id: str,
        pair_id: str,
        query_tokens: int,
        context_tokens: int,
        response_tokens: int,
        total_tokens: int,
        context_breakdown: Optional[Dict[str, int]] = None,
    ) -> None:
        if cls.token_usage_collection is None:
            return
        now = datetime.utcnow()
        await cls.token_usage_collection.insert_one(
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "pair_id": pair_id,
                "query_tokens": query_tokens,
                "context_tokens": context_tokens,
                "context_breakdown": context_breakdown or {},
                "response_tokens": response_tokens,
                "total_tokens": total_tokens,
                "created_at": now,
            }
        )
        await cls.threads_collection.update_one(
            {"thread_id": thread_id, "user_id": user_id, "agent_id": agent_id},
            {
                "$inc": {
                    "token_totals.query_tokens": query_tokens,
                    "token_totals.context_tokens": context_tokens,
                    "token_totals.response_tokens": response_tokens,
                    "token_totals.total_tokens": total_tokens,
                    "token_totals.request_count": 1,
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )

    @classmethod
    async def get_thread_token_totals(cls, thread_id: str, user_id: str, agent_id: str) -> Dict[str, int]:
        if cls.threads_collection is None:
            return {
                "query_tokens": 0,
                "context_tokens": 0,
                "response_tokens": 0,
                "total_tokens": 0,
                "request_count": 0,
            }
        thread = await cls.threads_collection.find_one(
            {"thread_id": thread_id, "user_id": user_id, "agent_id": agent_id},
            {"_id": 0, "token_totals": 1},
        )
        totals = (thread or {}).get("token_totals", {})
        return {
            "query_tokens": int(totals.get("query_tokens", 0)),
            "context_tokens": int(totals.get("context_tokens", 0)),
            "response_tokens": int(totals.get("response_tokens", 0)),
            "total_tokens": int(totals.get("total_tokens", 0)),
            "request_count": int(totals.get("request_count", 0)),
        }

    # ────────────────────────────────────────────────────────────
    # Agent Fine-Tuning Config (Sub-Agents, Executor, Validator)
    # ────────────────────────────────────────────────────────────

    @classmethod
    async def update_agent_config(
        cls,
        agent_id: str,
        user_id: str,
        config_update: Dict[str, Any],
    ) -> bool:
        """
        Patches the fine-tuning fields on an existing agent document.
        Accepts any combination of: sub_agents, executor_policy, validator_config.
        """
        if cls.collection is None:
            return False

        set_fields = {}
        for key in ("crew_roles", "executor_policy", "validator_config", "system_prompt", "tools"):
            if key in config_update:
                set_fields[key] = config_update[key]

        if not set_fields:
            return False

        set_fields["config_updated_at"] = datetime.utcnow()

        result = await cls.collection.update_one(
            {"agent_id": agent_id, "user_id": user_id},
            {"$set": set_fields},
        )
        return result.modified_count > 0

    @classmethod
    async def get_agent_config(
        cls,
        agent_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Returns the fine-tuning config for a specific agent.
        Includes sub_agents, executor_policy, validator_config, and the
        original crew_roles for reference.
        """
        if cls.collection is None:
            return {}

        doc = await cls.collection.find_one(
            {"agent_id": agent_id, "user_id": user_id},
            {
                "_id": 0,
                "crew_roles": 1,
                "sub_agents": 1,
                "executor_policy": 1,
                "validator_config": 1,
                "system_prompt": 1,
                "config_updated_at": 1,
            },
        )
        return doc or {}

    @classmethod
    async def clear_agent_history(cls, agent_id: str, user_id: str) -> bool:
        """Clears all conversation threads, messages, summaries, vector memories, and token usage for an agent."""
        if cls.threads_collection is None:
            return False
        try:
            # 1. Delete all threads for the agent
            await cls.threads_collection.delete_many({"agent_id": agent_id, "user_id": user_id})
            
            # 2. Delete all messages
            if cls.messages_collection is not None:
                await cls.messages_collection.delete_many({"agent_id": agent_id, "user_id": user_id})
                
            # 3. Delete summaries
            if cls.summaries_collection is not None:
                await cls.summaries_collection.delete_many({"agent_id": agent_id, "user_id": user_id})
                
            # 4. Delete vectors in Mongo
            if cls.vectors_collection is not None:
                await cls.vectors_collection.delete_many({"agent_id": agent_id, "user_id": user_id})
                
            # 5. Delete token usage records
            if cls.token_usage_collection is not None:
                await cls.token_usage_collection.delete_many({"agent_id": agent_id, "user_id": user_id})
                
            # 6. Delete from Chroma if available
            try:
                from core.memory.chroma_store import ChromaMemoryStore
                if ChromaMemoryStore.is_available():
                    ChromaMemoryStore.delete(where={"agent_id": agent_id, "user_id": user_id})
            except Exception as e:
                logger.warning(f"Failed to clear history in Chroma: {e}")
                
            return True
        except Exception as e:
            logger.error(f"Error clearing agent history for {agent_id}: {e}")
            return False

    @classmethod
    async def get_cumulative_token_usage(cls, agent_id: str, user_id: str) -> int:
        """Returns the total number of tokens consumed by the agent across all conversation threads."""
        if cls.threads_collection is None:
            return 0
        try:
            pipeline = [
                {"$match": {"agent_id": agent_id, "user_id": user_id}},
                {"$group": {"_id": None, "total": {"$sum": "$token_totals.total_tokens"}}}
            ]
            cursor = cls.threads_collection.aggregate(pipeline)
            result = await cursor.to_list(length=1)
            return result[0]["total"] if result else 0
        except Exception as e:
            logger.error(f"Error computing cumulative token usage for {agent_id}: {e}")
            return 0
