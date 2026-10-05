import os
import logging
from typing import Optional, Any
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential

logger = logging.getLogger(__name__)

class InvoiceFinanceService:
    def __init__(self):
        self.endpoint = os.getenv("AZURE_DOCUMENT_ENDPOINT")
        self.key = os.getenv("AZURE_DOCUMENT_API_KEY")

        if not self.endpoint or not self.key:
            logger.error("Azure Document Intelligence credentials missing")
            raise ValueError("Azure Document Intelligence credentials are not configured in .env")

        self.client = DocumentAnalysisClient(
            endpoint=self.endpoint, 
            credential=AzureKeyCredential(self.key)
        )

    async def analyze_document(self, file_data: bytes):
        """Analyze document using Azure Document Intelligence (Prebuilt-document)."""
        try:
            # Limit to first 2 pages
            poller = self.client.begin_analyze_document("prebuilt-document", document=file_data, pages="1-2")
            result = poller.result()

            # Helper to format polygon points
            def format_polygon(polygon):
                return [{"x": p.x, "y": p.y} for p in polygon]

            data = {
                "content": result.content,
                "pages_info": [
                    {
                        "page_number": p.page_number,
                        "width": p.width,
                        "height": p.height,
                        "unit": p.unit
                    } for p in result.pages
                ],
                "key_value_pairs": [],
                "tables": []
            }

            # ── Table Extraction ──────────────────────────────────────────
            for table in result.tables:
                table_data = {
                    "row_count": table.row_count,
                    "column_count": table.column_count,
                    "cells": []
                }
                for cell in table.cells:
                    table_data["cells"].append({
                        "row_index": cell.row_index,
                        "column_index": cell.column_index,
                        "content": cell.content,
                        "bounding_regions": [
                            {
                                "page_number": br.page_number,
                                "polygon": format_polygon(br.polygon)
                            }
                            for br in (cell.bounding_regions or [])
                        ]
                    })
                data["tables"].append(table_data)

            # ── KV Pairs Extraction ───────────────────────────────────────
            for kv in result.key_value_pairs:
                pair = {
                    "key": {
                        "content": kv.key.content,
                        "bounding_regions": [
                            {
                                "page_number": br.page_number, 
                                "polygon": format_polygon(br.polygon)
                            } 
                            for br in (kv.key.bounding_regions or [])
                        ]
                    },
                    "value": None
                }

                if kv.value:
                    pair["value"] = {
                        "content": kv.value.content,
                        "bounding_regions": [
                            {
                                "page_number": br.page_number, 
                                "polygon": format_polygon(br.polygon)
                            } 
                            for br in (kv.value.bounding_regions or [])
                        ]
                    }
                
                data["key_value_pairs"].append(pair)

            return data
        except Exception as e:
            logger.error(f"Error in InvoiceFinanceService: {e}", exc_info=True)
            raise e
