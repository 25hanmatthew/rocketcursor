"""Unit tests for NTRS URL/PDF helpers (no browser required)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory import ingest_failures as ing


class NtrsUrlHelpersTest(unittest.TestCase):
    def test_unwrap_google_redirect(self) -> None:
        wrapped = (
            "https://www.google.com/url?q="
            "https%3A%2F%2Fntrs.nasa.gov%2Fapi%2Fcitations%2F20130000001"
            "%2Fdownloads%2F20130000001.pdf&sa=U"
        )
        self.assertEqual(
            ing._unwrap_google_redirect(wrapped),
            "https://ntrs.nasa.gov/api/citations/20130000001/downloads/20130000001.pdf",
        )

    def test_canonical_ntrs_pdf_url_from_download_path(self) -> None:
        url = "https://ntrs.nasa.gov/api/citations/20200000325/downloads/20200000325.pdf"
        cid, pdf = ing._canonical_ntrs_pdf_url(url)
        self.assertEqual(cid, "20200000325")
        self.assertEqual(pdf, url)

    def test_canonical_ntrs_pdf_url_from_citation_page(self) -> None:
        url = "https://ntrs.nasa.gov/citations/20200000325"
        cid, pdf = ing._canonical_ntrs_pdf_url(url)
        self.assertEqual(cid, "20200000325")
        self.assertIn("/api/citations/20200000325/downloads/", pdf)

    def test_filter_ntrs_pdf_links_dedupes(self) -> None:
        hrefs = [
            "https://ntrs.nasa.gov/api/citations/20130000001/downloads/20130000001.pdf",
            "https://www.google.com/url?q="
            "https%3A%2F%2Fntrs.nasa.gov%2Fapi%2Fcitations%2F20130000001"
            "%2Fdownloads%2F20130000001.pdf",
            "https://example.com/not-ntrs.pdf",
        ]
        out = ing._filter_ntrs_pdf_links(hrefs, query="rocket propulsion")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["citation_id"], "20130000001")
        self.assertEqual(out[0]["query"], "rocket propulsion")

    def test_build_google_ntrs_search_urls(self) -> None:
        pairs = ing._build_google_ntrs_search_urls(["rocket propulsion"], pages_per_query=2)
        self.assertEqual(len(pairs), 2)
        self.assertIn("site%3Antrs.nasa.gov", pairs[0][0])
        self.assertIn("filetype%3Apdf", pairs[0][0])
        self.assertEqual(pairs[0][1], "rocket propulsion")
        self.assertIn("start=10", pairs[1][0])

    def test_ntrs_id_from_api_download_url(self) -> None:
        url = "https://ntrs.nasa.gov/api/citations/19950012345/downloads/doc.pdf"
        self.assertEqual(ing._ntrs_id_from_url(url), "19950012345")

    def test_make_slug_ntrs(self) -> None:
        url = "https://ntrs.nasa.gov/api/citations/19950012345/downloads/doc.pdf"
        self.assertEqual(ing._make_slug("Title", url, ntrs_id="19950012345"), "ntrs_19950012345")


class NtrsPdfTextTest(unittest.TestCase):
    def test_pdf_text_reads_minimal_pdf(self) -> None:
        # Minimal valid PDF with "Hello" text (works with pypdf on most versions)
        minimal_pdf = (
            b"%PDF-1.1\n"
            b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
            b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
            b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
            b"4 0 obj<< /Length 44 >>stream\n"
            b"BT /F1 12 Tf 20 100 Td (Hello NTRS) Tj ET\n"
            b"endstream\nendobj\n"
            b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n"
            b"xref\n0 6\n0000000000 65535 f \n"
            b"trailer<< /Size 6 /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.pdf"
            path.write_bytes(minimal_pdf)
            text = ing._pdf_text(path)
            self.assertIn("Hello", text)


class NtrsDownloadTest(unittest.TestCase):
    def test_download_ntrs_pdf_validates_magic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ing, "PDF_CACHE_DIR", Path(tmp)):
                with patch("memory.ingest_failures.httpx.get") as mock_get:
                    mock_get.return_value.content = b"NOTPDF"
                    mock_get.return_value.raise_for_status = lambda: None
                    with self.assertRaises(ValueError):
                        ing._download_ntrs_pdf(
                            "https://ntrs.nasa.gov/api/citations/1/downloads/1.pdf",
                            "1",
                        )


if __name__ == "__main__":
    unittest.main()
