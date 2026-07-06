"""
NEXUS AI v4.0 — Tool 17: Image processing via PIL/Pillow.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Processes images: resize, crop, convert format, apply filters, OCR,
and extract metadata. Uses Pillow (PIL) with pytesseract OCR fallback.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("nexus.tool.image_processor")

# ─── Constants ────────────────────────────────────────────────────────────────
MAX_IMAGE_SIZE_MB: int = 50
SUPPORTED_FORMATS: frozenset = frozenset({"PNG", "JPEG", "JPG", "GIF", "BMP", "TIFF", "WEBP", "ICO"})


def image_processor(
    action: str,
    path: str,
    output_path: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    format: Optional[str] = None,
    quality: int = 85,
    filter_name: Optional[str] = None,
    text: Optional[str] = None,
    position: Optional[List[int]] = None,
) -> str:
    """
    Process images: resize, crop, convert, filter, OCR, and annotate.
    
    Use this tool when: The user asks to edit an image, resize a photo,
    convert image format, extract text from an image (OCR), or apply filters.
    
    Args:
        action: One of: "resize", "crop", "convert", "info", "ocr",
                "grayscale", "thumbnail", "rotate", "flip", "filter",
                "add_text", "compress"
        path: Path to the input image.
        output_path: Path for the output image (required for most actions).
        width: Target width (for "resize", "thumbnail").
        height: Target height (for "resize", "thumbnail").
        format: Target format for "convert" (e.g., "PNG", "JPEG", "WEBP").
        quality: Output quality for JPEG/WEBP (1-100).
        filter_name: Filter name for "filter" action: "blur", "contour",
                    "detail", "edge_enhance", "emboss", "sharpen", "smooth".
        text: Text to add to image (for "add_text" action).
        position: [x, y] position for text placement.
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the operation succeeded.
          - result (any): Result info or extracted text.
          - error (str or null): Error message if failed.
    """
    start = time.perf_counter()
    
    try:
        from PIL import Image, ImageFilter, ImageDraw, ImageFont, ImageEnhance
        
        img_path = Path(path)
        if not img_path.exists():
            return json.dumps({"success": False, "result": None, "error": f"Image not found: {path}"})
        
        file_size_mb = img_path.stat().st_size / (1024 * 1024)
        if file_size_mb > MAX_IMAGE_SIZE_MB:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Image too large: {file_size_mb:.1f}MB (max {MAX_IMAGE_SIZE_MB}MB)"
            })
        
        img = Image.open(img_path)
        
        if action == "info":
            info = {
                "format": img.format,
                "mode": img.mode,
                "width": img.width,
                "height": img.height,
                "size_bytes": img_path.stat().st_size,
                "size_mb": round(file_size_mb, 2),
                "aspect_ratio": round(img.width / img.height, 3) if img.height > 0 else 0,
                "is_animated": getattr(img, "is_animated", False),
                "frames": getattr(img, "n_frames", 1),
            }
            img.close()
            return json.dumps({"success": True, "result": info, "error": None})
        
        elif action == "resize":
            if not output_path or not width or not height:
                return json.dumps({"success": False, "result": None, "error": "output_path, width, and height required"})
            resized = img.resize((width, height), Image.LANCZOS)
            resized.save(output_path, quality=quality)
            img.close()
            return json.dumps({"success": True, "result": f"Resized to {width}x{height}", "error": None, "metadata": {"output": output_path}})
        
        elif action == "thumbnail":
            if not output_path or not width or not height:
                return json.dumps({"success": False, "result": None, "error": "output_path, width, and height required"})
            img.thumbnail((width, height), Image.LANCZOS)
            img.save(output_path, quality=quality)
            img.close()
            return json.dumps({"success": True, "result": f"Thumbnail created: {img.width}x{img.height}", "error": None, "metadata": {"output": output_path}})
        
        elif action == "crop":
            if not output_path or not width or not height:
                return json.dumps({"success": False, "result": None, "error": "output_path, width, height required"})
            pos = position or [0, 0]
            cropped = img.crop((pos[0], pos[1], pos[0] + width, pos[1] + height))
            cropped.save(output_path, quality=quality)
            img.close()
            return json.dumps({"success": True, "result": f"Cropped to {width}x{height} at ({pos[0]}, {pos[1]})", "error": None})
        
        elif action == "convert":
            if not output_path:
                return json.dumps({"success": False, "result": None, "error": "output_path required"})
            fmt = format or Path(output_path).suffix[1:].upper()
            if img.mode == "RGBA" and fmt in ("JPEG", "JPG"):
                img = img.convert("RGB")
            img.save(output_path, format=fmt, quality=quality)
            img.close()
            return json.dumps({"success": True, "result": f"Converted to {fmt}", "error": None, "metadata": {"output": output_path, "format": fmt}})
        
        elif action == "grayscale":
            if not output_path:
                return json.dumps({"success": False, "result": None, "error": "output_path required"})
            gray = img.convert("L")
            gray.save(output_path, quality=quality)
            img.close()
            return json.dumps({"success": True, "result": "Converted to grayscale", "error": None})
        
        elif action == "rotate":
            if not output_path or width is None:
                return json.dumps({"success": False, "result": None, "error": "output_path and degrees (width param) required"})
            rotated = img.rotate(width, expand=True, fillcolor=(255, 255, 255))
            rotated.save(output_path, quality=quality)
            img.close()
            return json.dumps({"success": True, "result": f"Rotated {width} degrees", "error": None})
        
        elif action == "flip":
            if not output_path:
                return json.dumps({"success": False, "result": None, "error": "output_path required"})
            flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
            flipped.save(output_path, quality=quality)
            img.close()
            return json.dumps({"success": True, "result": "Flipped horizontally", "error": None})
        
        elif action == "filter":
            if not output_path or not filter_name:
                return json.dumps({"success": False, "result": None, "error": "output_path and filter_name required"})
            filters = {
                "blur": ImageFilter.BLUR,
                "contour": ImageFilter.CONTOUR,
                "detail": ImageFilter.DETAIL,
                "edge_enhance": ImageFilter.EDGE_ENHANCE,
                "emboss": ImageFilter.EMBOSS,
                "sharpen": ImageFilter.SHARPEN,
                "smooth": ImageFilter.SMOOTH,
            }
            if filter_name not in filters:
                return json.dumps({"success": False, "result": None, "error": f"Unknown filter: {filter_name}. Options: {', '.join(filters.keys())}"})
            filtered = img.filter(filters[filter_name])
            filtered.save(output_path, quality=quality)
            img.close()
            return json.dumps({"success": True, "result": f"Applied filter: {filter_name}", "error": None})
        
        elif action == "ocr":
            try:
                import pytesseract
                text = pytesseract.image_to_string(img)
                img.close()
                return json.dumps({"success": True, "result": text.strip(), "error": None, "metadata": {"method": "pytesseract"}})
            except ImportError:
                return json.dumps({"success": False, "result": None, "error": "pytesseract not installed. Install with: pip install pytesseract"})
        
        elif action == "add_text":
            if not output_path or not text:
                return json.dumps({"success": False, "result": None, "error": "output_path and text required"})
            draw = ImageDraw.Draw(img)
            pos = position or [10, 10]
            draw.text(tuple(pos), text, fill=(255, 255, 255))
            img.save(output_path, quality=quality)
            img.close()
            return json.dumps({"success": True, "result": f"Added text: {text[:50]}", "error": None})
        
        elif action == "compress":
            if not output_path:
                return json.dumps({"success": False, "result": None, "error": "output_path required"})
            img.save(output_path, quality=quality, optimize=True)
            img.close()
            new_size = Path(output_path).stat().st_size
            return json.dumps({
                "success": True,
                "result": f"Compressed: {file_size_mb:.2f}MB → {new_size / (1024*1024):.2f}MB",
                "error": None,
                "metadata": {"original_bytes": img_path.stat().st_size, "new_bytes": new_size, "quality": quality}
            })
        
        else:
            img.close()
            return json.dumps({
                "success": False, "result": None,
                "error": f"Unknown action: '{action}'. Valid: resize, crop, convert, info, ocr, grayscale, thumbnail, rotate, flip, filter, add_text, compress"
            })
    
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "Pillow not installed. Install with: pip install Pillow"
        })
    except Exception as e:
        logger.error(f"image_processor error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })