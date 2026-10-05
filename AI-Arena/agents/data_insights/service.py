import pandas as pd
import io
import os
import logging
from typing import Optional, Any
from agents.common.azure_agent_client import AzureAgentClient

logger = logging.getLogger(__name__)

class DataInsightsService:
    def __init__(self):
        self.agent_id = os.getenv("DATA_INSIGHTS_AGENT_ID")
        self._client = None

    def get_client(self):
        """Lazy-initialize the Azure Agent client."""
        if self._client is None:
            if not self.agent_id:
                raise ValueError("DATA_INSIGHTS_AGENT_ID not found in environment variables")
            logger.info(f"Initializing Data Insights Azure Agent: {self.agent_id}")
            self._client = AzureAgentClient(self.agent_id)
        return self._client

    def _read_data(self, content: bytes, filename: str) -> pd.DataFrame:
        """Parse uploaded file into a DataFrame with signature-based detection."""
        ext = filename.lower().split('.')[-1]
        
        # Check first 8-16 bytes for signature detection
        header = content[:16]
        header_hex = header.hex(' ').upper()
        
        is_zip = header.startswith(b'PK\x03\x04')
        is_xls_legacy = header.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')

        # Diagnostic log
        logger.info(f"File Analysis: {filename} | Ext: {ext} | Header: {header_hex}")

        try:
            if is_zip:
                # Likely .xlsx or other zip-based format
                return pd.read_excel(io.BytesIO(content), engine="openpyxl")
            
            if is_xls_legacy:
                # Likely .xls (legacy Excel)
                return pd.read_excel(io.BytesIO(content), engine="xlrd")

            # Fallback based on extension - try CSV/Text first if extension suggests it or it's not binary
            if ext in ["csv", "xlsx", "xls", "txt"]:
                # Try common delimiters for text-based files
                for sep in [',', '\t', ';']:
                    try:
                        io_buf = io.BytesIO(content)
                        return pd.read_csv(io_buf, sep=sep)
                    except Exception:
                        continue

            if ext == "json":
                return pd.read_json(io.BytesIO(content))
            
            # Final attempt using extension if signature didn't match anything specific
            if ext == "xlsx":
                return pd.read_excel(io.BytesIO(content), engine="openpyxl")
            elif ext == "xls":
                return pd.read_excel(io.BytesIO(content), engine="xlrd")
                
            raise ValueError(f"No matching parser for file signature: {header_hex}")
        except Exception as e:
            logger.error(f"Error parsing {filename} (Signature: {header_hex}): {e}")
            detail = f"Could not parse {filename}. Error: {e}. Signature: {header_hex}"
            # If it's a specific "zip file" error from openpyxl, provide a helpful message
            if "not a zip file" in str(e).lower() and not is_zip:
                detail = f"The file {filename} is named as .xlsx but is not a valid Excel Zip file. (Signature: {header_hex})"
            raise ValueError(detail)

    def _dataframe_to_prompt(self, df: pd.DataFrame, context: Optional[str]) -> str:
        """Convert a DataFrame into a structured prompt for the agent."""
        rows, cols = df.shape
        schema = df.dtypes.reset_index()
        schema.columns = ["Column", "DType"]
        schema_str = schema.to_string(index=False)
        
        # Get sample data (first 20 rows)
        sample = df.head(20).to_csv(index=False)
        
        # Get statistical summary
        stats = df.describe(include="all").to_string()

        prompt = f"""Please perform a comprehensive Data Insights Analysis on the following dataset.

# 📊 Dataset Overview
- **Rows**: {rows}
- **Columns**: {cols}

## 📋 Schema Information
```
{schema_str}
```

## 📈 Statistical Summary
```
{stats}
```

## 🔍 Sample Data (First 20 Rows)
```csv
{sample}
```
"""
        if context:
            prompt += f"\n## 💡 Additional Business Context\n{context}\n"

        prompt += """
Please provide:
1. **Executive Summary**: High-level overview of the data.
2. **Key Metrics & KPIs**: Important numbers derived from the data.
3. **Trend Analysis**: Patterns or changes over time (if applicable).
4. **Anomalies & Gaps**: Any data quality issues or unusual outliers.
5. **Strategic Recommendations**: Actionable insights for business owners.
"""
        return prompt

    async def analyze_text(self, data: str, context: Optional[str] = None) -> dict[str, Any]:
        """Analyze raw text or pasted tabular data."""
        client = self.get_client()
        prompt = f"# Data Analysis Request\n\n## 📝 Provided Data\n{data}"
        if context:
            prompt += f"\n\n## 💡 Context\n{context}"
        
        prompt += "\n\nPlease perform a full Data Insights Analysis on this data."
        logger.info(f"Text analysis prompt generated. Length: {len(prompt)}")
        result = client.run_analysis(prompt)
        logger.info(f"Agent (Text) response length: {len(result.get('response', ''))}")
        return result

    async def analyze_file(self, content: bytes, filename: str, context: Optional[str] = None) -> dict[str, Any]:
        """Analyze an uploaded file (CSV/Excel/JSON)."""
        client = self.get_client()
        try:
            df = self._read_data(content, filename)
            prompt = self._dataframe_to_prompt(df, context)
            logger.info(f"Analysis prompt generated for {filename}. Length: {len(prompt)}")
            result = client.run_analysis(prompt)
            logger.info(f"Agent (File) response length: {len(result.get('response', ''))}")
            return result
        except Exception as e:
            logger.error(f"Error in analyze_file: {e}")
            raise e
