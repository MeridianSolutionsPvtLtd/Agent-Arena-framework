"""
Service logic for Recruitment/ATS Agent.
"""
import os
import io
import json
import re
import asyncio
import logging
import time
import pandas as pd
from typing import List, Dict, Any
from pypdf import PdfReader
from agents.common.azure_agent_client import AzureAgentClient
from agents.common.utils import extract_json_from_response

logger = logging.getLogger(__name__)

# Lazy-initialized agent client
_azure_agent_instance = None

def get_azure_agent():
    """Returns a singleton AzureAgentClient instance for ATS, initializing it on first call."""
    global _azure_agent_instance
    if _azure_agent_instance is None:
        agent_id = os.getenv("ATS_AGENT_ID")
        if not agent_id:
            logger.warning("ATS_AGENT_ID not found in environment, using fallback")
            agent_id = "asst_cjcAshIAPbjB45xIfVIrYqVf"
        
        try:
            _azure_agent_instance = AzureAgentClient(agent_id)
            logger.info(f"ATS Azure Agent initialized: {agent_id}")
        except Exception as e:
            logger.error(f"Failed to initialize Azure Agent for ATS: {e}")
            raise Exception(f"Recruitment Agent (ATS) initialization failed: {e}")
            
    return _azure_agent_instance

def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from a PDF file using pypdf, with pdfplumber fallback."""
    try:
        with open(file_path, "rb") as f:
            content = f.read()
        return extract_text_from_bytes(content, os.path.basename(file_path))
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return ""

def extract_text_from_bytes(content: bytes, filename: str) -> str:
    """Extract text from a PDF content (bytes) using pypdf, with pdfplumber fallback."""
    # Try pypdf first (faster)
    try:
        reader = PdfReader(io.BytesIO(content))
        full_text = []
        for page in reader.pages:
            content = page.extract_text()
            if content:
                full_text.append(content)
        text = "\n".join(full_text).strip()
        if text:
            return text
    except Exception as e:
        logger.warning(f"pypdf extraction failed: {e}")

    # Fallback to pdfplumber (handles more formats)
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(pages).strip()
        if text:
            logger.info("pdfplumber fallback succeeded")
            return text
    except ImportError:
        logger.warning("pdfplumber not installed, skipping fallback")
    except Exception as e:
        logger.warning(f"pdfplumber extraction failed: {e}")

    return ""



async def generate_jd(role: str) -> str:
    """Generate a job description for a given role."""
    from agents.recruitment.prompts import get_jd_generation_prompt
    prompt = get_jd_generation_prompt(role)

    agent = get_azure_agent()
    if not agent:
        return "Error: Azure Agent not initialized"

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: agent.run_analysis(prompt)
    )

    return result.get("response", "No response from agent")


async def analyze_single_resume(resume_text: str, jd_text: str) -> Dict[str, Any]:
    """Analyze a single resume against a JD — full detailed analysis (15+ fields)."""
    from agents.recruitment.prompts import get_resume_analysis_prompt
    prompt = get_resume_analysis_prompt(resume_text, jd_text)

    agent = get_azure_agent()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: agent.run_analysis(prompt)
    )

    result_str = result.get("response", "")
    analysis = extract_json_from_response(result_str)
    
    # Store usage and thread ID
    analysis["thread_id"] = result.get("thread_id")
    analysis["token_usage"] = result.get("usage", {})
    return analysis


async def analyze_batch_single(resume_text: str, jd_text: str) -> Dict[str, Any]:
    """Lighter analysis for batch processing — returns only name/email/jScore/gScore."""
    from agents.recruitment.prompts import get_batch_score_prompt
    prompt = get_batch_score_prompt(resume_text, jd_text)

    agent = get_azure_agent()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: agent.run_analysis(prompt)
    )

    result_str = result.get("response", "")
    analysis = extract_json_from_response(result_str)
    analysis["thread_id"] = result.get("thread_id")
    analysis["token_usage"] = result.get("usage", {})
    return analysis


async def analyze_batch_resumes(file_paths: List[str], jd_text: str) -> List[Dict[str, Any]]:
    """Analyze multiple resumes sequentially with per-file tracking."""
    results = []
    total_files = len(file_paths)

    for idx, path in enumerate(file_paths):
        file_name = os.path.basename(path)
        logger.info(f"Processing file {idx + 1} of {total_files}: {file_name}")
        start_time = time.time()

        try:
            resume_text = extract_text_from_pdf(path)
            if not resume_text:
                results.append({
                    "fileName": file_name,
                    "name": "Error",
                    "email": "Error",
                    "jScore": 0,
                    "gScore": 0,
                    "status": "Failed",
                    "processingTime": "0s",
                    "error": "Could not extract text from PDF"
                })
                continue

            analysis = await analyze_batch_single(resume_text, jd_text)
            elapsed = round(time.time() - start_time, 1)

            # Normalize list fields to comma-separated strings for Excel
            top_skills = analysis.get("top_matching_skills", [])
            missing_skills = analysis.get("missing_critical_skills", [])

            results.append({
                "fileName": file_name,
                "name": analysis.get("name", "Unknown"),
                "email": analysis.get("email", "Unknown"),
                "phone": analysis.get("phone", "Not Found"),
                "experience_level": analysis.get("experience_level", "N/A"),
                "total_experience": analysis.get("total_experience", "N/A"),
                "education": analysis.get("education", "N/A"),
                "top_matching_skills": ", ".join(top_skills) if isinstance(top_skills, list) else str(top_skills),
                "missing_critical_skills": ", ".join(missing_skills) if isinstance(missing_skills, list) else str(missing_skills),
                "key_strengths": analysis.get("key_strengths", "N/A"),
                "key_gaps": analysis.get("key_gaps", "N/A"),
                "jScore": analysis.get("jScore", 0),
                "gScore": analysis.get("gScore", 0),
                "recommendation": analysis.get("recommendation", "N/A"),
                "status": "Completed",
                "processingTime": f"{elapsed}s",
                "error": "None",
                "token_usage": analysis.get("token_usage", {})
            })
            logger.info(f"Completed {file_name}: jScore={analysis.get('jScore', 0)}, recommendation={analysis.get('recommendation', 'N/A')}")

        except Exception as e:
            elapsed = round(time.time() - start_time, 1)
            logger.error(f"Error processing {file_name}: {e}")
            results.append({
                "fileName": file_name,
                "name": "Error",
                "email": "Error",
                "jScore": 0,
                "gScore": 0,
                "status": "Failed",
                "processingTime": f"{elapsed}s",
                "error": str(e)
            })

        # Small delay between files to avoid rate limiting
        await asyncio.sleep(1)

    # Sort by jScore descending
    results.sort(key=lambda r: r.get("jScore", 0), reverse=True)
    return results


def create_excel_report(analysis_results: List[Dict[str, Any]], output_path: str):
    """Generate an Excel report from batch analysis results — full 8-column format."""
    data = []
    for res in analysis_results:
        data.append({
            "File Name": res.get("fileName", "Unknown"),
            "Candidate Name": res.get("name", "Unknown"),
            "Email": res.get("email", "Unknown"),
            "Phone": res.get("phone", "Not Found"),
            "Experience Level": res.get("experience_level", "N/A"),
            "Total Experience": res.get("total_experience", "N/A"),
            "Education": res.get("education", "N/A"),
            "JD Score (%)": res.get("jScore", 0),
            "General Score (%)": res.get("gScore", 0),
            "Recommendation": res.get("recommendation", "N/A"),
            "Top Matching Skills": res.get("top_matching_skills", "N/A"),
            "Missing Critical Skills": res.get("missing_critical_skills", "N/A"),
            "Key Strengths": res.get("key_strengths", "N/A"),
            "Key Gaps": res.get("key_gaps", "N/A"),
            "Status": res.get("status", "Unknown"),
            "Processing Time": res.get("processingTime", "N/A"),
            "Error (if any)": res.get("error", "None"),
        })

    df = pd.DataFrame(data)

    # Auto-adjust column widths for readability
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Candidates")
        ws = writer.sheets["Candidates"]
        for col_idx, col in enumerate(df.columns, 1):
            max_len = max(len(str(col)), df[col].astype(str).str.len().max())
            ws.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else 'A' + chr(64 + col_idx - 26)].width = min(max_len + 3, 50)

    return output_path
