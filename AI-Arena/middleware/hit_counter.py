from database import get_users_collection
from utils.logger import get_logger

logger = get_logger(__name__)


async def increment_hit_count(
    user_id: str,
    service_name: str,
    target_field: str = "hit_counts",
    tokens: int | str | float = 0,
):
    """Increment the hit count and optionally tokens for a specific service or agent for a user."""
    users = get_users_collection()
    from bson import ObjectId
    try:
        update_data = {f"{target_field}.{service_name}": 1}

        parsed_tokens = 0
        if tokens is not None:
            try:
                # Some callers can pass tokens as string/float.
                parsed_tokens = int(float(tokens))
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid tokens value for %s/%s: %r",
                    target_field,
                    service_name,
                    tokens,
                )

        if parsed_tokens > 0:
            update_data["total_tokens"] = parsed_tokens
            
        await users.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": update_data},
        )
    except Exception as e:
        logger.error(f"Failed to increment {target_field} for user {user_id} service {service_name}: {e}", exc_info=True)
        # We don't raise here to avoid blocking the main request flow for a metric update failure
