import hashlib
import os
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import redis
import voyageai
from redis.commands.search.field import TextField, TagField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

VECTOR_DIM = 1024  # voyage-3.5-lite default — FROZEN, publish this
EMBED_MODEL = "voyage-3.5-lite"

# --- Full-document storage (doc:* keyspace + idx:docs chunk index) ---
DOC_TEXT_MAX_CHARS = 200_000
DOC_CHUNK_TARGET_TOKENS = 512
DOC_URL_INDEX_KEY = "doc:url_index"  # hash: sha256(canonical_url) -> doc key


def _canonical_url(url: str) -> str:
    """Normalize a URL for dedup: lowercase scheme/host, drop fragment, strip
    trailing slash. Query string is preserved (it can be significant)."""
    parts = urlsplit((url or "").strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _redis_client(redis_url=None, host="localhost", port=6379):
    url = redis_url or os.environ.get("REDIS_URL")
    if url:
        return redis.from_url(url, decode_responses=True)
    return redis.Redis(host=host, port=port, decode_responses=True)


class Memory:
    def __init__(self, redis_url=None, host="localhost", port=6379):
        self.r = _redis_client(redis_url=redis_url, host=host, port=port)
        self._vo = None
        self._ensure_index()
        self._ensure_docs_index()

    @property
    def vo(self):
        if self._vo is None:
            self._vo = voyageai.Client()
        return self._vo

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.vo.embed(
            texts, model=EMBED_MODEL, input_type="document"
        ).embeddings

    def embed_query(self, text: str) -> list[float]:
        return self.vo.embed(
            [text], model=EMBED_MODEL, input_type="query"
        ).embeddings[0]

    def _ensure_index(self):
        schema = (
            TextField("$.failure_mode", as_name="failure_mode"),
            TextField("$.system_config", as_name="system_config"),
            TextField("$.operating_conditions", as_name="operating_conditions"),
            TextField("$.root_cause", as_name="root_cause"),
            TextField("$.corrective_action", as_name="corrective_action"),
            TagField("$.source", as_name="source"),
            TagField("$.source_type", as_name="source_type"),
            VectorField(
                "$.embedding",
                "HNSW",
                {
                    "TYPE": "FLOAT32",
                    "DIM": VECTOR_DIM,
                    "DISTANCE_METRIC": "COSINE",
                },
                as_name="embedding",
            ),
            VectorField(
                "$.rc_embedding",
                "HNSW",
                {
                    "TYPE": "FLOAT32",
                    "DIM": VECTOR_DIM,
                    "DISTANCE_METRIC": "COSINE",
                },
                as_name="rc_embedding",
            ),
        )
        try:
            self.r.ft("idx:failures").info()
        except redis.exceptions.ResponseError:
            self.r.ft("idx:failures").create_index(
                schema,
                definition=IndexDefinition(
                    prefix=["failure:"], index_type=IndexType.JSON
                ),
            )

    def _ensure_docs_index(self):
        """Create ``idx:docs`` over the ``docchunk:`` prefix if missing.

        Passage-level index for full web documents. Uses the SAME embedding model
        and frozen ``VECTOR_DIM`` as ``idx:failures`` so one Voyage client serves
        both indexes.
        """
        schema = (
            TextField("$.text", as_name="text"),
            TagField("$.doc_id", as_name="doc_id"),
            TagField("$.source", as_name="source"),
            TagField("$.source_type", as_name="source_type"),
            VectorField(
                "$.embedding",
                "HNSW",
                {
                    "TYPE": "FLOAT32",
                    "DIM": VECTOR_DIM,
                    "DISTANCE_METRIC": "COSINE",
                },
                as_name="embedding",
            ),
        )
        try:
            self.r.ft("idx:docs").info()
        except redis.exceptions.ResponseError:
            self.r.ft("idx:docs").create_index(
                schema,
                definition=IndexDefinition(
                    prefix=["docchunk:"], index_type=IndexType.JSON
                ),
            )

    def _index_doc_chunks(self, source, doc_id, text: str):
        """Chunk ``text`` and (re)write ``docchunk:{doc_id}:{n}`` records.

        Existing chunks for ``doc_id`` are deleted first so re-writing a document
        never leaves stale chunks. Embedding failures are swallowed: the document
        record itself is already stored, and missing chunks only degrade passage
        search, not document retrieval.
        """
        from memory.llm.prefilter import chunk_text

        for old in self.r.keys(f"docchunk:{doc_id}:*"):
            self.r.delete(old)
        if not (text or "").strip():
            return
        chunks = chunk_text(text, target_tokens=DOC_CHUNK_TARGET_TOKENS)
        if not chunks:
            return
        try:
            embeddings = self.embed_documents(chunks)
        except Exception as exc:  # noqa: BLE001 - chunk search is best-effort
            print(f"[memory] doc chunk embedding failed for {doc_id}: {exc}")
            return
        for n, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            self.r.json().set(
                f"docchunk:{doc_id}:{n}",
                "$",
                {
                    "doc_id": doc_id,
                    "source": source,
                    "source_type": source,
                    "chunk_index": n,
                    "text": chunk,
                    "embedding": emb,
                },
            )

    def _failure_text(self, fields: dict) -> str:
        parts = []
        for field in (
            "failure_mode",
            "root_cause",
            "system_config",
            "operating_conditions",
            "corrective_action",
        ):
            val = str(fields.get(field, "")).strip()
            if val:
                parts.append(val)
        return " ".join(parts)

    def write_failure(self, source, id_, fields: dict):
        combined_text = self._failure_text(fields)
        root_cause_text = str(fields.get("root_cause", "")).strip()
        emb, rc_emb = self.embed_documents([combined_text, root_cause_text])
        key = f"failure:{source}:{id_}"
        self.r.json().set(
            key,
            "$",
            {
                **fields,
                "id": id_,
                "source": source,
                "source_type": source,
                "embedding": emb,
                "rc_embedding": rc_emb,
            },
        )
        return key

    def has_document_by_url(self, url: str) -> str | None:
        """Return the stored ``doc:*`` key for ``url`` if it was already fetched,
        else ``None``. Uses the canonical-URL dedup hash for O(1) lookups."""
        canonical = _canonical_url(url)
        if not canonical:
            return None
        return self.r.hget(DOC_URL_INDEX_KEY, _url_hash(canonical))

    def get_document(self, source, doc_id):
        """Return the full ``doc:{source}:{doc_id}`` JSON document, or ``None``."""
        return self.r.json().get(f"doc:{source}:{doc_id}")

    def write_document(
        self,
        source,
        doc_id,
        *,
        url="",
        title="",
        full_text="",
        content_type="",
        raw_bytes=None,
    ):
        """Store one fetched web document at ``doc:{source}:{doc_id}``.

        Records the full extracted text (capped at ``DOC_TEXT_MAX_CHARS``) plus
        provenance metadata, registers the canonical URL in the dedup hash so the
        same source is never fetched twice, and indexes the text for passage-level
        semantic search (see ``search_documents``). Idempotent: re-writing the same
        key overwrites in place and re-indexes its chunks.
        """
        canonical = _canonical_url(url) if url else ""
        text = (full_text or "")[:DOC_TEXT_MAX_CHARS]
        if raw_bytes is not None:
            sha = hashlib.sha256(raw_bytes).hexdigest()
            byte_len = len(raw_bytes)
        else:
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
            byte_len = len(text.encode("utf-8"))
        now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        key = f"doc:{source}:{doc_id}"
        self.r.json().set(
            key,
            "$",
            {
                "doc_id": doc_id,
                "url": url,
                "canonical_url": canonical,
                "source": source,
                "source_type": source,
                "title": title,
                "full_text": text,
                "content_type": content_type,
                "sha256": sha,
                "fetched_at": now,
                "byte_len": byte_len,
            },
        )
        if canonical:
            self.r.hset(DOC_URL_INDEX_KEY, _url_hash(canonical), key)
        self._index_doc_chunks(source, doc_id, text)
        return key

    def write_design(self, session_id, iteration, payload: dict):
        key = f"design:{session_id}:{iteration}"
        self.r.json().set(
            key,
            "$",
            {
                **payload,
                "session_id": session_id,
                "iteration": iteration,
                "timestamp": int(time.time()),
                "source_type": "internal",
            },
        )
        return key

    def backfill_source_type(self):
        """Set ``source_type`` on any ``failure:*`` record missing it.

        Older records were written before ``source_type`` existed; this mirrors
        each record's ``source`` into ``source_type`` without re-embedding.
        """
        updated = 0
        for key in self.r.keys("failure:*"):
            existing = self.r.json().get(key, "$.source_type")
            if existing:
                continue
            source = self.r.json().get(key, "$.source")
            source_val = source[0] if isinstance(source, list) and source else "external"
            self.r.json().set(key, "$.source_type", source_val)
            updated += 1
        return updated

    def get_design_history(self, session_id):
        keys = sorted(
            self.r.keys(f"design:{session_id}:*"),
            key=lambda k: int(k.split(":")[-1]),
        )
        return [self.r.json().get(k) for k in keys]

    def search_failures(self, query_text: str, k=5, source=None, field="combined"):
        qvec = np.array(self.embed_query(query_text), dtype=np.float32).tobytes()
        filt = f"@source:{{{source}}}" if source else "*"
        vector_field = "rc_embedding" if field == "root_cause" else "embedding"
        q = (
            Query(f"({filt})=>[KNN {k} @{vector_field} $vec AS score]")
            .sort_by("score")
            .return_fields(
                "failure_mode",
                "root_cause",
                "corrective_action",
                "source",
                "source_type",
                "score",
            )
            .dialect(2)
        )
        res = self.r.ft("idx:failures").search(q, query_params={"vec": qvec})
        results = [
            {
                "id": d.id,
                "score": float(d.score),
                "source": d.source,
                "source_type": getattr(d, "source_type", None) or d.source,
                "failure_mode": d.failure_mode,
                "root_cause": d.root_cause,
                "corrective_action": d.corrective_action,
            }
            for d in res.docs
        ]
        if os.getenv("MEMORY_DEBUG"):
            for chunk in results:
                print(
                    f"[MEMORY_DEBUG] id={chunk['id']} "
                    f"source_type={chunk['source_type']} "
                    f"score={chunk['score']:.4f}"
                )
        return results

    def search_documents(self, query_text: str, k=5, source=None):
        """Semantic k-NN over full-document chunks (``idx:docs``).

        Returns the most relevant passages from stored web documents, each with
        its parent ``doc_id`` so callers can load the full record via
        ``get_document``. ``source`` filters by the document's source tag; omit it
        to search all documents. Score is COSINE distance (lower = closer).
        """
        qvec = np.array(self.embed_query(query_text), dtype=np.float32).tobytes()
        filt = f"@source:{{{source}}}" if source else "*"
        q = (
            Query(f"({filt})=>[KNN {k} @embedding $vec AS score]")
            .sort_by("score")
            .return_fields(
                "doc_id",
                "source",
                "source_type",
                "chunk_index",
                "text",
                "score",
            )
            .dialect(2)
        )
        res = self.r.ft("idx:docs").search(q, query_params={"vec": qvec})
        return [
            {
                "id": d.id,
                "score": float(d.score),
                "doc_id": getattr(d, "doc_id", None),
                "source": getattr(d, "source", None),
                "source_type": getattr(d, "source_type", None) or getattr(d, "source", None),
                "chunk_index": int(getattr(d, "chunk_index", 0) or 0),
                "text": getattr(d, "text", ""),
            }
            for d in res.docs
        ]
