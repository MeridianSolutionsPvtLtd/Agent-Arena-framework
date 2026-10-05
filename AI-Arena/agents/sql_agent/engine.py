import os
import duckdb
import pandas as pd
import logging
from typing import Dict, List, Any, Optional
from openai import AzureOpenAI
from config import settings

logger = logging.getLogger(__name__)

class ChatWithDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version="2024-02-01"
        )
        self.deployment_name = settings.AZURE_OPENAI_DEPLOYMENT_NAME

    def _get_schema(self) -> str:
        """Extract table schemas from the DuckDB database."""
        conn = duckdb.connect(self.db_path)
        try:
            tables = conn.execute("SHOW TABLES").fetchall()
            schema_info = []
            for (table_name,) in tables:
                columns = conn.execute(f'DESCRIBE "{table_name}"').fetchall()
                col_info = ", ".join([f"{c[0]} ({c[1]})" for c in columns])
                schema_info.append(f'Table "{table_name}": {col_info}')
            return "\n".join(schema_info)
        finally:
            conn.close()

    def ask(self, question: str) -> Dict[str, Any]:
        """Generate SQL, execute it, and return the result."""
        try:
            schema = self._get_schema()
            if not schema:
                return {"success": False, "error": "No tables found in database. Please upload data first.", "response": "No data available."}

            # 1. Generate SQL
            prompt = f"""
You are a SQL expert. Given the following DuckDB schema, generate a valid SQL query to answer the user's question.
Return ONLY the SQL query, nothing else. No markdown formatting.

Schema:
{schema}

Question: {question}
SQL:"""
            
            response = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            sql = response.choices[0].message.content.strip()
            # Clean up potential markdown
            if "```sql" in sql:
                sql = sql.split("```sql")[1].split("```")[0].strip()
            elif "```" in sql:
                sql = sql.split("```")[1].split("```")[0].strip()

            logger.info(f"Generated SQL: {sql}")

            # 2. Execute SQL
            conn = duckdb.connect(self.db_path)
            try:
                df = conn.execute(sql).fetchdf()
                data = df.to_dict(orient="records")
                
                # 3. Summarize results (optional but helpful)
                summary_prompt = f"""
User asked: {question}
SQL executed: {sql}
Result summary (first 5 rows): {data[:5]}

Provide a brief, natural language answer based on the query results.
"""
                summary_response = self.client.chat.completions.create(
                    model=self.deployment_name,
                    messages=[{"role": "user", "content": summary_prompt}],
                    temperature=0
                )
                nl_answer = summary_response.choices[0].message.content.strip()

                return {
                    "success": True,
                    "sql": sql,
                    "data": data,
                    "response": nl_answer
                }
            finally:
                conn.close()

        except Exception as e:
            logger.error(f"Error in engine.ask: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": f"I encountered an error while processing your request: {str(e)}"
            }