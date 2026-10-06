"""Phase 0 (data acquisition): PDF parsing, fact extraction, web discovery."""

from __future__ import annotations

from pathlib import Path

from edumatch.ingest.pdf_facts import extract_pdf_facts, infer_school_year
from edumatch.ingest.pdf_reader import PdfText
from edumatch.sources.education_web import EducationWebCollector


def _pdf_text(body: str) -> PdfText:
    pdf = PdfText(path="x.pdf", n_pages=1, pages_with_text=1, char_count=len(body),
                  sha1="deadbeef", text_status="ok", text=body)
    pdf.page_offsets = [0]
    return pdf


def test_infer_school_and_year_from_filename():
    path = Path("北京工业大学2021届毕业生就业质量年度报告.pdf")
    school, year = infer_school_year(path)
    assert school == "北京工业大学"
    assert year == 2021


def test_percent_label_uses_nearest_left_keyword():
    """Regression: '签约率…就业率为 99.75%' must not label 99.75% as a signing rate."""
    body = "低亍学校平均签约率，硕士毕业生高亍学校平均签约率。硕士毕业生就业率为 99.75%，高于"
    facts = extract_pdf_facts(_pdf_text(body), school="X", year=2020)
    types = {f.fact_type: f.value for f in facts}
    assert types.get("employment_rate") == 0.9975
    assert "signing_rate" not in types


def test_counts_and_ratios_extracted_with_page():
    body = "2021 届毕业生共有 5975 人\n毕业生在京就业比例为 68.36%\n毕业去向落实率为 95.20%"
    facts = extract_pdf_facts(_pdf_text(body), school="X", year=2021)
    by_type = {f.fact_type: f for f in facts}
    assert by_type["graduates_total"].value == 5975
    assert by_type["beijing_employment_ratio"].value == 0.6836
    assert by_type["placement_rate"].value == 0.952
    assert all(f.page == 1 for f in facts)
    assert all(f.evidence_level == "A" for f in facts)


def test_no_text_layer_yields_no_facts():
    pdf = PdfText(path="scan.pdf", text_status="pdf_no_text_layer", text="", sha1="x")
    assert extract_pdf_facts(pdf, school="X", year=2019) == []


def _registry() -> dict:
    return {
        "keywords": {"就业质量报告": ["就业质量报告"]},
        "document_extensions": [".pdf"],
        "sources": {"某大学": {"listing": ["https://www.example.edu.cn/job/"]}},
    }


def test_web_collector_finds_documents_and_downloads(tmp_path):
    page = ('<html><a href="/files/2021就业质量报告.pdf">2021届毕业生就业质量报告</a>'
            '<a href="/other.htm">新闻</a></html>')

    def fetcher(url: str, ua: str) -> str:
        if url.endswith("robots.txt"):
            return "User-agent: *\nAllow: /\n"
        if url.endswith(".pdf"):
            return "%PDF-1.4 fake"          # binary content stand-in
        return page

    def robots_reader(url: str):
        class P:
            def can_fetch(self, ua, target):
                return True

        return P(), "ok"

    collector = EducationWebCollector(
        registry=_registry(), fetcher=fetcher, robots_reader=robots_reader
    )
    collector.download_dir = tmp_path
    collector.cache_dir = tmp_path / "cache"
    summary = collector.collect(limit_per_site=5)
    assert summary["n_downloaded"] == 1
    candidates = summary["candidates"]
    assert candidates and candidates[0]["doc_type"] == "就业质量报告"
    downloaded = Path(summary["downloads"][0]["local_path"])
    assert downloaded.exists() and downloaded.suffix == ".pdf"
    assert summary["downloads"][0]["sha1"]


def test_web_collector_respects_robots_denial(tmp_path):
    def fetcher(url: str, ua: str) -> str:
        return '<a href="/files/x就业质量报告.pdf">就业质量报告</a>'

    def robots_reader(url: str):
        class P:
            def can_fetch(self, ua, target):
                return False

        return P(), "ok"

    collector = EducationWebCollector(registry=_registry(), fetcher=fetcher, robots_reader=robots_reader)
    collector.download_dir = tmp_path
    collector.cache_dir = tmp_path / "cache"
    summary = collector.collect(dry_run=True)
    assert summary["listings"][0]["status"] == "error"
    assert "robots" in summary["listings"][0]["error"]
