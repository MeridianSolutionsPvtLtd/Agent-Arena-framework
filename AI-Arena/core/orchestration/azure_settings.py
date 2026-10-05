"""Local Ollama model settings for the Agent Arena runtime."""

from __future__ import annotations

import os
import threading
import httpx
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

_EMBEDDER = None
_EMBEDDER_LOCK = threading.Lock()


def _clean_env(value: Optional[str]) -> str:
    if value is None:
        return ""
    v = str(value).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        v = v[1:-1].strip()
    return v


def get_llm_provider() -> str:
    provider = (_clean_env(os.getenv("LLM_PROVIDER")) or "ollama").lower()
    if provider != "ollama":
        raise ValueError("Only the local Ollama provider is supported")
    return provider


def get_ollama_settings() -> dict:
    """Return bounded local inference settings without cloud fallback."""
    def bounded(name: str, default: int, minimum: int, maximum: int) -> int:
        value = int(os.getenv(name, str(default)))
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return value

    return {
        "model": _clean_env(os.getenv("OLLAMA_MODEL")) or "llama3.1",
        "base_url": (os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/"),
        "num_ctx": bounded("OLLAMA_NUM_CTX", 8192, 1024, 131072),
        "num_predict": bounded("OLLAMA_NUM_PREDICT", 2048, 128, 16384),
        "timeout": bounded("OLLAMA_TIMEOUT_SECONDS", 180, 1, 1800),
    }


def model_completion(*, messages, temperature: float = 0, max_tokens: int = 2048, **kwargs):
    """Call the local Ollama service through one bounded completion boundary."""
    get_llm_provider()
    import httpx
    from types import SimpleNamespace
    cfg = get_ollama_settings()
    response_format = kwargs.pop("response_format", None)
    if kwargs:
        raise ValueError("Unsupported local completion options")
    payload = {
        "model": cfg["model"], "messages": messages, "stream": False,
        "think": False, "keep_alive": "5m",
        "options": {"temperature": temperature, "num_ctx": cfg["num_ctx"],
                    "num_predict": min(max_tokens, cfg["num_predict"])},
    }
    if response_format:
        payload["format"] = (
            response_format["json_schema"]["schema"]
            if response_format.get("type") == "json_schema" else "json"
        )
    try:
        with httpx.Client(timeout=cfg["timeout"], trust_env=False) as client:
            response = client.post(cfg["base_url"] + "/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        raise RuntimeError("Local model request timed out") from None
    except httpx.HTTPStatusError as exc:
        message = "Local model not found; download the selected model" if exc.response.status_code == 404 else "Local model service rejected the request"
        raise RuntimeError(message) from None
    except (httpx.RequestError, ValueError):
        raise RuntimeError("Local model service unavailable or returned invalid data") from None
    if not isinstance(data, dict) or not isinstance(data.get("message"), dict):
        raise RuntimeError("Local model returned invalid data")
    content = data["message"].get("content")
    # Ollama can return useful text together with done_reason=length when the
    # model reaches its prediction budget. Preserve that text for ordinary
    # conversational responses; JSON/planner callers still validate and reject
    # truncated output at their own parsing boundary. Never accept an empty
    # incomplete response because it would hide the real provider failure.
    if (not data.get("done") or data.get("done_reason") == "length") and not isinstance(content, str):
        raise RuntimeError("Local model response incomplete; adjust output limit or simplify request")
    if not isinstance(content, str) or not content.strip():
        if not data.get("done") or data.get("done_reason") == "length":
            raise RuntimeError("Local model response incomplete; adjust output limit or simplify request")
        raise RuntimeError("Local model returned an empty response")
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def ollama_embedding(text: str) -> list[float]:
    """Create a local semantic embedding with a lazily loaded HF model."""
    global _EMBEDDER
    try:
        if _EMBEDDER is None:
            with _EMBEDDER_LOCK:
                if _EMBEDDER is None:
                    from sentence_transformers import SentenceTransformer
                    model_name = _clean_env(os.getenv("HF_EMBED_MODEL")) or "sentence-transformers/all-MiniLM-L6-v2"
                    _EMBEDDER = SentenceTransformer(model_name)
        vector = _EMBEDDER.encode(text[:4000], normalize_embeddings=True)
        return [float(value) for value in vector.tolist()]
    except Exception as exc:
        raise RuntimeError("Hugging Face embedding model unavailable") from exc


def warmup_ollama_models() -> None:
    """Load chat and Hugging Face embedding models once during startup."""
    # A tiny completion loads the configured chat model into Ollama memory.
    model_completion(
        messages=[{"role": "user", "content": "Reply with OK."}],
        max_tokens=4,
        temperature=0,
    )
    ollama_embedding("warmup")


def litellm_completion(
    prompt: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0,
    json_mode: bool = False,
) -> str:
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    response = model_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
        **kwargs,
    )
    content = response.choices[0].message.content
    return (content or "").strip()
