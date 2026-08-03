"""Cross-package adapter for the shared LLM client.

The canonical client lives under ``ttc-automation/daemon/llm_client.py``. Python
packages cannot contain hyphens, so this module loads that file directly via
``importlib.util`` and re-exports the functions we need.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from reloop.config import REPOSITORY_ROOT

_MODULE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = REPOSITORY_ROOT
_CLIENT_FILE = _REPO_ROOT / "ttc-automation" / "daemon" / "llm_client.py"


def _load_client_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_shared_llm_client", _CLIENT_FILE)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load shared LLM client from {_CLIENT_FILE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_client_module = _load_client_module()


def _export(name: str) -> Any:
    return getattr(_client_module, name)


chat_completion = _export("chat_completion")
complete = _export("complete")
image_to_data_url = _export("image_to_data_url")
parse_json_safe = _export("parse_json_safe")


def complete_with_image(
    prompt: str,
    image_path: str | Path,
    model: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.3,
) -> str | None:
    """Use the shared vision helper when available, otherwise fall back cleanly.

    Older shared clients predate the vision helper.  Importing Reloop must not
    fail in that environment; the parser already treats a ``None`` response as
    an unavailable optional OCR/LLM enhancement.
    """

    helper = getattr(_client_module, "complete_with_image", None)
    if helper is None:
        return None
    return helper(
        prompt,
        image_path,
        model=model,
        json_mode=json_mode,
        temperature=temperature,
    )

__all__ = [
    "chat_completion",
    "complete",
    "complete_with_image",
    "image_to_data_url",
    "parse_json_safe",
]
