"""Thin LLM client wrapper. Supports OpenAI-compatible APIs (Kimi, GPT-4o, etc.).

If no API key is configured, returns None and callers must fall back to heuristics.
"""

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Optional, Union


def _get_client():
    api_key = os.getenv("TTC_LLM_API_KEY")
    base_url = os.getenv("TTC_LLM_BASE_URL")
    if not api_key:
        return None
    try:
        import httpx
        import openai
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        # Vision/image requests can be slow; allow up to 10 minutes for the
        # read, but keep the connect timeout short so unreachable endpoints
        # fail fast instead of hanging 10 minutes.
        kwargs["timeout"] = httpx.Timeout(600.0, connect=5.0)
        return openai.OpenAI(**kwargs)
    except Exception:
        return None


def image_to_data_url(path: Union[str, Path]) -> str:
    """Encode a local image file as a base64 data URL for vision models."""
    path = Path(path)
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def chat_completion(messages: list[dict[str, Any]],
                    model: Optional[str] = None,
                    temperature: float = 0.3,
                    json_mode: bool = False) -> Optional[str]:
    client = _get_client()
    if not client:
        return None
    model = model or os.getenv("TTC_LLM_MODEL", "gpt-4o-mini")
    try:
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content
    except Exception as exc:
        print(f"[LLM] error: {exc}")
        return None


def complete(prompt: str, model: Optional[str] = None, json_mode: bool = False, temperature: float = 0.3) -> Optional[str]:
    return chat_completion(
        messages=[{"role": "system", "content": "You are a helpful assistant."},
                  {"role": "user", "content": prompt}],
        model=model,
        json_mode=json_mode,
        temperature=temperature,
    )


def complete_with_image(
    prompt: str,
    image_path: Union[str, Path],
    model: Optional[str] = None,
    json_mode: bool = False,
    temperature: float = 0.3,
) -> Optional[str]:
    """Send a text prompt together with a local image to a vision-capable model."""
    return chat_completion(
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                    {"type": "text", "text": prompt},
                ],
            },
        ],
        model=model,
        json_mode=json_mode,
        temperature=temperature,
    )


def parse_json_safe(text: Optional[str]) -> Optional[dict[str, Any]]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None
