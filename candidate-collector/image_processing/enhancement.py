"""Low-quality image/scanned document enhancement.

This module exposes conservative preprocessing steps that improve OCR
accuracy without inventing content.  It preserves the original file and
writes each step to `data/processed/` for audit.

Dependencies (optional at runtime):
- opencv-python
- numpy
- Real-ESRGAN (optional; not installed by default because of model size)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"


def _ensure_dir() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def enhance_image(path: Path, output_name: str | None = None) -> dict[str, Any]:
    """Apply a conservative enhancement pipeline and return paths + metadata."""
    _ensure_dir()
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        return {"ok": False, "error": "opencv-python 未安装", "original": str(path)}

    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return {"ok": False, "error": "无法读取图片", "original": str(path)}

    steps = []

    # 1. Denoise
    denoised = cv2.fastNlMeansDenoising(img, None, 10, 7, 21)
    steps.append(("denoise", denoised))

    # 2. Contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrasted = clahe.apply(denoised)
    steps.append(("contrast", contrasted))

    # 3. Adaptive threshold (optional; may help some scans)
    binary = cv2.adaptiveThreshold(contrasted, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 11, 2)
    steps.append(("binary", binary))

    out_name = output_name or f"enhanced_{path.name}"
    result_paths = {}
    for name, arr in steps:
        out = PROCESSED_DIR / f"{name}_{out_name}"
        cv2.imwrite(str(out), arr)
        result_paths[name] = str(out)

    return {
        "ok": True,
        "original": str(path),
        "enhanced": result_paths.get("contrast", str(path)),
        "steps": result_paths,
    }


def upscale_with_realesrgan(path: Path, output_name: str | None = None) -> dict[str, Any]:
    """Optional super-resolution. Requires Real-ESRGAN model download."""
    return {
        "ok": False,
        "error": "Real-ESRGAN 未启用。如需使用，请确认安装模型并重新调用。",
        "original": str(path),
    }
