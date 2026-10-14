"""Embedder (SDD §5.1 / issue #35).

Turns chunk text into dense vectors and persists them into `chunks.embedding`.

Two layers:
  * `embed_texts`  — pure, synchronous core. Batches calls to the embedding
    model and retries with exponential backoff. The model is injectable so
    tests can pass a mock (no model download, no network in CI).
  * `embed_document` — async DB I/O around the sync embed core. Skips
    re-embedding when the parent document's `content_hash` is unchanged since
    the last successful embed, otherwise embeds the chunks and upserts them
    into the `chunks` table.

Call-site note: `embed_document` awaits only SQLAlchemy; it calls sync
`embed_texts` inline (model encode + `time.sleep` on retry). That blocks the
asyncio event loop for the duration. Intended for batch ingest (#37 worker/CLI),
not for the FastAPI request loop — offload with `asyncio.to_thread` if needed.

Model: BAAI/bge-base-en-v1.5 (768-dim), run locally via sentence-transformers.
Read from `settings.embedding_model`. See ADR-006 in SDD §13.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingest.chunk import Chunk

logger = logging.getLogger(__name__)

# Tuning. The ADR measures ~100–300ms per 32-chunk batch on CPU.
DEFAULT_BATCH_SIZE = 32
DEFAULT_MAX_RETRIES = 4
DEFAULT_BACKOFF_BASE_SECONDS = 1.0

# An encoder maps a batch of texts to a batch of vectors.
Encoder = Callable[[list[str]], list[list[float]]]
Sleeper = Callable[[float], None]

# Lazily-constructed SentenceTransformer models, keyed by model name, so the
# (expensive) load happens once per process and never at import time.
_model_cache: dict[str, object] = {}


@dataclass(frozen=True)
class EmbedResult:
    """Outcome of embedding a single document."""

    document_id: str
    embedded: int  # number of chunks embedded and upserted
    skipped: bool  # True when content_hash was unchanged


def _load_model(name: str) -> object:
    """Load (and cache) a SentenceTransformer by name. Imported lazily so the
    heavy dependency is only touched when real embedding is requested."""
    if name not in _model_cache:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model %r", name)
        _model_cache[name] = SentenceTransformer(name)
    return _model_cache[name]


def _default_encoder(texts: list[str]) -> list[list[float]]:
    """Encode with the configured local model. Normalized embeddings so that
    pgvector cosine distance (the HNSW index uses `vector_cosine_ops`) behaves
    as expected for BGE models."""
    model = _load_model(settings.embedding_model)
    vectors = model.encode(  # type: ignore[attr-defined]
        texts,
        batch_size=DEFAULT_BATCH_SIZE,
        normalize_embeddings=True,
    )
    return [[float(x) for x in vec] for vec in vectors]


def _encode_with_retry(
    encoder: Encoder,
    batch: list[str],
    max_retries: int,
    backoff_base: float,
    sleep: Sleeper,
) -> list[list[float]]:
    """Call the encoder for one batch, retrying on any exception with
    exponential backoff (backoff_base * 2**attempt)."""
    attempt = 0
    while True:
        try:
            return encoder(batch)
        except Exception as exc:  # model/transport errors are opaque; retry them all
            if attempt >= max_retries:
                logger.error("Embedding batch failed after %d retries: %s", max_retries, exc)
                raise
            delay = backoff_base * (2**attempt)
            logger.warning(
                "Embedding batch failed (attempt %d/%d): %s — retrying in %.2fs",
                attempt + 1,
                max_retries,
                exc,
                delay,
            )
            sleep(delay)
            attempt += 1


def embed_texts(
    texts: Sequence[str],
    *,
    encoder: Encoder | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS,
    sleep: Sleeper = time.sleep,
) -> list[list[float]]:
    """Embed `texts` in batches, returning one vector per text (order preserved).

    `encoder` is injectable for testing; when omitted, the configured local
    model is used. Each batch is retried with exponential backoff on failure.
    """
    enc = encoder or _default_encoder
    vectors: list[list[float]] = []
    items = list(texts)
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        vectors.extend(_encode_with_retry(enc, batch, max_retries, backoff_base, sleep))
    return vectors


def _vector_literal(vec: list[float]) -> str:
    """Format a vector as a pgvector string literal, e.g. "[0.1,0.2,0.3]".

    Passed as a bound string and cast with `CAST(:embedding AS vector)` so it
    works regardless of pgvector's psycopg type registration."""
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


_UPSERT_CHUNK_SQL = text(
    """
    INSERT INTO chunks (document_id, ordinal, heading_path, text, token_count, url_anchor, embedding)
    VALUES (:document_id, :ordinal, :heading_path, :text, :token_count, :url_anchor,
            CAST(:embedding AS vector))
    ON CONFLICT (document_id, ordinal) DO UPDATE SET
        heading_path = EXCLUDED.heading_path,
        text         = EXCLUDED.text,
        token_count  = EXCLUDED.token_count,
        url_anchor   = EXCLUDED.url_anchor,
        embedding    = EXCLUDED.embedding
    """
)

_DELETE_EXCESS_SQL = text("DELETE FROM chunks WHERE document_id = :document_id AND ordinal >= :n")
_SELECT_EMBEDDED_HASH_SQL = text("SELECT embedded_hash FROM documents WHERE id = :document_id")
_UPDATE_EMBEDDED_HASH_SQL = text(
    "UPDATE documents SET embedded_hash = :embedded_hash WHERE id = :document_id"
)


async def embed_document(
    session: AsyncSession,
    *,
    document_id: str,
    content_hash: str,
    chunks: Sequence[Chunk],
    encoder: Encoder | None = None,
    force: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS,
) -> EmbedResult:
    """Embed a document's chunks and upsert them into `chunks`.

    Skips entirely when `content_hash` equals the document's stored
    `embedded_hash` (unless `force`), so unchanged pages are not re-embedded.
    On embed, chunk rows are upserted by `(document_id, ordinal)`, any now-excess
    rows from a previous larger chunking are removed, and `embedded_hash` is
    advanced to `content_hash`.
    """
    if not force:
        result = await session.execute(_SELECT_EMBEDDED_HASH_SQL, {"document_id": document_id})
        stored = result.scalar_one_or_none()
        if stored is not None and stored == content_hash:
            logger.info("Skipping %s — content_hash unchanged (%s)", document_id, content_hash[:8])
            return EmbedResult(document_id=document_id, embedded=0, skipped=True)

    # Sync CPU + retry sleep; see module docstring before calling from async HTTP handlers.
    vectors = embed_texts(
        [c.text for c in chunks],
        encoder=encoder,
        batch_size=batch_size,
        max_retries=max_retries,
        backoff_base=backoff_base,
    )

    for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
        await session.execute(
            _UPSERT_CHUNK_SQL,
            {
                "document_id": document_id,
                "ordinal": ordinal,
                "heading_path": chunk.heading_path,
                "text": chunk.text,
                "token_count": chunk.token_count,
                "url_anchor": chunk.url_anchor,
                "embedding": _vector_literal(vector),
            },
        )

    # Drop stale rows if this document now has fewer chunks than before.
    await session.execute(_DELETE_EXCESS_SQL, {"document_id": document_id, "n": len(chunks)})
    await session.execute(
        _UPDATE_EMBEDDED_HASH_SQL, {"document_id": document_id, "embedded_hash": content_hash}
    )
    await session.commit()

    logger.info("Embedded %d chunks for %s", len(chunks), document_id)
    return EmbedResult(document_id=document_id, embedded=len(chunks), skipped=False)
