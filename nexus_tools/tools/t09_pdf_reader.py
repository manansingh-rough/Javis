"""
NEXUS AI v4.0 — Tool 09: PDF text extraction with OCR fallback.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Extracts text from PDF files using PyMuPDF (fitz) with pytesseract
OCR fallback for scanned documents.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nexus.tool.pdf_reader")

# ─── Constants ────────────────────────────────────────────────────────────────
MAX_PDF_SIZE_MB: int = 100
MAX_PAGES: int = 100


def pdf_reader(
    path: str,
    page_start: int = 0,
    page_end: Optional[int] = None,
    use_ocr: bool = False,
) -> str:
    """
    Extract text content from PDF files.
    
    Use this tool when: The user asks to read a PDF file, extract text from a PDF,
    analyze a PDF document, or search within a PDF.
    
    Args:
        path: Path to the PDF file.
        page_start: First page to extract (0-indexed). Default 0.
        page_end: Last page to extract (exclusive). If None, extracts to end.
        use_ocr: Whether to use OCR for scanned PDFs (requires pytesseract).
                 Slower but works on image-based PDFs.
    
    Returns:
        JSON string with keys:
          - success (bool): Whether extraction succeeded.
          - result (str): Extracted text content.
          - error (str or null): Error message if failed.
          - metadata (dict): Page count, extraction method, etc.
    
    Examples:
        >>> pdf_reader("document.pdf")
        >>> pdf_reader("scanned.pdf", use_ocr=True)
        >>> pdf_reader("large.pdf", page_start=5, page_end=10)
    """
    start = time.perf_counter()
    
    try:
        pdf_path = Path(path)
        if not pdf_path.exists():
            return json.dumps({"success": False, "result": None, "error": f"PDF not found: {path}"})
        
        file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
        if file_size_mb > MAX_PDF_SIZE_MB:
            return json.dumps({
                "success": False, "result": None,
                "error": f"PDF too large: {file_size_mb:.1f}MB (max {MAX_PDF_SIZE_MB}MB)"
            })
        
        if use_ocr:
            return _extract_with_ocr(pdf_path, page_start, page_end)
        else:
            return _extract_with_pymupdf(pdf_path, page_start, page_end)
    
    except Exception as e:
        logger.error(f"pdf_reader error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })


def _extract_with_pymupdf(pdf_path: Path, page_start: int, page_end: Optional[int]) -> str:
    """Extract text using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "PyMuPDF not installed. Install with: pip install PyMuPDF"
        })
    
    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    
    if page_end is None or page_end > total_pages:
        page_end = total_pages
    
    page_start = max(0, min(page_start, total_pages - 1))
    page_end = min(page_end, total_pages)
    
    if page_start >= page_end:
        return json.dumps({
            "success": False, "result": None,
            "error": f"Invalid page range: {page_start} to {page_end}. PDF has {total_pages} pages."
        })
    
    pages_to_read = min(page_end - page_start, MAX_PAGES)
    text_parts = []
    
    for i in range(page_start, page_start + pages_to_read):
        page = doc[i]
        text = page.get_text()
        if text.strip():
            text_parts.append(f"--- Page {i + 1} ---\n{text}")
    
    doc.close()
    
    result_text = "\n\n".join(text_parts) if text_parts else "(No text content found)"
    
    return json.dumps({
        "success": True,
        "result": result_text,
        "error": None,
        "metadata": {
            "total_pages": total_pages,
            "extracted_pages": pages_to_read,
            "page_range": f"{page_start + 1}-{page_start + pages_to_read}",
            "method": "pymupdf",
            "file": str(pdf_path),
        }
    })


def _extract_with_ocr(pdf_path: Path, page_start: int, page_end: Optional[int]) -> str:
    """Extract text using OCR (pytesseract + PIL)."""
    try:
        import fitz
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "PyMuPDF not installed. Install with: pip install PyMuPDF"
        })
    
    try:
        import pytesseract
        from PIL import Image
        import io
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "pytesseract not installed. Install with: pip install pytesseract"
        })
    
    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    
    if page_end is None or page_end > total_pages:
        page_end = total_pages
    
    page_start = max(0, min(page_start, total_pages - 1))
    page_end = min(page_end, total_pages)
    pages_to_read = min(page_end - page_start, MAX_PAGES)
    
    text_parts = []
    
    for i in range(page_start, page_start + pages_to_read):
        page = doc[i]
        # Render page to image
        pix = page.get_pixmap(dpi=200)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        
        # OCR the image
        text = pytesseract.image_to_string(img)
        if text.strip():
            text_parts.append(f"--- Page {i + 1} (OCR) ---\n{text}")
    
    doc.close()
    
    result_text = "\n\n".join(text_parts) if text_parts else "(No text found via OCR)"
    
    return json.dumps({
        "success": True,
        "result": result_text,
        "error": None,
        "metadata": {
            "total_pages": total_pages,
            "extracted_pages": pages_to_read,
            "page_range": f"{page_start + 1}-{page_start + pages_to_read}",
            "method": "ocr",
            "file": str(pdf_path),
        }
    })