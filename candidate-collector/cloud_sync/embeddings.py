"""Text embeddings for semantic memory search.

MySQL 8.0 has no native vector type, so embeddings are stored as a JSON array
of floats in ``memories.embedding`` and cosine similarity is computed in
Python. This is fast enough for thousands of memories and keeps the deployment
dependency-free (no external vector store).

Two backends are supported:

* ``local``  (default) — fastembed ONNX model running fully offline. No API
  key required, which also makes it work identically on every machine. Uses a
  Chinese-optimized BGE model by default.
* ``openai`` — an OpenAI-compatible ``/embeddings`` HTTP endpoint, used when a
  working API key is available.

Configuration (environment variables):
    EMBEDDING_BACKEND       "local" (default) | "openai" | "auto".
    EMBEDDING_LOCAL_MODEL   fastembed model name. Default BAAI/bge-small-zh-v1.5
    EMBEDDING_API_KEY       API key for the openai backend (falls back to
                            OPENAI_NEXT_API_KEY / OPENAI_API_KEY).
    EMBEDDING_BASE_URL      Base URL for the openai backend.
    EMBEDDING_MODEL         Model name for the openai backend.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "auto").strip().lower()
EMBEDDING_LOCAL_MODEL = os.getenv("EMBEDDING_LOCAL_MODEL", "BAAI/bge-small-zh-v1.5").strip()

# openai backend config
_EMB_API_KEY = _first_env("EMBEDDING_API_KEY", "OPENAI_NEXT_API_KEY", "OPENAI_API_KEY")
_EMB_BASE_URL = _first_env("EMBEDDING_BASE_URL", "OPENAI_NEXT_BASE_URL") or "https://api.openai-next.com/v1"
_EMB_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small").strip()

_MAX_CHARS = 6000

# Lazily-initialised fastembed model (module-level singleton).
_local_model = None


def _openai_available() -> bool:
    return bool(httpx is not None and _EMB_API_KEY and _EMB_BASE_URL and _EMB_MODEL)


def _local_available() -> bool:
    try:
        import fastembed  # noqa: F401

        return True
    except ImportError:
        return False


def active_backend() -> str:
    """Resolve which backend to use: 'local', 'openai', or 'none'."""
    if EMBEDDING_BACKEND == "local":
        return "local" if _local_available() else "none"
    if EMBEDDING_BACKEND == "openai":
        return "openai" if _openai_available() else "none"
    # auto: prefer a working local model (no key, deterministic); fall back to openai.
    if _local_available():
        return "local"
    if _openai_available():
        return "openai"
    return "none"


def embeddings_configured() -> bool:
    """Return True when some embedding backend is usable."""
    return active_backend() != "none"


def embedding_model_name() -> str:
    """Return the model name for the active backend (for stamping rows)."""
    backend = active_backend()
    if backend == "local":
        return EMBEDDING_LOCAL_MODEL
    if backend == "openai":
        return _EMB_MODEL
    return ""


# Backwards-compatible attribute used by older call sites.
EMBEDDING_MODEL = EMBEDDING_LOCAL_MODEL if _local_available() else _EMB_MODEL


def _get_local_model():
    global _local_model
    if _local_model is None:
        from fastembed import TextEmbedding

        _local_model = TextEmbedding(model_name=EMBEDDING_LOCAL_MODEL)
    return _local_model


def _embed_local(texts: list[str]) -> list[list[float]]:
    model = _get_local_model()
    trimmed = [(t or "")[:_MAX_CHARS] for t in texts]
    vectors = list(model.embed(trimmed))
    return [[float(x) for x in v] for v in vectors]


def _embed_openai(texts: list[str], *, timeout: float = 60.0) -> list[list[float]]:
    if not _openai_available():
        raise RuntimeError("OpenAI embedding backend not configured.")
    payload = {
        "model": _EMB_MODEL,
        "input": [(t or "")[:_MAX_CHARS] for t in texts],
    }
    url = _EMB_BASE_URL.rstrip("/") + "/embeddings"
    headers = {
        "Authorization": f"Bearer {_EM_API_KEY}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
    vectors = [list(map(float, item["embedding"])) for item in items]
    if len(vectors) != len(texts):
        raise RuntimeError(f"Embedding count mismatch: got {len(vectors)}, want {len(texts)}")
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts with the active backend."""
    if not texts:
        return []
    backend = active_backend()
    if backend == "local":
        return _embed_local(texts)
    if backend == "openai":
        return _embed_openai(texts)
    raise RuntimeError(
        "No embedding backend available. Install fastembed (local) or set "
        "EMBEDDING_API_KEY (openai)."
    )


def embed_text(text: str) -> list[float]:
    """Embed a single text."""
    return embed_texts([text])[0]


def serialize_embedding(vector: list[float]) -> str:
    """Serialize a vector to a compact JSON string for the JSON column."""
    return json.dumps(vector)


def parse_embedding(raw: Any) -> list[float]:
    """Parse an embedding from the DB (JSON may arrive as str or list)."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [float(x) for x in raw]
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            return [float(x) for x in json.loads(raw)]
        except (ValueError, TypeError):
            return []
    return []


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors. Returns 0.0 on mismatch."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
