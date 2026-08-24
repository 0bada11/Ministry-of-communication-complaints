"""Hybrid retrieval: dense vectors in Chroma, sparse BM25 in memory, fused.

Both halves are here for a measured reason. On this corpus the embedding model
ranks the *wrong* Arabic chunk above the right one — it reads "these are both
Arabic policy sentences" rather than what they mean. BM25 matching on
normalized Arabic tokens does the real discrimination, and the vectors add
recall for paraphrases that share no words with the document.

Fusion is Reciprocal Rank Fusion rather than a weighted sum of scores, because
RRF consumes *ranks*. Cosine similarities and BM25 scores are on
incomparable scales, and one retriever being badly calibrated — which is
exactly the situation here — would poison a score-based blend.
"""

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass

from ..classifier import normalize
from . import config, ollama
from .chunker import Chunk, chunk_markdown, detect_language

logger = logging.getLogger("moct.ai")

# RRF's damping constant. 60 is the value from the original paper and stops any
# single retriever's top hit from dominating the fusion outright.
RRF_K = 60

# Sparse leads because it is the half that actually discriminates on Arabic.
WEIGHT_SPARSE = 1.0
WEIGHT_DENSE = 0.5

# Chunks written in the language of the question are preferred, but not
# required — a question in Arabic mentioning "MOCT" should still reach the
# English chunk that explains the reference format.
SAME_LANGUAGE_BOOST = 1.25

_TOKEN = re.compile(r"[\w؀-ۿ]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Normalize then split. Shares the classifier's Arabic normalization so a
    query written with different hamza or taa-marbuta forms still matches."""
    return _TOKEN.findall(normalize(text))


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    score: float
    dense_rank: int | None = None
    sparse_rank: int | None = None


class BM25:
    """Okapi BM25 over the chunk corpus.

    Written out rather than pulled in as a dependency because the tokenizer has
    to be the project's Arabic normalizer — swapping that in is most of what a
    BM25 library would have been doing anyway.
    """

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.doc_lengths = [len(doc) for doc in corpus]
        self.avg_length = (sum(self.doc_lengths) / len(corpus)) if corpus else 0.0
        self.frequencies = [Counter(doc) for doc in corpus]

        document_frequency = Counter()
        for doc in corpus:
            document_frequency.update(set(doc))

        total = len(corpus)
        # Smoothed IDF, floored at zero so a term appearing in almost every
        # chunk cannot contribute a negative score.
        self.idf = {
            term: max(0.0, math.log(1 + (total - freq + 0.5) / (freq + 0.5)))
            for term, freq in document_frequency.items()
        }

    def scores(self, query: list[str]) -> list[float]:
        results = [0.0] * len(self.corpus)
        for term in query:
            idf = self.idf.get(term)
            if not idf:
                continue
            for index, frequency in enumerate(self.frequencies):
                count = frequency.get(term, 0)
                if not count:
                    continue
                length_norm = 1 - self.b + self.b * (
                    self.doc_lengths[index] / self.avg_length if self.avg_length else 0
                )
                results[index] += idf * (count * (self.k1 + 1)) / (
                    count + self.k1 * length_norm
                )
        return results


class KnowledgeStore:
    """The knowledge base, indexed twice and queried as one."""

    def __init__(self):
        self._collection = None
        self._chunks: list[Chunk] = []
        self._bm25: BM25 | None = None
        self._loaded = False

    # ---------------------------------------------------------------- build

    def build(self, *, reset: bool = False) -> int:
        """Index the knowledge base. Returns the number of chunks stored."""
        chunks = chunk_markdown(config.KNOWLEDGE_BASE)
        if not chunks:
            raise RuntimeError(f"no chunks parsed from {config.KNOWLEDGE_BASE}")

        vectors = ollama.embed([c.text for c in chunks])
        if vectors is None:
            raise RuntimeError(
                "could not reach the embedding model — is Ollama running?"
            )

        client = self._client()
        if reset:
            try:
                client.delete_collection(config.COLLECTION)
            except Exception:  # nothing to delete on a first run
                pass

        collection = client.get_or_create_collection(
            name=config.COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        collection.upsert(
            ids=[c.id for c in chunks],
            embeddings=vectors,
            documents=[c.text for c in chunks],
            metadatas=[c.metadata for c in chunks],
        )
        self._collection = collection
        self._adopt(chunks)
        return len(chunks)

    # ----------------------------------------------------------------- load

    def _client(self):
        import chromadb  # imported lazily so the API starts without it
        from chromadb.config import Settings

        config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        # Telemetry off explicitly: this Chroma release ignores the
        # environment variable and its telemetry client raises on every call.
        return chromadb.PersistentClient(
            path=str(config.CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )

    def _adopt(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        self._bm25 = BM25([tokenize(c.text) for c in chunks])
        self._loaded = True

    def load(self) -> bool:
        """Attach to the persisted collection and rebuild the BM25 index.

        BM25 is cheap to rebuild and lives in memory, so only the vectors are
        persisted — that also means re-indexing never re-embeds unnecessarily.
        """
        if self._loaded:
            return True
        try:
            collection = self._client().get_collection(config.COLLECTION)
            stored = collection.get(include=["documents", "metadatas"])
        except Exception as error:
            logger.warning("knowledge base not indexed yet: %s", error)
            return False

        ids = stored.get("ids") or []
        if not ids:
            return False

        self._collection = collection
        self._adopt([
            Chunk(id=i, text=d, metadata=m or {})
            for i, d, m in zip(ids, stored["documents"], stored["metadatas"])
        ])
        return True

    @property
    def ready(self) -> bool:
        return self._loaded or self.load()

    def count(self) -> int:
        return len(self._chunks) if self.ready else 0

    # --------------------------------------------------------------- search

    def search(self, query: str, k: int = None) -> list[Hit]:
        """Hybrid search. Returns the fused top-k, best first."""
        k = k or config.TOP_K
        if not self.ready or not query.strip():
            return []

        limit = config.CANDIDATES_PER_RETRIEVER
        sparse_ranking = self._sparse(query, limit)
        dense_ranking = self._dense(query, limit)

        # Reciprocal Rank Fusion over the two rankings.
        fused: dict[str, float] = {}
        dense_positions: dict[str, int] = {}
        sparse_positions: dict[str, int] = {}

        for position, chunk_id in enumerate(sparse_ranking):
            sparse_positions[chunk_id] = position
            fused[chunk_id] = fused.get(chunk_id, 0.0) + WEIGHT_SPARSE / (RRF_K + position)
        for position, chunk_id in enumerate(dense_ranking):
            dense_positions[chunk_id] = position
            fused[chunk_id] = fused.get(chunk_id, 0.0) + WEIGHT_DENSE / (RRF_K + position)

        language = detect_language(query)
        by_id = {c.id: c for c in self._chunks}

        hits: list[Hit] = []
        for chunk_id, score in fused.items():
            chunk = by_id.get(chunk_id)
            if not chunk:
                continue
            if chunk.metadata.get("lang") == language:
                score *= SAME_LANGUAGE_BOOST
            hits.append(Hit(
                id=chunk_id,
                text=chunk.text,
                metadata=chunk.metadata,
                score=score,
                dense_rank=dense_positions.get(chunk_id),
                sparse_rank=sparse_positions.get(chunk_id),
            ))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    def _sparse(self, query: str, limit: int) -> list[str]:
        tokens = tokenize(query)
        if not tokens or not self._bm25:
            return []
        scored = self._bm25.scores(tokens)
        ordered = sorted(range(len(scored)), key=lambda i: scored[i], reverse=True)
        # A zero score means not one query term appeared; ranking those would
        # feed the fusion pure noise.
        return [self._chunks[i].id for i in ordered[:limit] if scored[i] > 0]

    def _dense(self, query: str, limit: int) -> list[str]:
        vectors = ollama.embed([query], is_query=True)
        if not vectors:
            return []
        try:
            result = self._collection.query(
                query_embeddings=vectors, n_results=min(limit, len(self._chunks))
            )
        except Exception as error:
            logger.warning("dense query failed: %s", error)
            return []
        ids = result.get("ids") or [[]]
        return ids[0] if ids else []


# One process-wide instance; Chroma and the BM25 index are both reusable.
store = KnowledgeStore()
