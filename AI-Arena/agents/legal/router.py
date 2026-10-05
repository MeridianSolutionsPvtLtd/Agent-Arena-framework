"""
agents/legal/router.py
Legal Agent endpoints.
"""
import io
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from fastapi.responses import Response
from pydantic import BaseModel

from agents.legal.client import LegalAgentClient
from agents.legal.utils import generate_pdf_from_text
from services.blob_service import upload_user_file
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/legal", tags=["Legal Agent"])

LEGAL_SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".doc", ".txt", ".rtf")

_legal_agent_client_instance = None


def get_legal_agent_client():
    global _legal_agent_client_instance
    if _legal_agent_client_instance is None:
        try:
            _legal_agent_client_instance = LegalAgentClient()
        except Exception as e:
            logger.error(f"Failed to initialize LegalAgentClient: {e}")
            raise HTTPException(
                status_code=503,
                detail="Legal Agent service is currently unavailable. Please check agent configurations."
            )
    return _legal_agent_client_instance


def _legal_read_text_from_upload(upload: UploadFile) -> str:
    upload.file.seek(0)
    content: bytes = upload.file.read()
    return _legal_read_text_from_bytes(content, upload.filename or "")


def _legal_read_text_from_bytes(content: bytes, filename: str) -> str:
    filename = (filename or "").lower()
    if filename.endswith(".txt") or filename.endswith(".rtf"):
        return content.decode("utf-8", errors="replace")
    elif filename.endswith(".pdf"):
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            text = "\n".join(pages).strip()
            if text:
                return text
        except Exception as e:
            logger.warning(f"pdfplumber failed: {e}")
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n".join(pages).strip()
            if text:
                return text
        except Exception as e:
            logger.warning(f"pypdf fallback failed: {e}")
        raise HTTPException(
            status_code=400,
            detail="Could not extract text from the PDF. It may be scanned or corrupted.",
        )
    elif filename.endswith((".docx", ".doc")):
        try:
            import docx
            doc = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="DOCX parsing requires 'python-docx'.",
            )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported: {', '.join(LEGAL_SUPPORTED_EXTENSIONS)}",
        )


def _legal_build_analysis_prompt(document_text: str, filename: str, context: Optional[str]) -> str:
    prompt = f"Please perform a comprehensive Indian Legal Document Analysis on the following document.\n\nDOCUMENT NAME\n=============\n{filename}\n\nDOCUMENT CONTENT\n================\n{document_text}\n"
    if context:
        prompt += f"\nADDITIONAL CONTEXT FROM USER\n=============================\n{context}\n"
    prompt += "\nPlease structure your analysis under the following mandatory headings:\n1. 🔍 Risk & Legal Gaps\n2. ⚖️ Compliance (Indian Law / Corporate Law / Tax Law)\n3. 🧾 Clause-by-Clause Feedback\n4. 🛑 Red Flags & Unfavorable Terms\n5. ✍️ Suggestions to Improve or Renegotiate Clauses\n6. 📌 Summary in Simple Language for Management\n"
    return prompt


class LegalChatRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None


class LegalChatResponse(BaseModel):
    thread_id: str
    response: str
    status: str


class LegalDraftRequest(BaseModel):
    document_type: str
    parties: Optional[str] = None
    context: Optional[str] = None
    thread_id: Optional[str] = None


class LegalMessageHistoryResponse(BaseModel):
    thread_id: str
    messages: List[dict]


class LegalDownloadPdfRequest(BaseModel):
    text: str
    filename: Optional[str] = "drafted_document.pdf"


@router.post("/chat", response_model=LegalChatResponse)
async def legal_chat(request: LegalChatRequest, current_user: dict = Depends(get_current_user)):
    """General Legal Chat & Text Analysis (Combined)"""
    client = get_legal_agent_client()
    try:
        result = client.run_query(prompt=request.query, thread_id=request.thread_id)

        # Update hits and tokens
        token_count = result.get("usage", {}).get("total_tokens", 0)
        await increment_hit_count(current_user["_id"], "legal_agent", target_field="agent_hits", tokens=token_count)

        return LegalChatResponse(**result)
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Chat failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze")
async def legal_analyze_document(
    file: UploadFile = File(...),
    context: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """File-based Document Analysis"""
    try:
        # 1. Upload to Blob Storage and update storage tracking
        blob_info = await upload_user_file(current_user["_id"], file)

        # 2. Extract text from the content (using the bytes from blob_info)
        document_text = _legal_read_text_from_bytes(blob_info["content"], file.filename)
        if not document_text.strip():
            raise HTTPException(status_code=400, detail="Document appears to be empty.")

        prompt = _legal_build_analysis_prompt(document_text, file.filename or "Document", context)
        client = get_legal_agent_client()
        result = client.run_query(prompt=prompt)

        # Update hits and tokens
        token_count = result.get("usage", {}).get("total_tokens", 0)
        await increment_hit_count(current_user["_id"], "legal_agent", target_field="agent_hits", tokens=token_count)

        return LegalChatResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/draft", response_model=LegalChatResponse)
async def legal_draft_document(request: LegalDraftRequest, current_user: dict = Depends(get_current_user)):
    """Legal Document Drafting"""
    try:
        parts = [
            f"Please draft a highly professional Indian legal document for a '{request.document_type}' immediately from scratch.",
            "DO NOT mention anything about template libraries, and DO NOT ask for permission or further details before drafting. Simply output the full content of the document based on the information provided below. If you need more info, make safe assumptions based on standard Indian legal practices."
        ]
        if request.parties:
            parts.append(f"\nParties involved:\n{request.parties}")
        if request.context:
            parts.append(f"\nAdditional context / instructions:\n{request.context}")

        prompt = "\n".join(parts)
        client = get_legal_agent_client()
        result = client.run_query(prompt=prompt, thread_id=request.thread_id)

        # Update hits and tokens
        token_count = result.get("usage", {}).get("total_tokens", 0)
        await increment_hit_count(current_user["_id"], "legal_agent", target_field="agent_hits", tokens=token_count)

        return LegalChatResponse(**result)
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Drafting failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{thread_id}", response_model=LegalMessageHistoryResponse)
async def legal_get_history(thread_id: str, current_user: dict = Depends(get_current_user)):
    """Retrieve Thread History"""
    client = get_legal_agent_client()
    try:
        messages = client.get_thread_messages(thread_id)
        return {"thread_id": thread_id, "messages": messages}
    except Exception as e:
        logger.exception("History retrieval failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download-pdf")
async def legal_download_pdf(request: LegalDownloadPdfRequest):
    """Generate and download PDF from text/markdown."""
    try:
        pdf_bytes = generate_pdf_from_text(request.text)
        headers = {
            'Content-Disposition': f'attachment; filename="{request.filename or "drafted_document.pdf"}"'
        }
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
    except Exception as e:
        logger.exception("PDF generation failed")
        raise HTTPException(status_code=500, detail=str(e))
