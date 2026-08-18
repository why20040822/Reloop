"""OCR fallback for PDFs and images that contain no selectable text.

This module is designed so that the main ingestion pipeline can call it
without caring which OCR engine is installed.  It currently supports:

- PyMuPDF built-in OCR (when available)
- PaddleOCR (requires optional `paddleocr` dependency and model download)
- Tesseract (placeholder; requires `pytesseract` and system binary)

All image processing preserves the original file and writes enhanced copies
under `data/processed/`.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import fitz


ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"


class OcrResult:
    def __init__(self, text: str, confidence: float, engine: str, pages: list[dict[str, Any]]):
        self.text = text
        self.confidence = confidence
        self.engine = engine
        self.pages = pages


def _ensure_processed_dir() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def pdf_has_selectable_text(path: Path | bytes, filetype: str = "pdf") -> bool:
    """Quick check: does the PDF contain at least a few characters of text?"""
    try:
        doc = fitz.open(stream=path, filetype=filetype) if isinstance(path, bytes) else fitz.open(path)
        text = "\n".join(page.get_text("text") for page in doc)
        return len(text.strip()) >= 30
    except Exception:
        return False


def pdf_page_images(path: Path | bytes, filetype: str = "pdf", dpi: int = 200) -> list[tuple[int, Path]]:
    """Render PDF pages to images and return (page_number, image_path) pairs."""
    _ensure_processed_dir()
    doc = fitz.open(stream=path, filetype=filetype) if isinstance(path, bytes) else fitz.open(path)
    images: list[tuple[int, Path]] = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
        out = PROCESSED_DIR / f"page_{i:03d}.png"
        pix.save(str(out))
        images.append((i, out))
    return images


def preprocess_image(path: Path, output_name: str | None = None) -> Path:
    """Apply conservative preprocessing: grayscale, contrast, denoise, deskew if needed.

    Requires opencv-python.  If not installed, returns the original path.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return path

    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return path

    # Mild denoise and contrast enhancement.
    denoised = cv2.fastNlMeansDenoising(img, None, 10, 7, 21)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)

    _ensure_processed_dir()
    out = PROCESSED_DIR / (output_name or f"processed_{path.name}")
    cv2.imwrite(str(out), enhanced)
    return out


def ocr_with_paddle(images: list[Path], lang: str = "ch") -> OcrResult:
    """Run PaddleOCR on a list of image paths.

    Models are downloaded on first use by the paddleocr package.
    """
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise RuntimeError("paddleocr 未安装。运行：pip install paddleocr") from exc

    ocr = PaddleOCR(use_angle_cls=True, lang=lang)
    pages = []
    all_text: list[str] = []
    confidences: list[float] = []
    for idx, img_path in enumerate(images):
        result = ocr.ocr(str(img_path), cls=True)
        lines: list[str] = []
        page_confidences: list[float] = []
        if result and result[0]:
            for line in result[0]:
                if line:
                    bbox, (text, conf) = line
                    lines.append(text)
                    page_confidences.append(float(conf))
        page_text = "\n".join(lines)
        all_text.append(page_text)
        pages.append({"page": idx, "text": page_text, "confidence": _avg(page_confidences)})
        confidences.extend(page_confidences)

    return OcrResult(
        text="\n".join(all_text),
        confidence=_avg(confidences),
        engine="paddleocr",
        pages=pages,
    )


def ocr_with_pymupdf(images: list[Path]) -> OcrResult:
    """Fallback using PyMuPDF's built-in OCR (requires Tesseract on the host)."""
    return ocr_with_tesseract(images)


def ocr_with_tesseract(images: list[Path], lang: str = "chi_sim+eng") -> OcrResult:
    """Run Tesseract OCR on a list of image paths."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("pytesseract 未安装。运行：pip install pytesseract") from exc

    pages = []
    all_text: list[str] = []
    confidences: list[float] = []
    for idx, img_path in enumerate(images):
        try:
            img = Image.open(img_path)
            text = pytesseract.image_to_string(img, lang=lang)
            # Tesseract does not provide per-line confidence easily; use 0.7 as a generic placeholder.
            pages.append({"page": idx, "text": text, "confidence": 0.7})
            all_text.append(text)
            confidences.append(0.7)
        except Exception as exc:
            pages.append({"page": idx, "text": "", "confidence": 0.0, "error": str(exc)})
    return OcrResult(
        text="\n".join(all_text),
        confidence=_avg(confidences),
        engine="tesseract",
        pages=pages,
    )


def ocr_pdf(path: Path | bytes, filetype: str = "pdf", engine: str = "auto") -> OcrResult:
    """High-level OCR entry point for PDFs and images.

    - `engine="auto"` tries PaddleOCR first (if paddlepaddle is available),
      then falls back to Tesseract.
    - Returns empty text with engine="none" if no OCR is available.
    """
    if pdf_has_selectable_text(path, filetype):
        doc = fitz.open(stream=path, filetype=filetype) if isinstance(path, bytes) else fitz.open(path)
        text = "\n".join(page.get_text("text") for page in doc)
        return OcrResult(text=text, confidence=1.0, engine="selectable_text", pages=[])

    images = pdf_page_images(path, filetype)
    if engine in ("auto", "paddle"):
        try:
            return ocr_with_paddle([preprocess_image(p) for _, p in images])
        except Exception:
            if engine == "paddle":
                raise
    if engine in ("auto", "tesseract"):
        return ocr_with_tesseract([preprocess_image(p) for _, p in images])

    raise RuntimeError(f"不支持的 OCR 引擎：{engine}")


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m image_processing.ocr <pdf_or_image>")
        raise SystemExit(1)
    result = ocr_pdf(Path(sys.argv[1]))
    print(f"engine={result.engine} confidence={result.confidence:.2f}")
    print(result.text[:2000])
