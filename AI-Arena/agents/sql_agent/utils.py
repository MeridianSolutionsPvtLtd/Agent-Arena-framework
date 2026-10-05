import os
import logging
import shutil
import pandas as pd
import duckdb
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

# Existing backend imports
from database import get_db
from middleware.auth import get_current_user

# Internal imports
from .engine import ChatWithDatabase

logger = logging.getLogger(__name__)

# Global cache for engines (one per database)
_engine_cache = {}

def _cache_key(cred: Dict[str, Any]) -> str:
    """Build cache key from database name."""
    return str(cred.get("db_name", "test.db"))

def _get_engine(sql_credential: Dict[str, Any]):
    """Get or create ChatWithDatabase for this connection."""
    key = _cache_key(sql_credential)
    if key in _engine_cache:
        return _engine_cache[key]
    
    # Simple DuckDB engine
    db_name = key
    if not db_name.endswith('.db'):
        db_name = f"{db_name}.db"
    
    db_dir = Path("databases")
    db_dir.mkdir(exist_ok=True)
    db_path = str(db_dir / db_name)
    
    engine = ChatWithDatabase(db_path=db_path)
    _engine_cache[key] = engine
    return engine

def process_sql_chat(question: str, sql_credential: Dict[str, Any]) -> Dict[str, Any]:
    """Process a natural-language question against the user's DuckDB database."""
    question = (question or "").strip()
    if not question:
        return {"bot_answer": "Please ask a question about your data."}

    try:
        engine = _get_engine(sql_credential)
        result = engine.ask(question)
        
        if result.get("success"):
            return {
                "bot_answer": result.get("response", "No answer generated."),
                "sql": result.get("sql"),
                "data": result.get("data"),
            }
        
        error_msg = result.get("error") or "Unknown error"
        return {"bot_answer": f"Query failed: {error_msg}"}

    except Exception as e:
        logger.exception("SQL chat processing failed")
        return {"bot_answer": f"Sorry, I couldn't process that question: {str(e)}"}

def ingest_to_duckdb(file_path: str, db_name: str = None, table_name: str = None) -> bool:
    """Ingest a CSV or Excel file into DuckDB using native DuckDB connection."""
    if not db_name:
        db_name = os.getenv('DB_NAME', 'test.db')
    
    if not db_name.endswith('.db'):
        db_name = f"{db_name}.db"

    db_dir = Path("databases")
    db_dir.mkdir(exist_ok=True)
    abs_db_path = str(db_dir / db_name)
    
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False
    
    if not table_name:
        table_name = Path(file_path).stem.replace(" ", "_").lower()
    
    try:
        # Load data with pandas
        ext = Path(file_path).suffix.lower()
        if ext == '.csv':
            df = pd.read_csv(file_path)
        elif ext in ('.xlsx', '.xls'):
            df = pd.read_excel(file_path)
        else:
            logger.error(f"Unsupported extension: {ext}")
            return False
           
        # Use native duckdb to ingest
        conn = duckdb.connect(abs_db_path)
        try:
            # Sanitize table name (replace hyphens with underscores)
            sanitized_name = table_name.replace('-', '_')
            
            # Register the dataframe and create/replace table
            conn.register('temp_df', df)
            conn.execute(f'CREATE OR REPLACE TABLE "{sanitized_name}" AS SELECT * FROM temp_df')
            logger.info(f"Successfully ingested {len(df)} rows into {sanitized_name} in {abs_db_path}")
            return True
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"DuckDB Ingestion error: {e}")
        return False

async def register_duckdb_mapping(user_id: str, db_name: str, table_name: str):
    """Store database mapping in MongoDB."""
    db = get_db()
    mapping = {
        "user_id": user_id,
        "db_name": db_name,
        "table_name": table_name,
        "type": "duckdb",
        "created_at": datetime.utcnow().isoformat()
    }
    await db.db_mappings.update_one(
        {"user_id": user_id, "db_name": db_name},
        {"$set": mapping},
        upsert=True
    )
