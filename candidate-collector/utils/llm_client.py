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

_MODULE_DIR = Path(__file__).resolve().parent
_CANDIDATE_COLLECTOR_DIR = _MODULE_DIR.parent
_REPO_ROOT = _CANDIDATE_COLLECTOR_DIR.parent
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
complete_with_image = _export("complete_with_image")
image_to_data_url = _export("image_to_data_url")
parse_json_safe = _export("parse_json_safe")

__all__ = [
    "chat_completion",
    "complete",
    "complete_with_image",
    "image_to_data_url",
    "parse_json_safe",
]
