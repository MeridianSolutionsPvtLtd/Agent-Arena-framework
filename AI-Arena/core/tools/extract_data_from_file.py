import json
import os
import logging
import numpy as np
import fitz
import pandas as pd
from typing import Type, List, Dict, Any
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------- OCR ENGINE ----------------
def _ocr_fallback(file_path: str) -> Dict[str, Any]:
    """OCR fallback with status tracking"""
    result = {
        "ocr_used": False,
        "ocr_engine": None,
        "ocr_text": ""
    }

    try:
        doc = fitz.open(file_path)
        images = []

        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            images.append(arr)

    except Exception as e:
        return {
            "ocr_used": False,
            "ocr_error": f"Rasterization failed: {e}"
        }

    # Try Tesseract
    try:
        import pytesseract
        text = ""

        for img in images:
            text += pytesseract.image_to_string(img) + "\n"

        if text.strip():
            result.update({
                "ocr_used": True,
                "ocr_engine": "tesseract",
                "ocr_text": text.strip()
            })
            return result

    except Exception as e:
        logger.warning(f"Tesseract failed: {e}")

    # Try EasyOCR
    try:
        import easyocr
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)

        lines = []
        for img in images:
            texts = reader.readtext(img, detail=0, paragraph=True)
            lines.extend(texts)

        text = "\n".join(lines).strip()

        if text:
            result.update({
                "ocr_used": True,
                "ocr_engine": "easyocr",
                "ocr_text": text
            })
            return result

    except Exception as e:
        logger.warning(f"EasyOCR failed: {e}")

    return {
        "ocr_used": False,
        "ocr_error": "OCR failed on both engines"
    }


# ---------------- DATAFRAME HANDLER ----------------
def _dataframe_to_payload(df: pd.DataFrame, name="default") -> Dict[str, Any]:
    """Improved structured dataframe output"""

    # Normalize columns
    df.columns = [str(c).strip() for c in df.columns]

    # Drop fully empty rows
    df = df.dropna(how="all")

    row_count = len(df)

    # Smart truncation
    preview_df = df if row_count <= 500 else df.head(200)

    return {
        "name": name,
        "columns": list(df.columns),
        "row_count": int(row_count),
        "preview_rows": preview_df.fillna("").to_dict(orient="records"),
        "truncated": row_count > 500,
        "data_quality": {
            "empty_rows_removed": True,
            "column_count": len(df.columns)
        }
    }


# ---------------- INPUT SCHEMA ----------------
class FileExtractorInput(BaseModel):
    file_path: str = Field(..., description="Absolute path to file")


# ---------------- MAIN TOOL ----------------
class FileExtractorTool(BaseTool):
    name: str = "extract_data_from_file"
    description: str = "Extract structured data from PDF, CSV, Excel, JSON, TXT, MD files"
    args_schema: Type[BaseModel] = FileExtractorInput

    def _run(self, file_path: str) -> str:
        
        if not file_path or not os.path.exists(file_path):
            return json.dumps({"error": f"File not found: {file_path}"})

        ext = os.path.splitext(file_path)[1].lower()

        try:
            # ---------------- TEXT ----------------
            if ext in [".txt", ".md"]:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()

                return json.dumps({
                    "file_type": ext,
                    "text_length": len(text),
                    "text_preview": text[:15000]
                }, indent=2)

            # ---------------- JSON ----------------
            if ext == ".json":
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)

                return json.dumps({
                    "file_type": ext,
                    "keys": list(data.keys()) if isinstance(data, dict) else "list",
                    "preview": str(data)[:15000]
                }, indent=2)

            # ---------------- CSV ----------------
            if ext == ".csv":
                df = None

                for enc in ["utf-8", "latin-1", "cp1252", "utf-16"]:
                    try:
                        df = pd.read_csv(file_path, encoding=enc)
                        break
                    except Exception:
                        continue

                if df is None:
                    return json.dumps({"error": "CSV decoding failed"})

                return json.dumps({
                    "file_type": ext,
                    "structure": _dataframe_to_payload(df, "csv"),
                    "extraction_quality": "good"
                }, indent=2)

            # ---------------- EXCEL ----------------
            if ext in [".xlsx", ".xls"]:
                sheets = pd.read_excel(file_path, sheet_name=None)

                payload = {}
                for name, df in sheets.items():
                    payload[name] = _dataframe_to_payload(df, name)

                return json.dumps({
                    "file_type": ext,
                    "sheet_count": len(payload),
                    "sheets": payload,
                    "extraction_quality": "good"
                }, indent=2)

            # ---------------- PDF ----------------
            if ext == ".pdf":
                doc = fitz.open(file_path)

                text_chunks = []
                for page in doc:
                    text_chunks.append(page.get_text())

                text = "\n".join(text_chunks).strip()

                # Print log to check whether any data is being extracted from pdf
                logger.info(f"[PDF] Extracted text length: {len(text)}")

                ocr_info = {
                    "ocr_used": False,
                    "ocr_engine": None
                }

                # Trigger OCR if weak text
                if len(text.strip()) < 100 or not any(c.isalnum() for c in text):

                    logger.info("[PDF] Triggering OCR fallback...")
                    ocr_res = _ocr_fallback(file_path)

                    if ocr_res.get("ocr_used"):
                        text = ocr_res["ocr_text"]
                        ocr_info = {
                            "ocr_used": True,
                            "ocr_engine": ocr_res.get("ocr_engine")
                        }

                logger.info(f"[OCR STATUS] Used: {ocr_info['ocr_used']} | Engine: {ocr_info['ocr_engine']}")

                return json.dumps({
                    "file_type": ext,
                    "text_length": len(text),
                    "text_preview": text[:15000],
                    "extraction_quality": "strong" if text else "weak",
                    "ocr_metadata": ocr_info
                }, indent=2)

            return json.dumps({"error": f"Unsupported file type: {ext}"})

        except Exception as e:
            return json.dumps({"error": str(e)})
