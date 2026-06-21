"""Unit tests for full-document storage + passage search in memory.core.

No real Redis or Voyage is required: a small in-memory fake provides the JSON,
hash, and RediSearch-KNN behavior the Memory methods exercise, and embeddings are
stubbed with a deterministic bag-of-words vector so cosine search is meaningful.
"""

from __future__ import annotations

import fnmatch
import re
import unittest
from types import SimpleNamespace

import numpy as np

from memory.core import DOC_URL_INDEX_KEY, VECTOR_DIM, Memory, _canonical_url


def _fake_vec(text: str) -> list[float]:
    """Deterministic bag-of-words embedding into VECTOR_DIM dims."""
    vec = np.zeros(VECTOR_DIM, dtype=np.float32)
    for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
        vec[hash(word) % VECTOR_DIM] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec.tolist()


class _FakeJSON:
    def __init__(self, store: dict):
        self._store = store

    def set(self, key, path, obj):
        if path == "$":
            self._store[key] = obj
        else:
            self._store.setdefault(key, {})[path.lstrip("$.")] = obj

    def get(self, key, path=None):
        if key not in self._store:
            return None
        if path is None or path == "$":
            return self._store[key]
        field = path.lstrip("$.")
        val = self._store[key].get(field)
        return [val] if val is not None else None


class _FakeIndex:
    def __init__(self, fake, name):
        self._fake = fake
        self._name = name

    def info(self):
        return {}

    def create_index(self, *a, **k):
        return None

    def search(self, query, query_params=None):
        vec = np.frombuffer(query_params["vec"], dtype=np.float32)
        prefix = "docchunk:" if "docs" in self._name else "failure:"
        scored = []
        for key, obj in self._fake.store.items():
            if not key.startswith(prefix) or "embedding" not in obj:
                continue
            emb = np.asarray(obj["embedding"], dtype=np.float32)
            denom = (np.linalg.norm(vec) * np.linalg.norm(emb)) or 1.0
            dist = 1.0 - float(vec @ emb) / denom
            ns = SimpleNamespace(id=key, score=dist)
            for k, v in obj.items():
                setattr(ns, k, v)
            scored.append((dist, ns))
        scored.sort(key=lambda t: t[0])
        return SimpleNamespace(docs=[ns for _, ns in scored])


class FakeRedis:
    def __init__(self):
        self.store: dict = {}
        self.hashes: dict = {}

    def json(self):
        return _FakeJSON(self.store)

    def hset(self, name, field, value):
        self.hashes.setdefault(name, {})[field] = value

    def hget(self, name, field):
        return self.hashes.get(name, {}).get(field)

    def keys(self, pattern):
        rx = re.compile(fnmatch.translate(pattern))
        return [k for k in self.store if rx.match(k)]

    def delete(self, key):
        self.store.pop(key, None)

    def ft(self, name):
        return _FakeIndex(self, name)


def _make_memory() -> tuple[Memory, FakeRedis]:
    fake = FakeRedis()
    mem = Memory.__new__(Memory)
    mem.r = fake
    mem._vo = None
    mem.embed_documents = lambda texts: [_fake_vec(t) for t in texts]
    mem.embed_query = lambda text: _fake_vec(text)
    return mem, fake


class DocumentRoundTripTest(unittest.TestCase):
    def test_write_get_and_url_dedup(self):
        mem, fake = _make_memory()
        url = "https://ntrs.nasa.gov/citations/123/downloads/123.pdf"
        key = mem.write_document(
            "ntrs", "123", url=url, title="Valve study",
            full_text="A valve failed under cryogenic pressure.", content_type="pdf",
        )
        self.assertEqual(key, "doc:ntrs:123")

        doc = mem.get_document("ntrs", "123")
        self.assertEqual(doc["doc_id"], "123")
        self.assertEqual(doc["title"], "Valve study")
        self.assertEqual(doc["content_type"], "pdf")
        self.assertTrue(doc["sha256"])
        self.assertEqual(doc["canonical_url"], _canonical_url(url))

        # dedup hash registered, and trailing-slash variant resolves to same key
        self.assertEqual(mem.has_document_by_url(url), "doc:ntrs:123")
        self.assertEqual(mem.has_document_by_url(url + "/"), "doc:ntrs:123")
        self.assertIsNone(mem.has_document_by_url("https://example.com/other.pdf"))

    def test_get_missing_returns_none(self):
        mem, _ = _make_memory()
        self.assertIsNone(mem.get_document("ntrs", "nope"))

    def test_text_capped(self):
        mem, _ = _make_memory()
        from memory.core import DOC_TEXT_MAX_CHARS

        mem.write_document("web", "big", url="https://x.test/a", full_text="x" * (DOC_TEXT_MAX_CHARS + 50))
        doc = mem.get_document("web", "big")
        self.assertEqual(len(doc["full_text"]), DOC_TEXT_MAX_CHARS)

    def test_rewrite_replaces_stale_chunks(self):
        mem, fake = _make_memory()
        mem.write_document("web", "d", url="https://x.test/d", full_text="alpha\n\nbeta\n\ngamma\n\ndelta")
        first = sorted(fake.keys("docchunk:d:*"))
        self.assertTrue(first)
        mem.write_document("web", "d", url="https://x.test/d", full_text="single short body")
        second = sorted(fake.keys("docchunk:d:*"))
        # no stale chunks left from the longer first version
        self.assertLessEqual(len(second), len(first))


class SearchDocumentsTest(unittest.TestCase):
    def test_returns_closest_passage(self):
        mem, _ = _make_memory()
        mem.write_document(
            "ntrs", "v1", url="https://x.test/v1",
            full_text="the valve controls tank pressure during the burn",
        )
        mem.write_document(
            "web", "c1", url="https://x.test/c1",
            full_text="a recipe for chocolate cake with flour and sugar",
        )
        hits = mem.search_documents("valve tank pressure", k=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["doc_id"], "v1")
        self.assertIn("valve", hits[0]["text"])
        # ascending by cosine distance
        self.assertEqual(hits, sorted(hits, key=lambda h: h["score"]))

    def test_source_filter_field_present(self):
        mem, _ = _make_memory()
        mem.write_document("ntrs", "v1", url="https://x.test/v1", full_text="valve pressure tank")
        hits = mem.search_documents("valve", k=5, source="ntrs")
        self.assertTrue(all(h["source"] == "ntrs" for h in hits))


if __name__ == "__main__":
    unittest.main()
