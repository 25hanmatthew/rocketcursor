"""Ingest aerospace/propulsion failure reports from NASA public sources.

Uses the Stagehand v3 session-based SDK to navigate listing pages, follow report
links, extract structured failure fields, and store them via memory.Memory.

Sources:
  - LLIS: direct site search at llis.nasa.gov
  - NTRS: Google site search (site:ntrs.nasa.gov {query} filetype:pdf), PDF download,
    text extraction, and structured field extraction

Tune SEARCH_QUERIES, PAGES_PER_QUERY, RELEVANCE_KEYWORDS, REPORT_DELAY_SEC, and
FailureReport before production runs.

Phases (--discover / --extract / --load) are resumable via JSON cache files.
With no phase flags, all three run in order using the caches as handoffs.
Use --source llis|ntrs|all to select ingestion source (default: llis).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, TypedDict
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import httpx
from pydantic import BaseModel, Field
from pypdf import PdfReader
from stagehand import Stagehand
from stagehand._exceptions import APIStatusError

from memory.core import Memory
from memory.paths import (
    FIELDS_CACHE,
    NTRS_FIELDS_CACHE,
    NTRS_SOURCES_CACHE,
    PDF_CACHE_DIR,
    URLS_CACHE,
)

# --- Tune: LLIS search queries and pages per query ---
SEARCH_QUERIES = [
    "propellant tank",
    "valve failure",
    "turbopump",
    "pressurization",
    "propellant leak",
    "cryogenic",
    "tank rupture",
    "feed system",
    "combustion instability",
    "thruster",
]
PAGES_PER_QUERY = 1

# --- Tune: relevance gate for propulsion / fluid-systems failure reports ---
RELEVANCE_KEYWORDS = [
    "propulsion",
    "fluid",
    "pressure vessel",
    "tank",
    "valve",
    "turbopump",
    "cryogenic",
    "oxidizer",
    "fuel",
    "engine",
    "rocket",
    "thruster",
    "pressurization",
    "leak",
    "rupture",
    "hypergolic",
    "turbine",
    "pump",
    "nozzle",
    "combustion",
]

# --- Tune: NTRS Google search ---
GOOGLE_PAGES_PER_QUERY = 1
GOOGLE_DELAY_SEC = 3.0
PDF_TEXT_MAX_CHARS = 120_000
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; rocketcursor/1.0; +https://github.com/nasa-research)"
    ),
}

# --- Tune: polite delay between report page navigations (seconds) ---
REPORT_DELAY_SEC = 2.0

DEFAULT_LIMIT = 3
ENV_KEYS = ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID", "MODEL_API_KEY")

# --- LLIS lesson page: section-to-field mapping for FailureReport extraction ---
LLIS_FAILURE_EXTRACT_INSTRUCTION = (
    "This is a NASA Lessons Learned Information System (LLIS) lesson page with named "
    "sections: Subject, Abstract, Driving Event, Lesson(s) Learned, Recommendation(s), "
    "Evidence of Recurrence Control, Program Relation, Topic(s). "
    "Map them to the FailureReport fields as follows:\n"
    "- failure_mode: the specific hardware failure or anomaly that occurred, drawn from "
    "Subject and Driving Event — what failed and how. One to three sentences.\n"
    "- system_config: the system, subsystem, and specific hardware or components involved, "
    "from Driving Event — e.g. subsystem name, component types.\n"
    "- operating_conditions: the conditions under which the failure occurred (test vs "
    "flight, applied loads, voltages, pressures, phase), from Driving Event.\n"
    "- root_cause: the underlying cause(s), from Driving Event and Lesson(s) Learned — "
    "the procedural or physical reason it failed.\n"
    "- corrective_action: the recommendations and preventive measures, from Lesson(s) "
    "Learned and Recommendation(s).\n"
    "Use only information present on the page. Keep each field concise factual prose. "
    "Set a field to an empty string if that information is genuinely absent."
)

GENERIC_FAILURE_EXTRACT_INSTRUCTION = (
    "From this aerospace failure or lessons learned report, extract: "
    "failure_mode (what failed), system_config (vehicle/system hardware), "
    "operating_conditions (mission/ops context), root_cause (underlying cause), "
    "and corrective_action (fixes or recommendations). Use only text present "
    "on the page; leave fields empty when not stated."
)

LLIS_DISCOVERY_EXTRACT_INSTRUCTION = (
    "Look at the page's HTML anchor elements. Return the href attribute value "
    "of every link whose href contains '/lesson/' followed by digits (e.g. /lesson/13801). "
    "Return the raw href strings exactly as they appear in the HTML. Do NOT return link "
    "text, titles, search-result numbers, or reconstructed URLs — only real href values "
    "that contain /lesson/{digits}."
)

GENERIC_DISCOVERY_EXTRACT_INSTRUCTION = (
    "Extract absolute URLs and titles for individual aerospace failure reports, "
    "lessons learned entries, or NTRS citation detail pages visible on this page. "
    "Skip navigation chrome, pagination-only links, and duplicate entries."
)

NTRS_FAILURE_EXTRACT_INSTRUCTION = (
    "This page contains the full text of a NASA Technical Reports Server (NTRS) "
    "technical document. Extract propulsion, fluid-system, or hardware failure "
    "information into the FailureReport fields:\n"
    "- failure_mode: specific hardware failure, anomaly, or incident described — "
    "what failed and how. One to four sentences.\n"
    "- system_config: vehicle, subsystem, and components involved.\n"
    "- operating_conditions: test vs flight, loads, pressures, temperatures, mission phase.\n"
    "- root_cause: underlying physical or procedural cause of the failure or anomaly.\n"
    "- corrective_action: fixes, design changes, or recommendations stated in the report.\n"
    "Focus on failure-related content from abstract, introduction, results, and conclusions. "
    "Ignore bibliography, nomenclature, and unrelated background. "
    "Use only information present in the text. Leave fields empty when not stated."
)

FIELD_KEYS = (
    "failure_mode",
    "system_config",
    "operating_conditions",
    "root_cause",
    "corrective_action",
)


# --- Tune: structured extraction schema (five string fields per report) ---
class FailureReport(BaseModel):
    failure_mode: str = ""
    system_config: str = ""
    operating_conditions: str = ""
    root_cause: str = ""
    corrective_action: str = ""


class ReportListing(BaseModel):
    """Report links discovered on a listing or search results page."""

    report_links: list[str] = Field(
        default_factory=list,
        description=(
            "Raw href attribute values from anchor elements (LLIS: every href containing "
            "/lesson/ followed by digits)."
        ),
    )
    report_titles: list[str] = Field(default_factory=list)


class ReportIdentity(BaseModel):
    """Title or catalog id used to build a stable storage slug."""

    title: str = ""
    ntrs_id: str = ""


class NtrsSource(TypedDict):
    citation_id: str
    pdf_url: str
    title: str
    query: str
    discovered_at: str


def _env_ready() -> bool:
    return all(os.environ.get(k) for k in ENV_KEYS)


def _unwrap_extract_result(response: Any) -> Any:
    if hasattr(response, "data") and hasattr(response.data, "result"):
        return response.data.result
    if isinstance(response, dict):
        data = response.get("data", response)
        if isinstance(data, dict) and "result" in data:
            return data["result"]
    return response


def _unwrap_evaluate_result(payload: Any) -> Any:
    if payload is None:
        return None
    if hasattr(payload, "data") and hasattr(payload.data, "result"):
        return payload.data.result
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, dict) and "result" in data:
            return data["result"]
    return payload


def _cdp_evaluate_js(cdp_url: str, expression: str) -> Any | None:
    """Evaluate JavaScript in the active page via the session CDP URL."""
    try:
        import websockets.sync.client as ws_client
    except ImportError:
        return None

    request_id = 0

    def next_id() -> int:
        nonlocal request_id
        request_id += 1
        return request_id

    def call(ws: Any, method: str, params: dict[str, Any] | None = None, *, session_id: str | None = None) -> dict[str, Any]:
        rid = next_id()
        msg: dict[str, Any] = {"id": rid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        ws.send(json.dumps(msg))
        while True:
            raw = json.loads(ws.recv())
            if raw.get("id") != rid:
                continue
            if "error" in raw:
                raise RuntimeError(str(raw["error"]))
            return raw.get("result") or {}

    try:
        with ws_client.connect(cdp_url, open_timeout=30) as ws:
            targets = call(ws, "Target.getTargets").get("targetInfos") or []
            page_target = next((t for t in targets if t.get("type") == "page"), None)
            if not page_target:
                return None
            attached = call(
                ws,
                "Target.attachToTarget",
                {"targetId": page_target["targetId"], "flatten": True},
            )
            frame_session_id = attached.get("sessionId")
            if not frame_session_id:
                return None
            call(ws, "Runtime.enable", session_id=frame_session_id)
            evaluated = call(
                ws,
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True, "awaitPromise": True},
                session_id=frame_session_id,
            )
            if evaluated.get("exceptionDetails"):
                return None
            return (evaluated.get("result") or {}).get("value")
    except Exception:
        return None


def _session_evaluate_js(
    client: Stagehand,
    session_id: str,
    expression: str,
    *,
    cdp_url: str = "",
) -> Any | None:
    """Run JavaScript in the page; prefer CDP, then undocumented evaluate POST."""
    if cdp_url:
        value = _cdp_evaluate_js(cdp_url, expression)
        if value is not None:
            return value

    for body in (
        {"expression": expression},
        {"script": expression},
        {"code": expression},
    ):
        try:
            raw = client.post(
                f"/v1/sessions/{session_id}/evaluate",
                body=body,
                cast_to=httpx.Response,
            )
        except APIStatusError as exc:
            if exc.status_code == 404:
                return None
            continue
        except Exception:
            continue
        if raw.status_code == 404:
            return None
        try:
            raw.raise_for_status()
        except httpx.HTTPStatusError:
            continue
        try:
            return _unwrap_evaluate_result(raw.json())
        except json.JSONDecodeError:
            continue
    return None


def _lesson_hrefs_from_observe(client: Stagehand, session_id: str) -> list[str]:
    response = client.sessions.observe(
        id=session_id,
        instruction=(
            "Find every link on this page whose href contains '/lesson/' followed by digits. "
            "Return the real anchor elements from the search results."
        ),
    )
    hrefs: list[str] = []
    results = getattr(getattr(response, "data", None), "result", None) or []
    for action in results:
        if hasattr(action, "model_dump"):
            blob = json.dumps(action.model_dump())
        elif hasattr(action, "to_dict"):
            blob = json.dumps(action.to_dict())
        elif isinstance(action, dict):
            blob = json.dumps(action)
        else:
            blob = str(action)
        hrefs.extend(_LESSON_HREF_IN_TEXT_RE.findall(blob))
    return hrefs


def _discover_llis_lesson_hrefs(client: Stagehand, session_id: str, *, cdp_url: str = "") -> list[str]:
    result = _session_evaluate_js(client, session_id, _LESSON_HREF_JS, cdp_url=cdp_url)
    if isinstance(result, list):
        hrefs = [str(href).strip() for href in result if str(href or "").strip()]
        if hrefs:
            return hrefs
    return _lesson_hrefs_from_observe(client, session_id)


def _is_empty_or_404_lesson(fields: dict[str, str], title: str = "") -> bool:
    if not fields.get("failure_mode") and not fields.get("root_cause"):
        return True
    if title and _PAGE_NOT_FOUND_RE.search(title):
        return True
    return False


def _to_plain_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, BaseModel):
        return raw.model_dump()
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        return raw.model_dump()
    if hasattr(raw, "dict"):
        return raw.dict()
    if hasattr(raw, "__dict__"):
        return dict(vars(raw))
    return {}


def _normalize_failure_fields(raw: Any) -> dict[str, str]:
    data = _to_plain_dict(raw)
    return {key: str(data.get(key, "") or "").strip() for key in FIELD_KEYS}


def _session_extract(client: Stagehand, session_id: str, instruction: str, schema_model: type[BaseModel]) -> Any:
    """Extract with Pydantic schema; fall back to JSON Schema if the SDK rejects the class."""
    last_error: Exception | None = None
    for schema in (schema_model, schema_model.model_json_schema()):
        try:
            response = client.sessions.extract(
                id=session_id,
                instruction=instruction,
                schema=schema,
            )
            return _unwrap_extract_result(response)
        except Exception as exc:
            last_error = exc
            if schema is schema_model.model_json_schema():
                raise
    if last_error:
        raise last_error
    raise RuntimeError("extract failed without a captured error")


def _is_relevant(fields: dict[str, str]) -> bool:
    gate_text = f"{fields.get('failure_mode', '')} {fields.get('root_cause', '')}".lower()
    return any(keyword.lower() in gate_text for keyword in RELEVANCE_KEYWORDS)


def _is_llis_lesson_url(url: str) -> bool:
    return "llis.nasa.gov" in url and "/lesson/" in url


def _is_llis_page_url(url: str) -> bool:
    return "llis.nasa.gov" in url


LLIS_BASE = "https://llis.nasa.gov"
NTRS_BASE = "https://ntrs.nasa.gov"
_LESSON_PATH_RE = re.compile(r"/lesson/\d+")
_LESSON_HREF_JS = '[...document.querySelectorAll(\'a[href*="/lesson/"]\')].map(a => a.href)'
_LESSON_HREF_IN_TEXT_RE = re.compile(r"(?:https?://[^\s\"'<>]+)?/lesson/\d+")
_PAGE_NOT_FOUND_RE = re.compile(r"\b(404|not\s+found|page\s+not\s+found|does\s+not\s+exist)\b", re.I)
_NTRS_DOWNLOAD_RE = re.compile(r"/api/citations/\d+/downloads/", re.I)
_NTRS_HREF_IN_TEXT_RE = re.compile(
    r"https?://(?:ntrs\.)?nasa\.gov[^\s\"'<>]*(?:/api/citations/\d+/downloads/[^\s\"'<>]+|/citations/\d+)",
    re.I,
)
_ALL_HREF_JS = '[...document.querySelectorAll("a[href]")].map(a => a.href)'
_PAGE_TEXT_JS = "document.body?.innerText || ''"
_PAGE_TITLE_JS = "document.title || ''"
_CAPTCHA_RE = re.compile(r"unusual traffic|captcha|recaptcha|not a robot", re.I)
_GOOGLE_CONSENT_DISMISSED = False


def _unwrap_google_redirect(url: str) -> str:
    """Resolve google.com/url?q=... wrappers to the target URL."""
    parsed = urlparse((url or "").strip())
    if "google." not in parsed.netloc:
        return url.strip()
    if parsed.path.rstrip("/") == "/url":
        target = parse_qs(parsed.query).get("q", [""])[0]
        if target:
            return unquote(target)
    return url.strip()


def _is_ntrs_host(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("ntrs.nasa.gov") or host == "nasa.gov" and "ntrs" in url.lower()


def _canonical_ntrs_pdf_url(url: str) -> tuple[str, str]:
    """Return (citation_id, canonical pdf_url) or ('', '') if not an NTRS PDF link."""
    resolved = _unwrap_google_redirect(url)
    if not _is_ntrs_host(resolved):
        return "", ""
    citation_id = _ntrs_id_from_url(resolved)
    if not citation_id:
        return "", ""
    parsed = urlparse(resolved)
    path = parsed.path
    if _NTRS_DOWNLOAD_RE.search(path):
        filename = path.rstrip("/").split("/")[-1]
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf" if filename else f"{citation_id}.pdf"
        pdf_url = f"{NTRS_BASE}/api/citations/{citation_id}/downloads/{filename}"
        return citation_id, pdf_url
    if re.search(rf"/citations/{citation_id}(?:/|$)", path):
        pdf_url = f"{NTRS_BASE}/api/citations/{citation_id}/downloads/{citation_id}.pdf"
        return citation_id, pdf_url
    return "", ""


def _filter_ntrs_pdf_links(
    raw_hrefs: list[str],
    *,
    query: str = "",
    titles: list[str] | None = None,
) -> list[NtrsSource]:
    """Keep NTRS PDF/download URLs; dedupe by citation_id."""
    title_list = titles or []
    seen: set[str] = set()
    out: list[NtrsSource] = []
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for idx, raw in enumerate(raw_hrefs):
        citation_id, pdf_url = _canonical_ntrs_pdf_url(raw)
        if not citation_id or citation_id in seen:
            continue
        seen.add(citation_id)
        title = title_list[idx].strip() if idx < len(title_list) else ""
        out.append(
            {
                "citation_id": citation_id,
                "pdf_url": pdf_url,
                "title": title,
                "query": query,
                "discovered_at": now,
            }
        )
    return out


def _build_google_ntrs_search_urls(
    queries: list[str],
    pages_per_query: int,
) -> list[tuple[str, str]]:
    """Return (google_search_url, query_term) pairs."""
    pairs: list[tuple[str, str]] = []
    for query in queries:
        for page in range(pages_per_query):
            q = f"site:ntrs.nasa.gov {query} filetype:pdf"
            start = page * 10
            url = (
                f"https://www.google.com/search?q={quote(q)}&num=10"
                f"{f'&start={start}' if start else ''}"
            )
            pairs.append((url, query))
    return pairs


def _search_queries(override: list[str] | None) -> list[str]:
    if override:
        return override
    return list(SEARCH_QUERIES)


def _report_text_data_url(text: str) -> str:
    escaped = html.escape(text)
    body = f"<html><head><meta charset='utf-8'></head><body><pre>{escaped}</pre></body></html>"
    return "data:text/html;charset=utf-8," + quote(body)


def _pdf_text(path: Path, max_chars: int = PDF_TEXT_MAX_CHARS) -> str:
    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        full = "\n".join(parts).strip()
        if len(full) > max_chars:
            cut = full[:max_chars]
            para = cut.rfind("\n\n")
            if para > max_chars // 2:
                cut = cut[:para]
            full = cut
        return full
    except Exception:
        return ""


def _download_ntrs_pdf(pdf_url: str, citation_id: str) -> Path:
    dest = PDF_CACHE_DIR / f"{citation_id}.pdf"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = httpx.get(
        pdf_url,
        follow_redirects=True,
        timeout=60,
        headers=HTTP_HEADERS,
    )
    resp.raise_for_status()
    content = resp.content
    if not content.startswith(b"%PDF"):
        raise ValueError(f"response is not a PDF: {pdf_url}")
    dest.write_bytes(content)
    return dest


def _read_ntrs_sources_cache() -> list[NtrsSource]:
    if not NTRS_SOURCES_CACHE.exists():
        return []
    try:
        with open(NTRS_SOURCES_CACHE, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(
            f"Malformed {NTRS_SOURCES_CACHE}: {exc}. Re-run with --discover to rebuild.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(data, list):
        print(
            f"Malformed {NTRS_SOURCES_CACHE}: expected a JSON list.",
            file=sys.stderr,
        )
        sys.exit(1)
    out: list[NtrsSource] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        citation_id = str(item.get("citation_id", "")).strip()
        pdf_url = str(item.get("pdf_url", "")).strip()
        if citation_id and pdf_url:
            out.append(
                {
                    "citation_id": citation_id,
                    "pdf_url": pdf_url,
                    "title": str(item.get("title", "")).strip(),
                    "query": str(item.get("query", "")).strip(),
                    "discovered_at": str(item.get("discovered_at", "")).strip(),
                }
            )
    return out


def _write_ntrs_sources_cache(sources: list[NtrsSource]) -> None:
    try:
        with open(NTRS_SOURCES_CACHE, "w", encoding="utf-8") as fh:
            json.dump(sources, fh, indent=2)
            fh.write("\n")
    except OSError as exc:
        print(f"Failed to write {NTRS_SOURCES_CACHE}: {exc}", file=sys.stderr)
        sys.exit(1)


def _require_ntrs_sources_cache() -> list[NtrsSource]:
    sources = _read_ntrs_sources_cache()
    if not sources:
        print(
            f"Missing or empty {NTRS_SOURCES_CACHE}. "
            "Run with --discover --source ntrs to create it.",
            file=sys.stderr,
        )
        sys.exit(1)
    return sources


def _read_ntrs_fields_cache() -> dict[str, dict[str, str]]:
    if not NTRS_FIELDS_CACHE.exists():
        return {}
    try:
        with open(NTRS_FIELDS_CACHE, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(
            f"Malformed {NTRS_FIELDS_CACHE}: {exc}. Re-run with --extract to rebuild.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(data, dict):
        print(
            f"Malformed {NTRS_FIELDS_CACHE}: expected a JSON object.",
            file=sys.stderr,
        )
        sys.exit(1)
    normalized: dict[str, dict[str, str]] = {}
    for url, fields in data.items():
        if isinstance(fields, dict):
            normalized[str(url).strip()] = _normalize_failure_fields(fields)
    return normalized


def _write_ntrs_fields_cache(fields_by_url: dict[str, dict[str, str]]) -> None:
    try:
        with open(NTRS_FIELDS_CACHE, "w", encoding="utf-8") as fh:
            json.dump(fields_by_url, fh, indent=2)
            fh.write("\n")
    except OSError as exc:
        print(f"Failed to write {NTRS_FIELDS_CACHE}: {exc}", file=sys.stderr)
        sys.exit(1)


def _require_ntrs_fields_cache() -> dict[str, dict[str, str]]:
    if not NTRS_FIELDS_CACHE.exists():
        print(
            f"Missing {NTRS_FIELDS_CACHE}. Run with --extract --source ntrs to create it.",
            file=sys.stderr,
        )
        sys.exit(1)
    return _read_ntrs_fields_cache()


def _merge_ntrs_sources(existing: list[NtrsSource], new_items: list[NtrsSource]) -> list[NtrsSource]:
    by_id = {item["citation_id"]: item for item in existing}
    for item in new_items:
        by_id[item["citation_id"]] = item
    return list(by_id.values())


def _ntrs_hrefs_from_observe(client: Stagehand, session_id: str) -> list[str]:
    response = client.sessions.observe(
        id=session_id,
        instruction=(
            "Find every link on this page whose href points to ntrs.nasa.gov and is a "
            "PDF download or /api/citations/.../downloads/ endpoint."
        ),
    )
    hrefs: list[str] = []
    results = getattr(getattr(response, "data", None), "result", None) or []
    for action in results:
        if hasattr(action, "model_dump"):
            blob = json.dumps(action.model_dump())
        elif hasattr(action, "to_dict"):
            blob = json.dumps(action.to_dict())
        elif isinstance(action, dict):
            blob = json.dumps(action)
        else:
            blob = str(action)
        hrefs.extend(_NTRS_HREF_IN_TEXT_RE.findall(blob))
    return hrefs


def _discover_google_ntrs_hrefs(
    client: Stagehand,
    session_id: str,
    *,
    cdp_url: str = "",
) -> list[str]:
    result = _session_evaluate_js(client, session_id, _ALL_HREF_JS, cdp_url=cdp_url)
    if isinstance(result, list):
        hrefs = [str(href).strip() for href in result if str(href or "").strip()]
        if hrefs:
            return hrefs
    return _ntrs_hrefs_from_observe(client, session_id)


def _is_google_blocked(client: Stagehand, session_id: str, *, cdp_url: str = "") -> bool:
    body = _session_evaluate_js(client, session_id, _PAGE_TEXT_JS, cdp_url=cdp_url)
    title = _session_evaluate_js(client, session_id, _PAGE_TITLE_JS, cdp_url=cdp_url)
    blob = f"{body} {title}"
    return bool(_CAPTCHA_RE.search(str(blob)))


def _maybe_dismiss_google_consent(client: Stagehand, session_id: str) -> None:
    global _GOOGLE_CONSENT_DISMISSED
    if _GOOGLE_CONSENT_DISMISSED:
        return
    try:
        client.sessions.act(
            id=session_id,
            input=(
                "If a cookie consent or privacy dialog is visible, accept or dismiss it. "
                "Otherwise do nothing."
            ),
        )
        _GOOGLE_CONSENT_DISMISSED = True
    except Exception:
        pass


def _discover_ntrs_pdf_links(
    client: Stagehand,
    session_id: str,
    google_url: str,
    query: str,
    *,
    cdp_url: str = "",
) -> list[NtrsSource]:
    client.sessions.navigate(id=session_id, url=google_url)
    _maybe_dismiss_google_consent(client, session_id)
    if _is_google_blocked(client, session_id, cdp_url=cdp_url):
        raise RuntimeError("Google blocked the session (CAPTCHA or unusual traffic)")
    client.sessions.act(
        id=session_id,
        input=(
            "Scroll through all visible Google search results so every result link "
            "to ntrs.nasa.gov is revealed. Do not follow the links."
        ),
    )
    raw_hrefs = _discover_google_ntrs_hrefs(client, session_id, cdp_url=cdp_url)
    return _filter_ntrs_pdf_links(raw_hrefs, query=query)


def _extract_ntrs_from_text(
    client: Stagehand,
    session_id: str,
    text: str,
    preset_title: str = "",
    preset_ntrs_id: str = "",
) -> tuple[dict[str, str], str, str]:
    if not text.strip():
        return {key: "" for key in FIELD_KEYS}, preset_title, preset_ntrs_id

    page_url = _report_text_data_url(text)
    client.sessions.navigate(id=session_id, url=page_url)
    client.sessions.act(
        id=session_id,
        input="Scroll through the full document text from top to bottom.",
    )
    identity_raw = _session_extract(
        client,
        session_id,
        instruction=(
            "Extract the report title and any NTRS or NASA catalog document id "
            "mentioned in the text."
        ),
        schema_model=ReportIdentity,
    )
    identity = _to_plain_dict(identity_raw)
    title = (preset_title or str(identity.get("title", ""))).strip()
    ntrs_id = (preset_ntrs_id or str(identity.get("ntrs_id", ""))).strip()

    fields_raw = _session_extract(
        client,
        session_id,
        instruction=NTRS_FAILURE_EXTRACT_INSTRUCTION,
        schema_model=FailureReport,
    )
    fields = _normalize_failure_fields(fields_raw)
    return fields, title, ntrs_id


def _extract_ntrs_pdf(
    client: Stagehand,
    session_id: str,
    source: NtrsSource,
) -> tuple[dict[str, str], str, str]:
    pdf_path = _download_ntrs_pdf(source["pdf_url"], source["citation_id"])
    text = _pdf_text(pdf_path)
    if len(text) < 500:
        print(
            f"  warning: low text quality ({len(text)} chars) for {source['citation_id']}; "
            "trying in-browser PDF viewer"
        )
        client.sessions.navigate(id=session_id, url=source["pdf_url"])
        client.sessions.act(
            id=session_id,
            input=(
                "Scroll through the full PDF document so all pages and text are visible."
            ),
        )
        fields_raw = _session_extract(
            client,
            session_id,
            instruction=NTRS_FAILURE_EXTRACT_INSTRUCTION,
            schema_model=FailureReport,
        )
        fields = _normalize_failure_fields(fields_raw)
        return fields, source["title"], source["citation_id"]
    return _extract_ntrs_from_text(
        client,
        session_id,
        text,
        preset_title=source["title"],
        preset_ntrs_id=source["citation_id"],
    )


def _run_discover_ntrs(
    client: Stagehand,
    session_id: str,
    cdp_url: str,
    queries: list[str],
    google_pages: int,
    stats: dict[str, int],
    errors: list[str],
) -> list[NtrsSource]:
    existing = _read_ntrs_sources_cache()
    seen: set[str] = {item["citation_id"] for item in existing}
    discovered: list[NtrsSource] = list(existing)

    for google_url, query in _build_google_ntrs_search_urls(queries, google_pages):
        print(f"\nGoogle NTRS search: {query!r} ({google_url})")
        try:
            candidates = _discover_ntrs_pdf_links(
                client,
                session_id,
                google_url,
                query,
                cdp_url=cdp_url,
            )
        except Exception as exc:
            stats["errored"] += 1
            msg = f"{google_url} ({query!r}): {type(exc).__name__}: {exc}"
            errors.append(msg)
            print(f"  listing error: {msg}")
            if GOOGLE_DELAY_SEC > 0:
                time.sleep(GOOGLE_DELAY_SEC)
            continue

        print(f"  found {len(candidates)} NTRS PDF link(s) on this page")
        for item in candidates:
            if item["citation_id"] not in seen:
                seen.add(item["citation_id"])
                discovered.append(item)

        if GOOGLE_DELAY_SEC > 0:
            time.sleep(GOOGLE_DELAY_SEC)

    merged = _merge_ntrs_sources(existing, discovered)
    _write_ntrs_sources_cache(merged)
    print(f"\nDiscovered {len(merged)} unique NTRS PDF(s); wrote {NTRS_SOURCES_CACHE}")
    return merged


def _run_extract_ntrs(
    client: Stagehand,
    session_id: str,
    sources: list[NtrsSource],
    limit: int,
    refresh: bool,
    stats: dict[str, int],
    errors: list[str],
) -> None:
    fields_cache = _read_ntrs_fields_cache()
    remaining = limit
    extracted = 0
    skipped_empty = 0
    errored = 0

    for source in sources:
        if remaining <= 0:
            break
        pdf_url = source["pdf_url"]
        if pdf_url in fields_cache and not refresh:
            stats["skipped"] += 1
            continue

        stats["scraped"] += 1
        try:
            fields, title, _ntrs_id = _extract_ntrs_pdf(client, session_id, source)
            if _is_empty_or_404_lesson(fields, title):
                fields_cache.pop(pdf_url, None)
                skipped_empty += 1
                stats["skipped"] += 1
                print(f"  skip (empty/404): {pdf_url}")
            else:
                fields_cache[pdf_url] = fields
                extracted += 1
                stats["kept"] += 1
                summary = _one_line_summary(fields)
                print(f"  extracted {source['citation_id']}: {summary}")
        except Exception as exc:
            errored += 1
            stats["errored"] += 1
            msg = f"{pdf_url}: {type(exc).__name__}: {exc}"
            errors.append(msg)
            print(f"  error: {msg}")
        finally:
            if REPORT_DELAY_SEC > 0:
                time.sleep(REPORT_DELAY_SEC)
        remaining -= 1

    _write_ntrs_fields_cache(fields_cache)
    print(f"\nWrote {len(fields_cache)} NTRS field record(s) to {NTRS_FIELDS_CACHE}")
    print(
        f"Extract summary — extracted-with-content={extracted} "
        f"skipped-empty={skipped_empty} errored={errored}"
    )


def _load_ntrs_report(
    source: NtrsSource,
    fields: dict[str, str],
    mem: Memory | None,
    dry_run: bool,
    stats: dict[str, int],
    errors: list[str],
) -> None:
    stats["scraped"] += 1
    pdf_url = source["pdf_url"]
    try:
        if not fields["failure_mode"] and not fields["root_cause"]:
            stats["skipped"] += 1
            print(f"  skip (empty failure_mode and root_cause): {pdf_url}")
            return

        if not _is_relevant(fields):
            stats["skipped"] += 1
            print(f"  skip (not propulsion/fluid relevant): {pdf_url}")
            return

        slug = _make_slug(source["title"], pdf_url, ntrs_id=source["citation_id"])
        summary = _one_line_summary(fields)

        if dry_run:
            stats["kept"] += 1
            print(f"  [dry-run] {slug}: {summary}")
            for key in FIELD_KEYS:
                print(f"    {key}: {fields[key][:200]}")
            return

        key = mem.write_failure("external", slug, fields)
        stats["kept"] += 1
        print(f"  stored {key}: {summary}")
    except Exception as exc:
        stats["errored"] += 1
        msg = f"{pdf_url}: {type(exc).__name__}: {exc}"
        errors.append(msg)
        print(f"  error: {msg}")


def _run_load_ntrs(
    sources: list[NtrsSource],
    fields_cache: dict[str, dict[str, str]],
    limit: int,
    dry_run: bool,
    mem: Memory | None,
    stats: dict[str, int],
    errors: list[str],
) -> None:
    by_url = {item["pdf_url"]: item for item in sources}
    remaining = limit
    for pdf_url, fields in fields_cache.items():
        if remaining <= 0:
            break
        source = by_url.get(pdf_url)
        if not source:
            source = {
                "citation_id": _ntrs_id_from_url(pdf_url),
                "pdf_url": pdf_url,
                "title": "",
                "query": "",
                "discovered_at": "",
            }
        _load_ntrs_report(source, fields, mem, dry_run, stats, errors)
        remaining -= 1


def _filter_llis_lesson_links(raw_hrefs: list[str]) -> list[tuple[str, str]]:
    """Keep only real anchor hrefs whose path matches /lesson/{digits}; dedupe."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for raw in raw_hrefs:
        raw = (raw or "").strip()
        if not raw or not _LESSON_PATH_RE.search(raw):
            continue
        resolved = urljoin(f"{LLIS_BASE}/", raw)
        path_match = _LESSON_PATH_RE.search(resolved)
        if not path_match:
            continue
        id_match = re.search(r"/lesson/(\d+)", path_match.group(0))
        if not id_match:
            continue
        canonical = f"{LLIS_BASE}/lesson/{id_match.group(1)}"
        if canonical not in seen:
            seen.add(canonical)
            out.append((canonical, ""))
    return out


def _ntrs_id_from_url(url: str) -> str:
    match = re.search(r"/citations/(\d{10,})", url) or re.search(r"(\d{11})", url)
    return match.group(1) if match else ""


def _make_slug(title: str, url: str, ntrs_id: str = "") -> str:
    llis_match = re.search(r"/lesson/(\d+)", url)
    if llis_match:
        return f"llis_{llis_match.group(1)}"
    catalog_id = (ntrs_id or _ntrs_id_from_url(url)).strip()
    if catalog_id:
        slug = f"ntrs_{catalog_id}"
    else:
        base = title.strip() or urlparse(url).path.rstrip("/").split("/")[-1] or "report"
        slug = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
        slug = re.sub(r"_+", "_", slug) or "report"
    return slug[:120]


def _pair_discovered_links(
    raw_links: list[str],
    titles: list[str],
    normalize_link: Callable[[str], str | None],
) -> list[tuple[str, str]]:
    """Normalize/dedupe discovered links and pair with titles by original index."""
    while len(titles) < len(raw_links):
        titles.append("")
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for raw_link, title in zip(raw_links, titles, strict=False):
        link = normalize_link(raw_link)
        if link and link not in seen:
            seen.add(link)
            out.append((link, title))
    return out


def _one_line_summary(fields: dict[str, str]) -> str:
    mode = fields.get("failure_mode", "") or fields.get("root_cause", "")
    return (mode[:120] + "...") if len(mode) > 120 else mode


def _build_search_urls() -> list[str]:
    return [
        f"https://llis.nasa.gov/search?page={page}&query={quote(query)}"
        for query in SEARCH_QUERIES
        for page in range(1, PAGES_PER_QUERY + 1)
    ]


def _read_urls_cache() -> list[str]:
    try:
        with open(URLS_CACHE, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(
            f"Missing {URLS_CACHE}. Run with --discover (or a full run) to create it.",
            file=sys.stderr,
        )
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(
            f"Malformed {URLS_CACHE}: {exc}. Re-run with --discover to rebuild the cache.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(data, list):
        print(
            f"Malformed {URLS_CACHE}: expected a JSON list of URLs. "
            "Re-run with --discover to rebuild the cache.",
            file=sys.stderr,
        )
        sys.exit(1)
    return [str(url).strip() for url in data if str(url).strip()]


def _write_urls_cache(urls: list[str]) -> None:
    try:
        with open(URLS_CACHE, "w", encoding="utf-8") as fh:
            json.dump(urls, fh, indent=2)
            fh.write("\n")
    except OSError as exc:
        print(f"Failed to write {URLS_CACHE}: {exc}", file=sys.stderr)
        sys.exit(1)


def _read_fields_cache() -> dict[str, dict[str, str]]:
    if not FIELDS_CACHE.exists():
        return {}
    try:
        with open(FIELDS_CACHE, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(
            f"Malformed {FIELDS_CACHE}: {exc}. Re-run with --extract to rebuild the cache.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(data, dict):
        print(
            f"Malformed {FIELDS_CACHE}: expected a JSON object mapping URLs to fields. "
            "Re-run with --extract to rebuild the cache.",
            file=sys.stderr,
        )
        sys.exit(1)
    normalized: dict[str, dict[str, str]] = {}
    for url, fields in data.items():
        if not isinstance(fields, dict):
            print(
                f"Malformed {FIELDS_CACHE}: entry for {url!r} is not an object. "
                "Re-run with --extract to rebuild the cache.",
                file=sys.stderr,
            )
            sys.exit(1)
        normalized[str(url).strip()] = _normalize_failure_fields(fields)
    return normalized


def _write_fields_cache(fields_by_url: dict[str, dict[str, str]]) -> None:
    try:
        with open(FIELDS_CACHE, "w", encoding="utf-8") as fh:
            json.dump(fields_by_url, fh, indent=2)
            fh.write("\n")
    except OSError as exc:
        print(f"Failed to write {FIELDS_CACHE}: {exc}", file=sys.stderr)
        sys.exit(1)


def _require_fields_cache() -> dict[str, dict[str, str]]:
    if not FIELDS_CACHE.exists():
        print(
            f"Missing {FIELDS_CACHE}. Run with --extract (or a full run) to create it.",
            file=sys.stderr,
        )
        sys.exit(1)
    return _read_fields_cache()


def _discover_report_links(
    client: Stagehand,
    session_id: str,
    page_url: str,
    *,
    cdp_url: str = "",
) -> list[tuple[str, str]]:
    client.sessions.navigate(id=session_id, url=page_url)
    client.sessions.act(
        id=session_id,
        input=(
            "If this is a search or listing page, scroll enough to reveal individual "
            "failure report, lessons learned, or NTRS citation links. Do not follow them."
        ),
    )
    if _is_llis_page_url(page_url):
        raw_links = _discover_llis_lesson_hrefs(client, session_id, cdp_url=cdp_url)
        return _filter_llis_lesson_links(raw_links)

    raw = _session_extract(
        client,
        session_id,
        instruction=GENERIC_DISCOVERY_EXTRACT_INSTRUCTION,
        schema_model=ReportListing,
    )
    data = _to_plain_dict(raw)
    raw_links = list(data.get("report_links") or [])
    titles = [str(t or "").strip() for t in (data.get("report_titles") or [])]
    return _pair_discovered_links(
        raw_links,
        titles,
        lambda link: urljoin(page_url, (link or "").strip()) if (link or "").strip() else None,
    )


def _extract_report(
    client: Stagehand,
    session_id: str,
    report_url: str,
    preset_title: str = "",
) -> tuple[dict[str, str], str, str]:
    client.sessions.navigate(id=session_id, url=report_url)
    if _is_llis_lesson_url(report_url):
        act_input = (
            "Scroll through the full LLIS lesson page so every named section is visible: "
            "Subject, Abstract, Driving Event, Lesson(s) Learned, Recommendation(s), "
            "Evidence of Recurrence Control, Program Relation, and Topic(s)."
        )
    else:
        act_input = (
            "Open the main report body if it is collapsed or behind tabs, then scroll "
            "through the full failure description, root cause, and corrective actions."
        )
    client.sessions.act(id=session_id, input=act_input)
    identity_raw = _session_extract(
        client,
        session_id,
        instruction=(
            "Extract the report title and any NTRS or NASA catalog document id shown "
            "on this page."
        ),
        schema_model=ReportIdentity,
    )
    identity = _to_plain_dict(identity_raw)
    title = (preset_title or str(identity.get("title", ""))).strip()
    ntrs_id = str(identity.get("ntrs_id", "")).strip()

    extract_instruction = (
        LLIS_FAILURE_EXTRACT_INSTRUCTION
        if _is_llis_lesson_url(report_url)
        else GENERIC_FAILURE_EXTRACT_INSTRUCTION
    )
    fields_raw = _session_extract(
        client,
        session_id,
        instruction=extract_instruction,
        schema_model=FailureReport,
    )
    fields = _normalize_failure_fields(fields_raw)
    return fields, title, ntrs_id


def _run_discover_llis(
    client: Stagehand,
    session_id: str,
    cdp_url: str,
    stats: dict[str, int],
    errors: list[str],
) -> list[str]:
    seen_lessons: set[str] = set()
    unique_lessons: list[str] = []

    for search_url in _build_search_urls():
        print(f"\nSearch: {search_url}")
        try:
            candidates = _discover_report_links(
                client, session_id, search_url, cdp_url=cdp_url
            )
        except Exception as exc:
            stats["errored"] += 1
            msg = f"{search_url} (listing): {type(exc).__name__}: {exc}"
            errors.append(msg)
            print(f"  listing error: {msg}")
            continue

        print(f"  found {len(candidates)} real lesson href(s) on this page")
        for report_url, _preset_title in candidates:
            if report_url not in seen_lessons:
                seen_lessons.add(report_url)
                unique_lessons.append(report_url)

    _write_urls_cache(unique_lessons)
    print(f"\nDiscovered {len(unique_lessons)} unique lesson URL(s); wrote {URLS_CACHE}")
    return unique_lessons


def _run_extract_llis(
    client: Stagehand,
    session_id: str,
    urls: list[str],
    limit: int,
    refresh: bool,
    stats: dict[str, int],
    errors: list[str],
) -> None:
    fields_cache = _read_fields_cache()
    remaining = limit
    extracted = 0
    skipped_empty = 0
    errored = 0

    for report_url in urls:
        if remaining <= 0:
            break
        if report_url in fields_cache and not refresh:
            stats["skipped"] += 1
            continue

        stats["scraped"] += 1
        try:
            fields, title, _ntrs_id = _extract_report(client, session_id, report_url)
            if _is_empty_or_404_lesson(fields, title):
                fields_cache.pop(report_url, None)
                skipped_empty += 1
                stats["skipped"] += 1
                print(f"  skip (empty/404): {report_url}")
            else:
                fields_cache[report_url] = fields
                extracted += 1
                stats["kept"] += 1
                summary = _one_line_summary(fields)
                print(f"  extracted {report_url}: {summary}")
        except Exception as exc:
            errored += 1
            stats["errored"] += 1
            msg = f"{report_url}: {type(exc).__name__}: {exc}"
            errors.append(msg)
            print(f"  error: {msg}")
        finally:
            if REPORT_DELAY_SEC > 0:
                time.sleep(REPORT_DELAY_SEC)
        remaining -= 1

    _write_fields_cache(fields_cache)
    print(f"\nWrote {len(fields_cache)} lesson field record(s) to {FIELDS_CACHE}")
    print(
        f"Extract summary — extracted-with-content={extracted} "
        f"skipped-empty={skipped_empty} errored={errored}"
    )


def _load_report(
    report_url: str,
    fields: dict[str, str],
    mem: Memory | None,
    dry_run: bool,
    stats: dict[str, int],
    errors: list[str],
) -> None:
    stats["scraped"] += 1
    try:
        if not fields["failure_mode"] and not fields["root_cause"]:
            stats["skipped"] += 1
            print(f"  skip (empty failure_mode and root_cause): {report_url}")
            return

        if not _is_relevant(fields):
            stats["skipped"] += 1
            print(f"  skip (not propulsion/fluid relevant): {report_url}")
            return

        slug = _make_slug("", report_url)
        summary = _one_line_summary(fields)

        if dry_run:
            stats["kept"] += 1
            print(f"  [dry-run] {slug}: {summary}")
            for key in FIELD_KEYS:
                print(f"    {key}: {fields[key][:200]}")
            return

        key = mem.write_failure("external", slug, fields)
        stats["kept"] += 1
        print(f"  stored {key}: {summary}")
    except Exception as exc:
        stats["errored"] += 1
        msg = f"{report_url}: {type(exc).__name__}: {exc}"
        errors.append(msg)
        print(f"  error: {msg}")


def _run_load_llis(
    fields_cache: dict[str, dict[str, str]],
    limit: int,
    dry_run: bool,
    mem: Memory | None,
    stats: dict[str, int],
    errors: list[str],
) -> None:
    remaining = limit
    for report_url, fields in fields_cache.items():
        if remaining <= 0:
            break
        _load_report(report_url, fields, mem, dry_run, stats, errors)
        remaining -= 1


def run(
    phases: list[str],
    limit: int,
    dry_run: bool,
    refresh: bool,
    source: str = "llis",
    queries: list[str] | None = None,
    google_pages: int = GOOGLE_PAGES_PER_QUERY,
) -> int:
    run_llis = source in ("llis", "all")
    run_ntrs = source in ("ntrs", "all")
    search_queries = _search_queries(queries)

    needs_session = "discover" in phases or "extract" in phases
    needs_browser = needs_session and (
        (run_llis and ("discover" in phases or "extract" in phases))
        or (run_ntrs and ("discover" in phases or "extract" in phases))
    )

    print(f"env vars present: {_env_ready()}")
    print(f"source={source!r} queries={search_queries!r} google_pages={google_pages}")
    if needs_browser and not _env_ready():
        missing = [k for k in ENV_KEYS if not os.environ.get(k)]
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        return 1

    mem: Memory | None = None
    if "load" in phases and not dry_run:
        mem = Memory()

    client: Stagehand | None = None
    session_id: str | None = None
    cdp_url = ""
    stats = {"scraped": 0, "kept": 0, "skipped": 0, "errored": 0}
    errors: list[str] = []

    try:
        if needs_browser:
            client = Stagehand()
            resp = client.sessions.start(model_name="anthropic/claude-sonnet-4-6")
            session_id = resp.data.session_id
            cdp_url = resp.data.cdp_url or ""
            print(f"Stagehand session: {session_id}")

        if "discover" in phases:
            if run_llis:
                _run_discover_llis(client, session_id, cdp_url, stats, errors)
            if run_ntrs:
                _run_discover_ntrs(
                    client,
                    session_id,
                    cdp_url,
                    search_queries,
                    google_pages,
                    stats,
                    errors,
                )

        if "extract" in phases:
            if run_llis:
                urls = _read_urls_cache()
                print(f"\nExtract LLIS: {len(urls)} URL(s) in {URLS_CACHE}")
                _run_extract_llis(client, session_id, urls, limit, refresh, stats, errors)
            if run_ntrs:
                sources = _require_ntrs_sources_cache()
                print(f"\nExtract NTRS: {len(sources)} PDF(s) in {NTRS_SOURCES_CACHE}")
                _run_extract_ntrs(client, session_id, sources, limit, refresh, stats, errors)

        if "load" in phases:
            if run_llis:
                fields_cache = _require_fields_cache()
                print(f"\nLoad LLIS: {len(fields_cache)} record(s) in {FIELDS_CACHE}")
                _run_load_llis(fields_cache, limit, dry_run, mem, stats, errors)
            if run_ntrs:
                ntrs_sources = _require_ntrs_sources_cache()
                ntrs_fields = _require_ntrs_fields_cache()
                print(f"\nLoad NTRS: {len(ntrs_fields)} record(s) in {NTRS_FIELDS_CACHE}")
                _run_load_ntrs(ntrs_sources, ntrs_fields, limit, dry_run, mem, stats, errors)
    finally:
        if session_id and client:
            client.sessions.end(id=session_id)

    print(
        "\nSummary — "
        f"scraped={stats['scraped']} kept={stats['kept']} "
        f"skipped={stats['skipped']} errored={stats['errored']}"
    )
    if errors:
        print("Errors:")
        for err in errors:
            print(f"  - {err}")

    return 1 if stats["errored"] and stats["kept"] == 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape NASA failure reports with Stagehand and store in Redis."
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Discover lesson URLs and write them to the URLs cache.",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Extract fields from cached URLs and write them to the fields cache.",
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Apply the relevance gate and load cached fields into Redis.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="In --extract, re-extract every URL instead of skipping cached entries.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="In --load (and full runs), print kept records instead of writing to Redis.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        metavar="N",
        help=f"Maximum reports to extract or load per source per run (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--source",
        choices=("llis", "ntrs", "all"),
        default="llis",
        help="Ingestion source: LLIS site search, NTRS Google PDF search, or both (default: llis).",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        metavar="TERM",
        help="Override SEARCH_QUERIES with one or more ad-hoc search terms (repeatable).",
    )
    parser.add_argument(
        "--google-pages",
        type=int,
        default=GOOGLE_PAGES_PER_QUERY,
        metavar="N",
        help=f"Google result pages per NTRS query (default: {GOOGLE_PAGES_PER_QUERY}).",
    )
    args = parser.parse_args()

    if args.limit < 1:
        print("--limit must be at least 1", file=sys.stderr)
        sys.exit(1)
    if args.google_pages < 1:
        print("--google-pages must be at least 1", file=sys.stderr)
        sys.exit(1)

    if args.discover or args.extract or args.load:
        phases = []
        if args.discover:
            phases.append("discover")
        if args.extract:
            phases.append("extract")
        if args.load:
            phases.append("load")
    else:
        phases = ["discover", "extract", "load"]

    sys.exit(
        run(
            phases=phases,
            limit=args.limit,
            dry_run=args.dry_run,
            refresh=args.refresh,
            source=args.source,
            queries=args.queries,
            google_pages=args.google_pages,
        )
    )


if __name__ == "__main__":
    main()
