"""Thin Ollama client.

Every call is wrapped so a stopped or slow Ollama degrades the feature instead
of breaking the platform: callers get None and fall back to the deterministic
path. A citizen must never be unable to file a complaint because a local model
is not running.
"""

import json
import logging

import httpx

from . import config

logger = logging.getLogger("moct.ai")


class OllamaUnavailable(RuntimeError):
    """Raised only by health checks; the normal paths return None instead."""


def _post(path: str, payload: dict, timeout: float) -> dict | None:
    try:
        response = httpx.post(f"{config.OLLAMA_URL}{path}", json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.TimeoutException:
        logger.warning("ollama timeout on %s after %ss", path, timeout)
    except httpx.HTTPError as error:
        logger.warning("ollama error on %s: %s", path, error)
    except ValueError as error:  # malformed JSON body
        logger.warning("ollama returned malformed JSON on %s: %s", path, error)
    return None


def available() -> bool:
    """Whether Ollama answers and carries both models we depend on."""
    if not config.AI_ENABLED:
        return False
    try:
        response = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        names = {m.get("name", "") for m in response.json().get("models", [])}
    except (httpx.HTTPError, ValueError):
        return False

    # Ollama reports "gemma3:4b"; a bare "gemma3" in config should still match.
    def present(wanted: str) -> bool:
        return any(n == wanted or n.split(":")[0] == wanted.split(":")[0] for n in names)

    return present(config.LLM_MODEL) and present(config.EMBED_MODEL)


def embed(texts: list[str], *, is_query: bool = False) -> list[list[float]] | None:
    """Embed one or more strings, or None if the model is unreachable.

    nomic-embed-text distinguishes queries from documents by prefix, so the
    caller has to say which side of the comparison it is on.
    """
    if not texts:
        return []
    prefix = config.EMBED_QUERY_PREFIX if is_query else config.EMBED_DOCUMENT_PREFIX
    body = _post(
        "/api/embed",
        {"model": config.EMBED_MODEL, "input": [prefix + t for t in texts]},
        config.EMBED_TIMEOUT_SECONDS,
    )
    if not body or "embeddings" not in body:
        return None
    return body["embeddings"]


def generate(
    prompt: str,
    *,
    system: str | None = None,
    as_json: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 600,
) -> str | None:
    """Run a single-turn completion. Returns None when the model is unreachable."""
    payload: dict = {
        "model": config.LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if system:
        payload["system"] = system
    if as_json:
        # Constrained decoding: the model cannot emit anything but valid JSON,
        # which removes a whole class of parsing failures.
        payload["format"] = "json"

    body = _post("/api/generate", payload, config.LLM_TIMEOUT_SECONDS)
    if not body:
        return None
    return (body.get("response") or "").strip()


def generate_json(prompt: str, *, system: str | None = None, **kwargs) -> dict | None:
    """generate() plus a parse, returning None if either step fails."""
    raw = generate(prompt, system=system, as_json=True, **kwargs)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("model did not return parseable JSON: %.200s", raw)
        return None
    return parsed if isinstance(parsed, dict) else None
