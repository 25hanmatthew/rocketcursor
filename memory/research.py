"""Self-contained prior-art research: retrieval-first, then live web search.

This module is the reusable research layer for the memory package. It provides
three callables built on the Browserbase/Stagehand NTRS search + extraction
primitives in :mod:`memory.ingest_failures`:

- ``search_web(query, ...)``        -> discover NTRS PDF sources for a query
- ``fetch_and_extract(source, ...)``-> download + extract one source
- ``research_failure_mode(query, *, mem, ...)`` -> the orchestration entry point

``research_failure_mode`` is retrieval-first: it queries existing memory (failure
records + document-chunk passages) and only hits the web when local coverage is
weak. Anything newly fetched is written back to Redis (full document via
``write_document`` + structured failure via ``write_failure``), and the function
returns a ranked, provenance-tagged, inject-ready list of cases.

Design constraints:
- Nothing here imports or touches the ``loop`` package. Wiring the returned cases
  into a running agent is the caller's responsibility (out of scope here).
- Web access is best-effort: any failure (missing env, CAPTCHA, network) degrades
  to whatever local/partial results are available and never raises.
- The :mod:`memory.ingest_failures` CLI is reused, not modified.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from memory import ingest_failures as ing

# --- Tune: retrieval-first coverage gate + web budget defaults ---
DEFAULT_K_LOCAL = 5
DEFAULT_MIN_LOCAL_HITS = 3
# Cosine DISTANCE threshold (lower = closer). If the best local hit is farther
# than this, local coverage is considered weak and web research is triggered.
DEFAULT_MAX_LOCAL_DISTANCE = 0.35
DEFAULT_MAX_WEB_SOURCES = 3
DEFAULT_BUDGET_SEC = 120.0

# --- IRIS transferability framing (see memory/IRIS_FRAMING.md) ---
IRIS_INTERNAL = "internal case: apply as a direct design constraint"
IRIS_EXTERNAL = (
    "external case: apply only via an explicit structural analogy; "
    "otherwise the lesson does not transfer"
)


@dataclass
class BrowserSession:
    """Handle for an active Stagehand session."""

    client: Any
    session_id: str
    cdp_url: str


@contextmanager
def _browser_session() -> Iterator[BrowserSession]:
    """Start a Stagehand session and always end it on exit."""
    client = ing.Stagehand()
    resp = client.sessions.start(model_name="anthropic/claude-sonnet-4-6")
    session_id = resp.data.session_id
    cdp_url = resp.data.cdp_url or ""
    try:
        yield BrowserSession(client, session_id, cdp_url)
    finally:
        try:
            client.sessions.end(id=session_id)
        except Exception:  # noqa: BLE001 - teardown must not raise
            pass


@contextmanager
def _existing_session(session: BrowserSession) -> Iterator[BrowserSession]:
    yield session


def _session_ctx(session: BrowserSession | None):
    """Reuse a caller-provided session, or open (and own) a fresh one."""
    return _existing_session(session) if session is not None else _browser_session()


def _safe(fn: Callable[[], Any], default: Any, label: str) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - research is best-effort
        print(f"[research] {label} failed: {type(exc).__name__}: {exc}")
        return default


def _transferability(source_type: str | None) -> str:
    return IRIS_INTERNAL if (source_type or "").lower() == "internal" else IRIS_EXTERNAL


# --------------------------------------------------------------------------- #
# Web layer (best-effort; reuses ingest_failures primitives)
# --------------------------------------------------------------------------- #

def search_web(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_WEB_SOURCES,
    google_pages: int = 1,
    session: BrowserSession | None = None,
) -> list[ing.NtrsSource]:
    """Discover NTRS PDF sources for ``query`` via Google site search.

    Manages its own browser session when ``session`` is not supplied. Deduplicates
    by citation id and caps the result count at ``max_results``.
    """
    out: list[ing.NtrsSource] = []
    seen: set[str] = set()
    with _session_ctx(session) as sess:
        for google_url, term in ing._build_google_ntrs_search_urls([query], google_pages):
            try:
                candidates = ing._discover_ntrs_pdf_links(
                    sess.client, sess.session_id, google_url, term, cdp_url=sess.cdp_url
                )
            except Exception as exc:  # noqa: BLE001 - skip a blocked page
                print(f"[research] search page failed ({term!r}): {type(exc).__name__}: {exc}")
                continue
            for cand in candidates:
                cid = cand.get("citation_id", "")
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                out.append(cand)
                if len(out) >= max_results:
                    return out
    return out


def fetch_and_extract(
    source: ing.NtrsSource,
    *,
    session: BrowserSession | None = None,
) -> tuple[dict[str, str], str, str]:
    """Download one NTRS PDF and extract (fields, full_text, title).

    ``full_text`` is the raw extracted PDF text (for ``write_document``); ``fields``
    are the structured FailureReport fields (for ``write_failure``).
    """
    with _session_ctx(session) as sess:
        pdf_path = ing._download_ntrs_pdf(source["pdf_url"], source["citation_id"])
        full_text = ing._pdf_text(pdf_path)
        fields, title, _ntrs_id = ing._extract_ntrs_pdf(sess.client, sess.session_id, source)
    return fields, full_text, (title or source.get("title", ""))


def _gather_web_cases(
    query: str,
    *,
    mem: Any,
    max_web_sources: int,
    google_pages: int,
    budget_sec: float,
) -> list[str]:
    """Search the web, extract, and write new docs/failures to Redis.

    Returns the slugs of newly written failure records. Best-effort throughout:
    any error degrades gracefully and is logged, never raised.
    """
    written: list[str] = []
    start = time.monotonic()
    try:
        with _browser_session() as sess:
            sources = search_web(
                query,
                max_results=max_web_sources,
                google_pages=google_pages,
                session=sess,
            )
            for src in sources:
                if time.monotonic() - start > budget_sec:
                    print("[research] time budget exceeded; stopping web research")
                    break
                url = src.get("pdf_url", "")
                if not url:
                    continue
                if mem.has_document_by_url(url):
                    print(f"[research] skip (already stored): {url}")
                    continue
                try:
                    fields, full_text, title = fetch_and_extract(src, session=sess)
                except Exception as exc:  # noqa: BLE001 - skip a bad source
                    print(f"[research] extract failed for {url}: {type(exc).__name__}: {exc}")
                    continue
                if not (fields.get("failure_mode") or fields.get("root_cause")):
                    continue
                citation_id = src.get("citation_id") or ing._ntrs_id_from_url(url)
                _safe(
                    lambda: mem.write_document(
                        "ntrs",
                        citation_id,
                        url=url,
                        title=title,
                        full_text=full_text,
                        content_type="pdf",
                    ),
                    None,
                    "write_document",
                )
                slug = ing._make_slug(title, url, ntrs_id=citation_id)
                key = _safe(
                    lambda: mem.write_failure("external", slug, fields),
                    None,
                    "write_failure",
                )
                if key:
                    written.append(slug)
                    print(f"[research] stored {key}")
    except Exception as exc:  # noqa: BLE001 - web research is optional
        print(f"[research] web research degraded: {type(exc).__name__}: {exc}")
    return written


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def _coverage_ok(
    failures: list[dict],
    min_hits: int,
    max_distance: float,
) -> bool:
    """Local coverage is sufficient when we have enough hits AND the closest one
    is within ``max_distance`` (cosine distance; results are ascending by score)."""
    if len(failures) < min_hits:
        return False
    best = min((f.get("score", 1e9) for f in failures), default=1e9)
    return best <= max_distance


def _format_cases(
    failures: list[dict],
    docs: list[dict],
    *,
    researched_web: bool,
) -> list[dict]:
    """Merge failure records + document passages into a ranked, inject-ready list.

    Each case carries provenance (``source``/``source_type``) and an IRIS
    ``transferability`` note so a downstream caller can frame it correctly.
    """
    cases: list[dict] = []
    for f in failures or []:
        st = f.get("source_type") or f.get("source")
        cases.append(
            {
                "kind": "failure",
                "id": f.get("id"),
                "score": f.get("score"),
                "source": f.get("source"),
                "source_type": st,
                "failure_mode": f.get("failure_mode"),
                "root_cause": f.get("root_cause"),
                "corrective_action": f.get("corrective_action"),
                "transferability": _transferability(st),
                "researched_web": researched_web,
            }
        )
    for d in docs or []:
        st = d.get("source_type") or d.get("source")
        cases.append(
            {
                "kind": "document_passage",
                "id": d.get("id"),
                "doc_id": d.get("doc_id"),
                "score": d.get("score"),
                "source": d.get("source"),
                "source_type": st,
                "text": d.get("text"),
                "transferability": _transferability(st),
                "researched_web": researched_web,
            }
        )
    cases.sort(key=lambda c: c["score"] if c.get("score") is not None else 1e9)
    return cases


def research_failure_mode(
    query: str,
    *,
    mem: Any,
    k_local: int = DEFAULT_K_LOCAL,
    min_local_hits: int = DEFAULT_MIN_LOCAL_HITS,
    max_local_distance: float = DEFAULT_MAX_LOCAL_DISTANCE,
    max_web_sources: int = DEFAULT_MAX_WEB_SOURCES,
    google_pages: int = 1,
    allow_web: bool = True,
    budget_sec: float = DEFAULT_BUDGET_SEC,
) -> list[dict]:
    """Retrieval-first research for a failure mode / phenomenon.

    1. Query existing memory (``search_failures`` + ``search_documents``).
    2. If local coverage is weak (and ``allow_web`` and env is configured), search
       the web, extract, and write new docs/failures to Redis.
    3. Return a ranked, provenance-tagged list of cases ready for injection.

    Never raises: web/local failures degrade to whatever results are available.
    """
    local_failures = _safe(lambda: mem.search_failures(query, k=k_local), [], "search_failures")
    local_docs = _safe(lambda: mem.search_documents(query, k=k_local), [], "search_documents")

    if not allow_web or _coverage_ok(local_failures, min_local_hits, max_local_distance):
        return _format_cases(local_failures, local_docs, researched_web=False)

    if not ing._env_ready():
        print("[research] web search skipped: missing Browserbase/model env vars")
        return _format_cases(local_failures, local_docs, researched_web=False)

    written = _gather_web_cases(
        query,
        mem=mem,
        max_web_sources=max_web_sources,
        google_pages=google_pages,
        budget_sec=budget_sec,
    )

    # Re-query so newly written documents/failures are reflected in the result.
    merged_failures = _safe(
        lambda: mem.search_failures(query, k=k_local), local_failures, "search_failures"
    )
    merged_docs = _safe(
        lambda: mem.search_documents(query, k=k_local), local_docs, "search_documents"
    )
    return _format_cases(merged_failures, merged_docs, researched_web=bool(written))
