"""Unit tests for memory.research (web layer fully mocked).

Verifies the retrieval-first short-circuit, the dedup-before-fetch guard, writeback
to Redis, and the IRIS transferability framing -- all without a browser, network,
or real Redis.
"""

from __future__ import annotations

import contextlib
import unittest
from unittest.mock import MagicMock, patch

from memory import research as R


class FakeMemory:
    """Records write_document / write_failure calls; canned local search results."""

    def __init__(self, failures=None, docs=None, stored_urls=None):
        self._failures = failures or []
        self._docs = docs or []
        self._stored_urls = set(stored_urls or [])
        self.documents_written = []
        self.failures_written = []

    def search_failures(self, query, k=5):
        return list(self._failures)

    def search_documents(self, query, k=5):
        return list(self._docs)

    def has_document_by_url(self, url):
        return f"doc:ntrs:{url}" if url in self._stored_urls else None

    def write_document(self, source, doc_id, **kw):
        self.documents_written.append((source, doc_id, kw))
        return f"doc:{source}:{doc_id}"

    def write_failure(self, source, slug, fields):
        self.failures_written.append((source, slug, fields))
        return f"failure:{source}:{slug}"


_CLOSE = [{"id": "a", "score": 0.05, "source": "external", "source_type": "external",
           "failure_mode": "m", "root_cause": "r", "corrective_action": "c"},
          {"id": "b", "score": 0.10, "source": "external", "source_type": "external"},
          {"id": "c", "score": 0.15, "source": "external", "source_type": "external"}]

_WEAK = [{"id": "a", "score": 0.80, "source": "external", "source_type": "external",
          "failure_mode": "m", "root_cause": "r"}]


class CoverageGateTest(unittest.TestCase):
    def test_short_circuit_when_local_coverage_strong(self):
        mem = FakeMemory(failures=_CLOSE)
        with patch.object(R, "_gather_web_cases") as gather:
            cases = R.research_failure_mode("valve failure", mem=mem)
        gather.assert_not_called()
        self.assertTrue(cases)
        self.assertFalse(any(c["researched_web"] for c in cases))
        # external cases carry the structural-analogy framing
        self.assertTrue(all("structural analogy" in c["transferability"]
                            for c in cases if c["source_type"] == "external"))

    def test_allow_web_false_never_researches(self):
        mem = FakeMemory(failures=_WEAK)
        with patch.object(R, "_gather_web_cases") as gather:
            R.research_failure_mode("valve failure", mem=mem, allow_web=False)
        gather.assert_not_called()

    def test_weak_coverage_but_missing_env_skips_web(self):
        mem = FakeMemory(failures=_WEAK)
        with patch.object(R.ing, "_env_ready", return_value=False), \
                patch.object(R, "_gather_web_cases") as gather:
            cases = R.research_failure_mode("valve failure", mem=mem)
        gather.assert_not_called()
        self.assertFalse(any(c["researched_web"] for c in cases))


class WebResearchTest(unittest.TestCase):
    def test_dedup_and_writeback(self):
        # one source already stored (should be skipped), one new (should be written)
        sources = [
            {"citation_id": "111", "pdf_url": "https://ntrs.nasa.gov/api/citations/111/downloads/111.pdf",
             "title": "Old", "query": "q", "discovered_at": ""},
            {"citation_id": "222", "pdf_url": "https://ntrs.nasa.gov/api/citations/222/downloads/222.pdf",
             "title": "New", "query": "q", "discovered_at": ""},
        ]
        mem = FakeMemory(failures=_WEAK, stored_urls={sources[0]["pdf_url"]})

        @contextlib.contextmanager
        def fake_session():
            yield R.BrowserSession(client=MagicMock(), session_id="s", cdp_url="")

        fields = {"failure_mode": "turbopump cracked", "root_cause": "fatigue",
                  "system_config": "", "operating_conditions": "", "corrective_action": ""}

        with patch.object(R.ing, "_env_ready", return_value=True), \
                patch.object(R, "_browser_session", fake_session), \
                patch.object(R, "search_web", return_value=sources), \
                patch.object(R, "fetch_and_extract", return_value=(fields, "full text body", "New")):
            cases = R.research_failure_mode("turbopump failure", mem=mem)

        # only the non-deduped source was written, both as a doc and a failure
        self.assertEqual([d[1] for d in mem.documents_written], ["222"])
        self.assertEqual(len(mem.failures_written), 1)
        self.assertEqual(mem.failures_written[0][0], "external")
        self.assertEqual(mem.failures_written[0][1], "ntrs_222")
        self.assertTrue(any(c["researched_web"] for c in cases))

    def test_empty_extraction_not_written(self):
        sources = [{"citation_id": "333", "pdf_url": "https://ntrs.nasa.gov/api/citations/333/downloads/333.pdf",
                    "title": "", "query": "q", "discovered_at": ""}]
        mem = FakeMemory(failures=_WEAK)

        @contextlib.contextmanager
        def fake_session():
            yield R.BrowserSession(client=MagicMock(), session_id="s", cdp_url="")

        empty = {"failure_mode": "", "root_cause": "", "system_config": "",
                 "operating_conditions": "", "corrective_action": ""}
        with patch.object(R.ing, "_env_ready", return_value=True), \
                patch.object(R, "_browser_session", fake_session), \
                patch.object(R, "search_web", return_value=sources), \
                patch.object(R, "fetch_and_extract", return_value=(empty, "", "")):
            R.research_failure_mode("nothing useful", mem=mem)

        self.assertEqual(mem.failures_written, [])
        self.assertEqual(mem.documents_written, [])

    def test_local_query_failure_degrades(self):
        mem = FakeMemory(failures=_CLOSE)
        mem.search_documents = MagicMock(side_effect=RuntimeError("redis down"))
        # search_documents raising must not crash; failures still returned
        cases = R.research_failure_mode("valve failure", mem=mem)
        self.assertTrue(cases)


if __name__ == "__main__":
    unittest.main()
