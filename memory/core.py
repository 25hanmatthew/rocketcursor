import os
import redis
import time
import numpy as np
import voyageai
from redis.commands.search.field import TextField, TagField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

VECTOR_DIM = 1024  # voyage-3.5-lite default — FROZEN, publish this
EMBED_MODEL = "voyage-3.5-lite"


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
                "source_type": "internal",
                "embedding": emb,
                "rc_embedding": rc_emb,
            },
        )
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
                "source_type": d.source_type,
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
