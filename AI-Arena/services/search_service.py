import uuid
import io
from datetime import datetime, timezone
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchFieldDataType,
)
from azure.core.credentials import AzureKeyCredential
from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers – text extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(file_data: bytes) -> str:
    """Extract text from a PDF using PyPDF2."""
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(file_data))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n".join(pages)


def extract_text_from_docx(file_data: bytes) -> str:
    """Extract text from a DOCX using python-docx."""
    from docx import Document

    doc = Document(io.BytesIO(file_data))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def extract_text_from_txt(file_data: bytes) -> str:
    """Decode plain text bytes."""
    return file_data.decode("utf-8", errors="replace")


def extract_text(file_data: bytes, filename: str) -> str:
    """Route to the correct extractor based on file extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        return extract_text_from_pdf(file_data)
    elif ext in ("docx",):
        return extract_text_from_docx(file_data)
    elif ext in ("txt", "md", "csv", "json", "log"):
        return extract_text_from_txt(file_data)
    else:
        raise ValueError(f"Unsupported file type: .{ext}. Supported: PDF, DOCX, TXT, MD, CSV, JSON, LOG")


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def _get_creds(credentials: dict | None = None, user_id: str = None):
    creds = credentials or {}
    endpoint = creds.get("AZURE_SEARCH_ENDPOINT") or settings.AZURE_SEARCH_ENDPOINT
    key = creds.get("AZURE_SEARCH_API_KEY") or settings.AZURE_SEARCH_API_KEY
    
    if not user_id:
        raise ValueError("User ID is required to determine the search index.")
        
    # Generate index name from user ID (sanitize if needed, but user_id is usually safe)
    # Azure Search index names must be lowercase, alphanumeric, dashes allowed
    index_name = f"user-{user_id.lower()}"

    if not endpoint or not key:
        raise ValueError(
            "Azure Search credentials are not configured. Please add them in your profile."
        )
    return endpoint, key, index_name


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------

def _build_index_schema(index_name: str) -> SearchIndex:
    """Define the search index schema."""
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SearchableField(name="title", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="file_type", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="file_size", type=SearchFieldDataType.Int64),
        SimpleField(name="upload_date", type=SearchFieldDataType.String, filterable=True, sortable=True),
    ]
    return SearchIndex(name=index_name, fields=fields)


async def ensure_index_exists(credentials: dict | None = None, user_id: str = None):
    """Create or update the index so the required fields are always present."""
    endpoint, key, index_name = _get_creds(credentials, user_id)
    index_client = SearchIndexClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    try:
        index_client.create_or_update_index(
            _build_index_schema(index_name),
            allow_index_downtime=True,
        )
        logger.info(f"Index '{index_name}' is ready (created or updated).")
    except Exception as e:
        logger.error(f"Failed to create/update index '{index_name}': {e}", exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Document upload / indexing
# ---------------------------------------------------------------------------

async def upload_and_index_document(
    file_data: bytes,
    filename: str,
    credentials: dict | None = None,
    user_id: str = None,
) -> dict:
    """
    Extract text from a file, then push it into the Azure Search index.
    Returns metadata about the indexed document.
    """
    endpoint, key, index_name = _get_creds(credentials, user_id)

    # 1. Ensure the index exists
    await ensure_index_exists(credentials, user_id)

    # 2. Extract text
    content = extract_text(file_data, filename)
    if not content.strip():
        raise ValueError("The uploaded file appears to be empty or could not be parsed.")

    # 3. Build the document
    doc_id = uuid.uuid4().hex[:16]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
    now = datetime.now(timezone.utc).isoformat()

    doc = {
        "id": doc_id,
        "title": filename,
        "content": content[:32000],  # Azure Search string field limit safety
        "file_type": ext,
        "file_size": len(file_data),
        "upload_date": now,
    }

    # 4. Push into the index
    search_client = SearchClient(
        endpoint=endpoint, index_name=index_name, credential=AzureKeyCredential(key)
    )
    result = search_client.upload_documents(documents=[doc])
    logger.info(f"Indexed document '{filename}' into '{index_name}' as id={doc_id}, result={result[0].succeeded}")

    if not result[0].succeeded:
        raise RuntimeError(f"Failed to index document: {result[0].error_message}")

    return {
        "id": doc_id,
        "title": filename,
        "file_type": ext,
        "file_size": len(file_data),
        "content_preview": content[:200],
        "upload_date": now,
    }


# ---------------------------------------------------------------------------
# List indexed documents
# ---------------------------------------------------------------------------

async def list_indexed_documents(credentials: dict | None = None, user_id: str = None) -> list[dict]:
    """Return all documents in the search index (metadata only)."""
    endpoint, key, index_name = _get_creds(credentials, user_id)
    search_client = SearchClient(
        endpoint=endpoint, index_name=index_name, credential=AzureKeyCredential(key)
    )

    try:
        results = search_client.search(
            search_text="*",
            select=["id", "title", "file_type", "file_size", "upload_date"],
            top=100,
        )
        docs = []
        for r in results:
            docs.append({
                "id": r["id"],
                "title": r.get("title", "Untitled"),
                "file_type": r.get("file_type", "unknown"),
                "file_size": r.get("file_size", 0),
                "upload_date": r.get("upload_date", ""),
            })
        return docs
    except Exception as e:
        logger.warning(f"Could not list documents from '{index_name}' (index may not exist yet): {e}")
        return []


# ---------------------------------------------------------------------------
# Delete document from index
# ---------------------------------------------------------------------------

async def delete_document(doc_id: str, credentials: dict | None = None, user_id: str = None):
    """Remove a single document from the index by its id."""
    endpoint, key, index_name = _get_creds(credentials, user_id)
    search_client = SearchClient(
        endpoint=endpoint, index_name=index_name, credential=AzureKeyCredential(key)
    )
    search_client.delete_documents(documents=[{"id": doc_id}])
    logger.info(f"Deleted document id={doc_id} from index '{index_name}'")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

async def search_documents(
    query: str,
    top: int = 10,
    credentials: dict | None = None,
    user_id: str = None,
) -> list[dict]:
    """Run a search query against the index and return formatted results."""
    endpoint, key, index_name = _get_creds(credentials, user_id)
    
    # Check if index exists first to avoid 404s on fresh users
    try:
        index_client = SearchIndexClient(endpoint=endpoint, credential=AzureKeyCredential(key))
        index_client.get_index(index_name)
    except Exception:
        logger.info(f"Index '{index_name}' not found during search. Returning empty result.")
        return []

    search_client = SearchClient(
        endpoint=endpoint, index_name=index_name, credential=AzureKeyCredential(key)
    )

    try:
        results = search_client.search(
            search_text=query,
            top=top,
            include_total_count=True,
        )
        output = []
        for r in results:
            content = r.get("content", "")
            output.append({
                "id": r.get("id", ""),
                "title": r.get("title", "Untitled"),
                "content": content[:500] if content else "",
                "file_type": r.get("file_type", ""),
                "score": r.get("@search.score", 0),
            })
        return output
    except Exception as e:
        logger.error(f"Error in Search service: {e}", exc_info=True)
        raise e

