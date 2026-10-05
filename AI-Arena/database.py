from motor.motor_asyncio import AsyncIOMotorClient
from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

client: AsyncIOMotorClient = None
db = None


async def connect_to_mongo():
    """Initialize MongoDB connection on app startup."""
    global client, db
    try:
        client = AsyncIOMotorClient(settings.MONGODB_URI)
        db = client[settings.MONGODB_NAME]
        # Verify connection
        await client.admin.command("ping")
        logger.info(f"Connected to MongoDB Atlas — database: {settings.MONGODB_NAME}")
    except Exception as e:
        logger.critical(f"Failed to connect to MongoDB: {e}", exc_info=True)
        raise e


async def close_mongo_connection():
    """Close MongoDB connection on app shutdown."""
    global client
    if client:
        client.close()
        logger.info("MongoDB connection closed")


def get_db():
    """Return the database instance."""
    return db


def get_users_collection():
    """Return the users collection."""
    return db[settings.MONGODB_COLLECTION_NAME]
