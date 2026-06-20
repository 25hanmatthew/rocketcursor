"""Package-local paths for ingest caches and downloaded PDFs."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

URLS_CACHE = PACKAGE_DIR / "lesson_urls.json"
FIELDS_CACHE = PACKAGE_DIR / "lesson_fields.json"
NTRS_SOURCES_CACHE = PACKAGE_DIR / "ntrs_sources.json"
NTRS_FIELDS_CACHE = PACKAGE_DIR / "ntrs_fields.json"
PDF_CACHE_DIR = PACKAGE_DIR / "pdfs" / "ntrs"
