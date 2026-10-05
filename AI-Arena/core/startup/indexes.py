"""Cosmos DB-compatible index management for all MongoDB collections.

Usage (in any ensure_indexes method):
    from core.startup.indexes import ensure_index
    await ensure_index(collection, [("field", ASCENDING)], unique=True, name="uq_my_index")

Design principles:
- Name-first deduplication: if the requested name already exists in
  index_information(), return immediately without calling create_index().
  This is the primary guard against Cosmos DB code-13/67 spam on 60-second probes.
- Structural fallback: if no name is provided (or name not found), compare
  key tuples. Cosmos DB strips sparse/unique flags from index_information()
  responses, so the option check is skipped when flags are absent — making
  a key-only match sufficient.
- Cosmos DB error codes handled gracefully (INFO, not error):
    13  — unique index cannot be modified (collection has an older definition)
    20  — partialFilterExpression not supported
    67  — cannot create unique index when collection has documents
    85  — IndexOptionsConflict
- Database/network failures still propagate so startup fails loudly.
- Identical behaviour on local MongoDB (name check still fires, no extra round-trip).
"""
from contextvars import ContextVar

from pymongo.errors import OperationFailure, PyMongoError
from utils.logger import get_logger

logger = get_logger(__name__)

# Optional warning accumulator — callers may set this to a list to collect
# non-fatal notices (used by health supervisor). Default: None (ignored).
warnings: ContextVar[list | None] = ContextVar("index_warnings", default=None)


def _normalize_keys(keys):
    """Normalise the *keys* argument to a list of (field, direction) tuples."""
    if isinstance(keys, str):
        return [(keys, 1)]
    if hasattr(keys, "items"):           # dict / SON
        keys = keys.items()
    return [
        (key, int(direction) if isinstance(direction, (int, float)) else direction)
        for key, direction in keys
    ]


def _matches(existing_index: dict, keys: list, options: dict, stored_name: str | None = None) -> bool:
    """Return True if *existing_index* satisfies the requested index definition."""
    requested_name = options.get("name")
    # Name match: if Cosmos DB stored the index under the exact requested name, done.
    if stored_name and requested_name and stored_name == requested_name:
        return True

    existing_keys = _normalize_keys(existing_index.get("key", []))
    if existing_keys != keys:
        return False

    # Cosmos DB often omits sparse/unique/hidden from index_information() responses.
    # Only fail the check when the flag IS present and contradicts the request.
    for flag in ("unique", "sparse", "hidden"):
        if flag in existing_index and bool(existing_index[flag]) != bool(options.get(flag, False)):
            return False

    if "expireAfterSeconds" in existing_index:
        if existing_index["expireAfterSeconds"] != options.get("expireAfterSeconds"):
            return False

    return True


def _notice(collection, keys: list, options: dict, reason: str) -> None:
    """Log a non-fatal index notice at INFO level (not WARNING/ERROR)."""
    label = options.get("name", str(keys))
    msg = f"Index {label} on {collection.name} was not changed: {reason}"
    logger.info("%s", msg)
    # Accumulate into the warnings context variable if a collector is active.
    pending = warnings.get()
    if pending is not None:
        pending.append(msg)


async def ensure_index(collection, keys, **options) -> None:
    """Create or verify a MongoDB index with full Cosmos DB compatibility.

    Never drops existing indexes or weakens uniqueness guarantees.
    Safe to call repeatedly (on startup and on 60-second recovery probes).
    """
    normalized_keys = _normalize_keys(keys)

    try:
        existing_indexes = await collection.index_information()
    except PyMongoError as exc:
        label = options.get("name", str(normalized_keys))
        raise RuntimeError(
            f"Unable to inspect indexes on {collection.name} ({label})"
        ) from exc

    # ── Fast-path: name-only check ────────────────────────────────────────────
    # Cosmos DB returns the exact name we stored but often strips option metadata,
    # making structural comparison unreliable. A name hit means the index exists.
    # This MUST run before the key loop to avoid spurious create_index attempts
    # every 60 seconds on recovery probes.
    requested_name = options.get("name")
    if requested_name and requested_name in existing_indexes:
        logger.debug("Index %s already exists on %s", requested_name, collection.name)
        return

    # ── Structural fallback: key + option comparison ──────────────────────────
    for stored_name, idx in existing_indexes.items():
        if _matches(idx, normalized_keys, options, stored_name=stored_name):
            logger.debug("Index already satisfied (%s) on %s", stored_name, collection.name)
            return

    # ── Attempt creation ──────────────────────────────────────────────────────
    try:
        await collection.create_index(normalized_keys, **options)
        logger.info(
            "Created required index %s on %s",
            options.get("name", normalized_keys),
            collection.name,
        )
        return

    except OperationFailure as exc:
        # Re-check after failure — another process may have created it.
        try:
            latest = await collection.index_information()
        except PyMongoError:
            latest = {}

        # Name re-check first (most reliable for Cosmos DB).
        if requested_name and requested_name in latest:
            return
        if any(_matches(idx, normalized_keys, options) for idx in latest.values()):
            return

        error_text = str(exc).lower()
        code = getattr(exc, "code", None)

        cosmos_immutable = (
            code in (13, 67, 85)
            or "unique index cannot be modified" in error_text
            or "cannot create unique index when collection contains documents" in error_text
            or "forbidden" in error_text
        )
        if cosmos_immutable:
            _notice(
                collection, normalized_keys, options,
                "Cosmos DB does not allow this index change on the existing "
                "collection; the application will use the current indexes",
            )
            return

        partial_unsupported = code == 20 or (
            "partial" in error_text and "partialfilterexpression" in error_text
        )
        if partial_unsupported:
            _notice(
                collection, normalized_keys, options,
                "partialFilterExpression is not supported by this database; "
                "the application will use the current indexes",
            )
            return

        # Any other OperationFailure is unexpected — propagate.
        raise RuntimeError(
            f"Index {options.get('name', normalized_keys)} on {collection.name} "
            f"could not be created (code={code})"
        ) from exc

    except PyMongoError as exc:
        raise RuntimeError(
            f"Index {options.get('name', normalized_keys)} on {collection.name} "
            "could not be created due to a database/connection error"
        ) from exc
