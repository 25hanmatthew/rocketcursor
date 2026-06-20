import redis
import numpy as np
from redis.commands.search.field import TextField, TagField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

VECTOR_DIM = 1536  # placeholder — match your real embedding model later

r = redis.Redis(host="localhost", port=6379, decode_responses=True)


# 1. create the index (idempotent)
def create_index():
    schema = (
        TextField("$.failure_mode", as_name="failure_mode"),
        TextField("$.root_cause", as_name="root_cause"),
        TextField("$.corrective_action", as_name="corrective_action"),
        TagField("$.source", as_name="source"),
        VectorField(
            "$.embedding",
            "HNSW",
            {"TYPE": "FLOAT32", "DIM": VECTOR_DIM, "DISTANCE_METRIC": "COSINE"},
            as_name="embedding",
        ),
    )
    try:
        r.ft("idx:failures").info()
        print("index already exists")
    except redis.exceptions.ResponseError:
        r.ft("idx:failures").create_index(
            schema,
            definition=IndexDefinition(prefix=["failure:"], index_type=IndexType.JSON),
        )
        print("index created")


# 2. write one dummy failure with a random vector
def write_dummy():
    vec = np.random.rand(VECTOR_DIM).astype(np.float32).tolist()
    r.json().set(
        "failure:external:dummy1",
        "$",
        {
            "id": "dummy1",
            "failure_mode": "valve stuck open under cryogenic load",
            "root_cause": "seal contraction at low temperature",
            "corrective_action": "switched to cryo-rated elastomer seal",
            "source": "external",
            "embedding": vec,
        },
    )
    print("wrote failure:external:dummy1")
    return vec


# 3. KNN search using that same vector as the query (should return itself, score ~0)
def search(query_vec):
    vec = np.array(query_vec, dtype=np.float32).tobytes()
    q = (
        Query("(*)=>[KNN 3 @embedding $vec AS score]")
        .sort_by("score")
        .return_fields("failure_mode", "root_cause", "source", "score")
        .dialect(2)
    )
    res = r.ft("idx:failures").search(q, query_params={"vec": vec})
    print(f"got {len(res.docs)} results:")
    for d in res.docs:
        print(f"  {d.id}  score={d.score}  mode={d.failure_mode}")


create_index()
v = write_dummy()
search(v)
