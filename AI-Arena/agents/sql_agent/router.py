"""
agents/sql_agent/router.py
SQL Intelligence agent endpoints.
"""
import os
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from pydantic import BaseModel

from agents.sql_agent.utils import ingest_to_duckdb, process_sql_chat, register_duckdb_mapping
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/sql-agent", tags=["SQL Intelligence"])


class SqlQueryRequest(BaseModel):
    query: str
    database: str
    visibility: str = "local"


class SqlQueryResponse(BaseModel):
    bot_answer: str
    sql: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    sources: List[str] = []


@router.post("/upload")
async def sql_agent_upload(
    file: UploadFile = File(...),
    db_name: str = Form(...),
    table_name: Optional[str] = Form(None),
    user=Depends(get_current_user)
):
    """Upload and ingest data into DuckDB."""
    try:
        user_id = str(user["_id"])

        # 1. Create temporary directory for the upload
        temp_dir = Path("uploads") / "sql" / user_id
        temp_dir.mkdir(parents=True, exist_ok=True)
        file_path = temp_dir / file.filename

        # 2. Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 3. Ingest into DuckDB
        success = ingest_to_duckdb(str(file_path), db_name, table_name)
        if not success:
            # Cleanup before raising
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=500, detail="DuckDB ingestion failed")

        # 4. Register mapping in MongoDB
        effective_table = table_name or Path(file.filename).stem.replace(" ", "_").lower()
        await register_duckdb_mapping(user_id, db_name, effective_table)

        # 5. Cleanup temp file
        if os.path.exists(file_path):
            os.remove(file_path)

        return {
            "status": "success",
            "message": "Data ingested successfully",
            "database": db_name,
            "table": effective_table
        }

    except Exception as e:
        logger.error(f"SQL Upload failed: {e}")
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query", response_model=SqlQueryResponse)
async def sql_agent_query(request: SqlQueryRequest, user=Depends(get_current_user)):
    """Query ingested SQL data."""
    try:
        user_id = str(user["_id"])

        # Build credential for engine
        cred = {
            "user_id": user_id,
            "db_name": request.database,
            "db_type": "duckdb"
        }

        result = process_sql_chat(request.query, cred)
        return SqlQueryResponse(
            bot_answer=result.get("bot_answer", "Error processing query"),
            sql=result.get("sql"),
            data=result.get("data"),
            sources=[]
        )
    except Exception as e:
        logger.error(f"SQL Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
