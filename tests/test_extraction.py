"""Evaluation dimension 1 & 2: extraction accuracy and skill normalisation."""

from __future__ import annotations

from edumatch.ingest.education_facts import extract_documents


def _find(facts, **kw):
    return [
        f for f in facts
        if all(getattr(f, k) == v for k, v in kw.items())
    ]


def test_extracts_real_employment_row(dataset):
    facts = _find(dataset.facts, school="北京交通大学", major="人工智能", year=2024)
    values = {f.fact_type: f.value for f in facts}
    # 来源：《北京交通大学2024届就业质量年度报告》表1-3
    assert values["graduates"] == 42
    assert values["further_study_rate"] == 0.5714
    assert values["signing_rate"] == 0.9048
    assert values["placement_rate"] == 0.9048


def test_school_faculty_ratio_not_scaled_by_100(dataset):
    """Regression: 生师比 33 must stay 33, not 0.33 (unit confusion bug).

    该断言针对**金标准解析器**（策展文档），因为分析数据源已改为报告 PDF 的自动抽取。
    """
    ratios = [
        f.value for f in dataset.golden_facts
        if f.fact_type == "student_faculty_ratio" and f.year == 2024 and f.school == "中央民族大学"
    ]
    assert ratios == [33.0]


def test_analysis_source_is_pdf_extraction_not_curated_docs(dataset):
    """分析只用 PDF 抽取结果；策展文档仅作校验金标准。"""
    assert dataset.golden_facts, "金标准应存在"
    assert not (set(f.fact_id for f in dataset.facts) & set(f.fact_id for f in dataset.golden_facts))
    assert all(f.evidence_level in {"A", "B", "C"} for f in dataset.facts), "分析数据应为官方报告抽取"
    assert dataset.major_rows_count > 0


def test_percentage_facts_are_fractions(dataset):
    for fact in dataset.facts:
        if fact.unit == "ratio":
            assert 0 <= fact.value <= 1, fact


def test_every_fact_is_traceable(dataset):
    for fact in dataset.facts:
        assert fact.source_document, fact
        assert fact.source_line > 0, fact
        assert fact.raw_text, fact


def test_duplicate_documents_detected(dataset):
    assert len(dataset.policy_duplicates) >= 1


def test_policy_text_is_read_or_flagged_never_guessed(dataset):
    """政策原文要么真的抽到正文，要么显式标记为不可抽取——不允许猜测填充。"""
    pdfs = [p for p in dataset.policies if p.extension == ".pdf"]
    assert pdfs, "archive contains policy PDFs"
    # 有文本层的 PDF 现在会被真实抽取（不再一律当作 extractor_unavailable）
    assert any(p.text_status == "ok" and p.char_count > 0 for p in pdfs)
    for policy in dataset.policies:
        if policy.text_status == "ok":
            assert policy.char_count > 0
        else:
            assert policy.text_status == "extractor_unavailable"
            assert policy.char_count == 0
            # 不可抽取的只能是拿不到文本层的格式，绝不可能是我们明确支持的 docx
            assert policy.extension != ".docx"
