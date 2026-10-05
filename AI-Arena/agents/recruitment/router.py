"""
agents/recruitment/router.py
Recruitment agent endpoints.
"""
import os
import shutil
import tempfile
from typing import List

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from fastapi.responses import FileResponse

from agents.recruitment.service import (
    extract_text_from_bytes,
    generate_jd,
    analyze_single_resume,
    analyze_batch_resumes,
    create_excel_report
)
from services.blob_service import upload_user_file
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/recruitment", tags=["recruitment"])


@router.post("/generate-jd")
async def recruitment_generate_jd(role: str = Form(...), user=Depends(get_current_user)):
    """Generate a job description."""
    try:
        jd = await generate_jd(role)
        return {"success": True, "role": role, "jobDescription": jd}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"JD generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate JD")


@router.post("/analyze/single")
async def recruitment_analyze_single(
    file: UploadFile = File(...),
    jd_text: str = Form(...),
    user=Depends(get_current_user)
):
    """Analyze a single resume."""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, file.filename)

    try:
        # 1. Upload to Blob Storage and update storage tracking
        blob_info = await upload_user_file(user["_id"], file)

        # 2. Extract text from the content (using the bytes from blob_info)
        resume_text = extract_text_from_bytes(blob_info["content"], file.filename)
        if not resume_text:
            raise HTTPException(status_code=400, detail="Could not extract text from PDF")

        result = await analyze_single_resume(resume_text, jd_text)

        # Update user stats
        token_count = result.get("token_usage", {}).get("total_tokens", 0)
        await increment_hit_count(user["_id"], "recruitment", target_field="agent_hits", tokens=token_count)

        return result

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Single analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/analyze/batch")
async def recruitment_analyze_batch(
    files: List[UploadFile] = File(...),
    jd_text: str = Form(...),
    user=Depends(get_current_user)
):
    """Analyze multiple resumes and return an Excel report."""
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files allowed for batch processing")

    temp_dir = tempfile.mkdtemp()
    file_paths = []

    try:
        for file in files:
            if not file.filename.lower().endswith('.pdf'):
                continue

            # Upload to Blob Storage and update storage tracking
            blob_info = await upload_user_file(user["_id"], file)

            # Save to temp for the existing batch analysis logic which expects file paths
            path = os.path.join(temp_dir, file.filename)
            with open(path, "wb") as f:
                f.write(blob_info["content"])
            file_paths.append(path)

        if not file_paths:
            raise HTTPException(status_code=400, detail="No valid PDF files uploaded")

        results = await analyze_batch_resumes(file_paths, jd_text)

        # Generate Excel in a subfolder or temp file
        report_filename = "resume_analysis_report.xlsx"
        report_path = os.path.join(temp_dir, report_filename)
        create_excel_report(results, report_path)

        # Update user stats (sum tokens)
        total_tokens = sum(r.get("token_usage", {}).get("total_tokens", 0) for r in results if "token_usage" in r)
        await increment_hit_count(user["_id"], "recruitment", target_field="agent_hits", tokens=total_tokens)

        return FileResponse(
            report_path,
            filename=report_filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Batch analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
