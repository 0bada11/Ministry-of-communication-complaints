"""Configuration for the local AI features.

Everything is overridable by environment variable so the stack can be pointed
at a different Ollama host or model without touching code.
"""

import os
from pathlib import Path

# Chroma phones home by default and its telemetry client is noisy on this
# version. Off before chromadb is imported anywhere.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
# chromadb 0.6.3 ships a telemetry client whose capture() signature is wrong,
# so every call raises and logs. Silencing the logger is the only fix that
# works from outside the library; the setting alone doesn't stop it.
import logging as _logging
_logging.getLogger("chromadb.telemetry.product.posthog").setLevel(_logging.CRITICAL)
_logging.getLogger("chromadb.telemetry").setLevel(_logging.CRITICAL)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_DIR = BASE_DIR.parent

OLLAMA_URL = os.environ.get("MOCT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")

# gemma3 answers questions and judges priority; nomic-embed-text builds the
# vectors. Splitting the two is deliberate — a chat model's embedding layer is
# a poor substitute for a model trained for retrieval.
LLM_MODEL = os.environ.get("MOCT_LLM_MODEL", "gemma3:4b")
EMBED_MODEL = os.environ.get("MOCT_EMBED_MODEL", "nomic-embed-text")

# nomic-embed-text is trained with task prefixes and loses accuracy without
# them. They are not decoration.
EMBED_QUERY_PREFIX = "search_query: "
EMBED_DOCUMENT_PREFIX = "search_document: "

# Where Chroma persists its collection, and what the knowledge base is.
DATA_DIR = Path(os.environ.get("MOCT_DATA_DIR") or BASE_DIR / "data")
CHROMA_DIR = DATA_DIR / "chroma"
COLLECTION = "moct_knowledge_base"
KNOWLEDGE_BASE = PROJECT_DIR / "docs" / "knowledge-base.md"

# Set MOCT_AI_ENABLED=0 to run the platform with every AI path switched off.
AI_ENABLED = os.environ.get("MOCT_AI_ENABLED", "1") not in ("0", "false", "False")

# Generation is capped so a slow model can never hold a request open forever;
# the caller falls back to the deterministic path instead.
LLM_TIMEOUT_SECONDS = float(os.environ.get("MOCT_LLM_TIMEOUT", "45"))
EMBED_TIMEOUT_SECONDS = float(os.environ.get("MOCT_EMBED_TIMEOUT", "30"))

# Retrieval
TOP_K = int(os.environ.get("MOCT_TOP_K", "5"))
CANDIDATES_PER_RETRIEVER = int(os.environ.get("MOCT_CANDIDATES", "20"))
