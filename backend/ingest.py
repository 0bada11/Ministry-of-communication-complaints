"""Build the vector index from the knowledge base.

Run:  python ingest.py            (upsert; safe to re-run)
      python ingest.py --reset    (drop the collection and rebuild)

Re-run this whenever docs/knowledge-base.md changes — the chatbot answers only
from what is indexed here.
"""

import sys

from app.ai import config, ollama
from app.ai.store import store


def main() -> int:
    print(f"knowledge base : {config.KNOWLEDGE_BASE}")
    print(f"chroma path    : {config.CHROMA_DIR}")
    print(f"embedding model: {config.EMBED_MODEL}")

    if not config.KNOWLEDGE_BASE.exists():
        print(f"\nERROR: {config.KNOWLEDGE_BASE} not found.")
        return 1

    if not ollama.available():
        print(
            f"\nERROR: Ollama is not reachable at {config.OLLAMA_URL}, or it is "
            f"missing {config.LLM_MODEL} / {config.EMBED_MODEL}.\n"
            "Start it with `ollama serve` and pull the models."
        )
        return 1

    count = store.build(reset="--reset" in sys.argv)
    print(f"\nindexed {count} chunks")

    # A smoke query proves the collection is queryable, not merely written.
    hits = store.search("كم تستغرق معالجة الشكوى؟", k=3)
    print("\nsmoke query: كم تستغرق معالجة الشكوى؟")
    for hit in hits:
        print(f"  {hit.score:.4f}  [{hit.metadata.get('lang')}] {hit.metadata.get('title')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
