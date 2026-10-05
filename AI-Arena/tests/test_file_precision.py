"""Unit tests for File & Document Precision rendering in InputNormalizer."""

import pytest
from core.ingestion.extractors import STATUS_OK, STATUS_PARTIAL, STATUS_EMPTY, STATUS_FAILED
from core.ingestion.normalizer import InputNormalizer


def test_render_attachment_block_status_ok_no_warning():
    attachments = [
        {
            "file_id": "file_101",
            "filename": "clean_invoice.pdf",
            "kind": "document",
            "extraction_engine": "pymupdf",
            "extraction_status": STATUS_OK,
            "text": "Invoice #12345 Total: $500.00",
            "text_chars": 29,
            "truncated": False,
        }
    ]
    rendered = InputNormalizer.render_attachment_block(attachments)
    
    assert "--- BEGIN FILE: clean_invoice.pdf (id=file_101, kind=document, engine=pymupdf) ---" in rendered
    assert "DEGRADED/PARTIAL EXTRACTION" not in rendered
    assert "TRUNCATED" not in rendered
    assert "Invoice #12345 Total: $500.00" in rendered


def test_render_attachment_block_status_partial_shows_degraded_warning():
    attachments = [
        {
            "file_id": "file_102",
            "filename": "scanned_invoice.pdf",
            "kind": "document",
            "extraction_engine": "ocr:tesseract",
            "extraction_status": STATUS_PARTIAL,
            "text": "Invoice #12345 Total: $500.00 (OCR degraded)",
            "text_chars": 44,
            "truncated": False,
        }
    ]
    rendered = InputNormalizer.render_attachment_block(attachments)
    
    assert "DEGRADED/PARTIAL EXTRACTION - verify critical numbers, dates and names against original file" in rendered
    assert "TRUNCATED" not in rendered
    assert "Invoice #12345 Total: $500.00 (OCR degraded)" in rendered


def test_render_attachment_block_truncated_preserves_truncated_warning():
    attachments = [
        {
            "file_id": "file_103",
            "filename": "long_doc.txt",
            "kind": "text",
            "extraction_engine": "decode:utf-8",
            "extraction_status": STATUS_OK,
            "text": "Long document body text...",
            "text_chars": 1000,
            "truncated": True,
        }
    ]
    rendered = InputNormalizer.render_attachment_block(attachments)
    
    assert "TRUNCATED" in rendered
    assert "DEGRADED/PARTIAL EXTRACTION" not in rendered
    assert "Long document body text..." in rendered


def test_render_attachment_block_partial_and_truncated_shows_both_warnings():
    attachments = [
        {
            "file_id": "file_104",
            "filename": "large_scanned_contract.pdf",
            "kind": "document",
            "extraction_engine": "ocr:tesseract",
            "extraction_status": STATUS_PARTIAL,
            "text": "Contract clause text snippet...",
            "text_chars": 50000,
            "truncated": True,
        }
    ]
    rendered = InputNormalizer.render_attachment_block(attachments)
    
    assert "TRUNCATED" in rendered
    assert "DEGRADED/PARTIAL EXTRACTION - verify critical numbers, dates and names against original file" in rendered
    assert "Contract clause text snippet..." in rendered


def test_render_attachment_block_content_unmodified():
    raw_content = "EXACT_CONTENT_LINE_1\nEXACT_CONTENT_LINE_2"
    attachments = [
        {
            "file_id": "file_105",
            "filename": "data.txt",
            "kind": "text",
            "extraction_engine": "decode:utf-8",
            "extraction_status": STATUS_PARTIAL,
            "text": raw_content,
            "text_chars": len(raw_content),
            "truncated": False,
        }
    ]
    rendered = InputNormalizer.render_attachment_block(attachments)
    
    assert raw_content in rendered
