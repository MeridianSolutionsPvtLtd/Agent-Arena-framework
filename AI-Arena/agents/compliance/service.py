import os
import io
import logging
from typing import Optional, Any
from fastapi import UploadFile, HTTPException
from agents.common.azure_agent_client import AzureAgentClient

logger = logging.getLogger(__name__)

class ComplianceService:
    def __init__(self):
        self.agent_id = os.getenv("COMPLIANCE_AGENT_ID")
        self._client = None
        self.supported_extensions = (".pdf", ".docx", ".doc", ".txt", ".rtf")

    def get_client(self):
        """Lazy-initialize the Azure Agent client."""
        if self._client is None:
            if not self.agent_id:
                raise ValueError("COMPLIANCE_AGENT_ID not found in environment variables")
            logger.info(f"Initializing Compliance Azure Agent: {self.agent_id}")
            self._client = AzureAgentClient(self.agent_id)
        return self._client

    def run_analysis(self, prompt: str, thread_id: Optional[str] = None):
        return self.get_client().run_analysis(prompt, thread_id)

    def get_thread_messages(self, thread_id: str):
        return self.get_client().get_thread_messages(thread_id)

    def read_text_from_upload(self, upload: UploadFile) -> str:
        """Extract raw text from an uploaded document file."""
        upload.file.seek(0)
        content: bytes = upload.file.read()
        return self.read_text_from_content(content, upload.filename or "")

    def read_text_from_content(self, content: bytes, filename: str) -> str:
        """Extract raw text from document content bytes."""
        filename = (filename or "").lower()

        if filename.endswith(".txt") or filename.endswith(".rtf"):
            return content.decode("utf-8", errors="replace")

        elif filename.endswith(".pdf"):
            # Try pdfplumber first
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    pages = [page.extract_text() or "" for page in pdf.pages]
                text = "\n".join(pages).strip()
                if text:
                    return text
            except Exception as e:
                logger.warning(f"pdfplumber failed: {e}")

            # Fallback to pypdf
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
            except Exception as e:
                logger.error(f"DOCX parsing failed: {e}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to parse Word document: {e}",
                )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type. Please upload: {', '.join(self.supported_extensions)}",
            )

    def build_analysis_prompt(self, document_text: str) -> str:
        """Construct a structured compliance analysis prompt."""
        prompt = f"""You are an expert Regulatory Compliance Auditor. 
Please perform a comprehensive compliance and policy analysis for the document provided below.

Structure your response using the following Markdown sections:

# 🛡️ Compliance & Policy Executive Summary
Provide a high-level overview of the document's compliance status.

## 📊 Key Compliance Metrics
- Overall Compliance Score: [Score out of 100]
- Critical Gaps Identified: [Count]
- Regulatory Alignment: [Status]

## 🔍 Detailed Gap Analysis
Identify specific areas where the policy falls short of standard regulatory requirements or best practices.

## 📋 Recommended Actions
Provide a bulleted list of prioritized steps to improve compliance.

## ⚖️ Regulatory Mapping
Map the document sections to relevant international or local standards if applicable.

DOCUMENT CONTENT:
================
{document_text}
"""
        return prompt
